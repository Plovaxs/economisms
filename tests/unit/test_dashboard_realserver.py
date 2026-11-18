"""The dashboard under a REAL uvicorn/h11 stack with the shared production
options, driven over raw sockets: what no hand-built ASGI scope can show --
the server's own `Server` header behaviour, its request-target parsing and
the whole path from a hostile request line to the response bytes."""

from __future__ import annotations

import hashlib
import json
import socket
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
import uvicorn

from prometheus.dashboard import app as app_module
from prometheus.dashboard.app import DashboardService
from prometheus.httpsec.server import uvicorn_options
from prometheus.service.auth import CredentialStore

TOKEN = "t" * 43


@dataclass
class Reply:
    status: int
    headers: dict[str, str]
    body: bytes


def send_raw(port: int, payload: bytes, *, timeout: float = 15.0) -> Reply:
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as sock:
        sock.sendall(payload)
        data = b""
        while chunk := sock.recv(65536):
            data += chunk
    head, _, body = data.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    headers = {}
    for line in lines[1:]:
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()
    return Reply(int(lines[0].split(" ", 2)[1]), headers, body)


def get(port: int, target: bytes, *, token: str | None = TOKEN) -> Reply:
    auth = b"Authorization: Bearer " + token.encode() + b"\r\n" if token else b""
    return send_raw(
        port, b"GET " + target + b" HTTP/1.1\r\nHost: d\r\nConnection: close\r\n" + auth + b"\r\n"
    )


@pytest.fixture(scope="module")
def port(tmp_path_factory: pytest.TempPathFactory) -> Iterator[int]:
    root = tmp_path_factory.mktemp("dash")
    auth = root / "auth.json"
    auth.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "credentials": [
                    {
                        "subject": "alice-sub",
                        "owner": "alice",
                        "scopes": ["read"],
                        "token_sha256": hashlib.sha256(TOKEN.encode()).hexdigest(),
                    }
                ],
            }
        )
    )
    auth.chmod(0o600)
    app = DashboardService(CredentialStore(auth), portfolios={})
    options = uvicorn_options(
        host="127.0.0.1", port=0, tls_cert=None, tls_key=None, max_connections=32
    )
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", **options))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "dashboard failed to start"
        time.sleep(0.02)
    yield server.servers[0].sockets[0].getsockname()[1]
    server.should_exit = True
    thread.join(15)


def test_a_real_authenticated_json_request_is_served_with_hardened_headers(port) -> None:
    reply = get(port, b"/dashboard/economy?format=json")
    assert reply.status == 200
    assert "economy" in json.loads(reply.body) or json.loads(reply.body)
    assert reply.headers["content-type"] == "application/json"
    assert reply.headers["x-content-type-options"] == "nosniff"
    assert reply.headers["x-frame-options"] == "DENY"
    assert reply.headers["cache-control"] == "no-store"
    assert "x-request-id" in reply.headers
    assert "server" not in reply.headers, "uvicorn's banner must not be sent"


def test_the_html_index_carries_a_script_less_csp(port) -> None:
    reply = get(port, b"/dashboard")
    assert reply.status == 200 and reply.headers["content-type"].startswith("text/html")
    csp = reply.headers["content-security-policy"]
    assert "default-src 'none'" in csp and "script-src" not in csp


def test_the_resource_exhaustion_request_is_refused_instantly_over_a_real_socket(port) -> None:
    started = time.monotonic()
    reply = get(port, b"/dashboard/portfolio-risk?n=100000000000&format=json")
    assert reply.status == 400
    assert time.monotonic() - started < 2.0
    assert "n must be an integer between 10 and 100000" in json.loads(reply.body)["error"]


def test_non_ascii_query_bytes_are_a_client_error_never_a_server_error(port) -> None:
    assert get(port, b"/dashboard/economy?q=\xc3\xa9").status == 400


def test_a_script_in_the_query_is_rejected_and_never_reflected(port) -> None:
    reply = get(port, b"/dashboard/model-usage?model_id=<script>alert(1)</script>&application=x")
    assert reply.status == 400
    assert b"<script>" not in reply.body


def test_no_token_is_401_for_every_path(port) -> None:
    for target in (b"/dashboard/economy", b"/dashboard/nope", b"/x"):
        reply = get(port, target, token=None)
        assert reply.status == 401
        assert reply.headers["www-authenticate"] == "Bearer"


def test_a_slow_view_does_not_stall_the_health_probe_on_the_real_server(port, monkeypatch) -> None:
    def slow_view(**kwargs):
        time.sleep(1.2)
        return {"slow": True}

    monkeypatch.setattr(app_module, "economy_explorer_as_json", slow_view)
    timings: dict[str, float] = {}

    def call_slow() -> None:
        started = time.monotonic()
        get(port, b"/dashboard/economy?format=json")
        timings["slow"] = time.monotonic() - started

    worker = threading.Thread(target=call_slow)
    worker.start()
    time.sleep(0.3)
    started = time.monotonic()
    assert get(port, b"/health/live", token=None).status == 200
    timings["health"] = time.monotonic() - started
    worker.join(10)
    assert timings["slow"] >= 1.0
    assert timings["health"] < 0.5, f"health probe stalled behind a slow view: {timings}"
