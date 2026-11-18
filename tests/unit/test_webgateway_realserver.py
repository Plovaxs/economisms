"""The gateway under a REAL uvicorn/h11 stack with its production options
(`uvicorn_options`), the REAL `HttpUpstreamTransport`, and raw sockets for
the client -- so these exercise what no hand-built ASGI scope can: the
server's own `raw_path`, its request-target parsing, its `Server` header
behaviour, HEAD framing, and the whole chain from a hostile request line
to the bytes a backend actually receives.

Everything binds `127.0.0.1:0`; no external network is touched."""

from __future__ import annotations

import http.server
import json
import socket
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
import uvicorn

from prometheus.httpsec.server import uvicorn_options
from prometheus.webgateway.app import GatewayConfig, WebGatewayService


@dataclass
class Stub:
    base: str
    hits: list[dict[str, str]]


def _start_stub(kind: str, evil_base: str | None = None) -> tuple[Stub, http.server.HTTPServer]:
    hits: list[dict[str, str]] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _serve(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(length)
            hits.append(
                {
                    "method": self.command,
                    "path": self.path,
                    "authorization": self.headers.get("Authorization", ""),
                    "x-forwarded-for": self.headers.get("X-Forwarded-For", ""),
                }
            )
            if self.path == "/redirect" and evil_base:
                self.send_response(302)
                self.send_header("Location", f"{evil_base}/stolen")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if self.path == "/slow":
                time.sleep(1.2)
            if self.path == "/created":
                body = b"{}"
                self.send_response(202)
                self.send_header("Location", "/v1/jobs/abc")
            else:
                body = json.dumps({"kind": kind, "path": self.path}).encode()
                self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Server", "stub-backend/1.0")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        do_GET = do_POST = do_HEAD = _serve

        def log_message(self, *args: object) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return Stub(f"http://127.0.0.1:{server.server_port}", hits), server


@dataclass
class Fixture:
    port: int
    jobs: Stub
    dashboard: Stub
    evil: Stub


@pytest.fixture(scope="module")
def gateway(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Fixture]:
    dist: Path = tmp_path_factory.mktemp("dist")
    (dist / "assets").mkdir()
    (dist / "index.html").write_text("<!doctype html><title>shell</title>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    evil, evil_server = _start_stub("evil")
    jobs, jobs_server = _start_stub("jobs", evil.base)
    dashboard, dashboard_server = _start_stub("dashboard")
    app = WebGatewayService(
        dist,
        jobs.base,
        dashboard.base,
        config=GatewayConfig(rate_limit_per_second=0, max_request_body_bytes=1000),
    )
    options = uvicorn_options(
        host="127.0.0.1", port=0, tls_cert=None, tls_key=None, max_connections=64
    )
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", **options))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "gateway failed to start"
        time.sleep(0.02)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield Fixture(port, jobs, dashboard, evil)
    finally:
        server.should_exit = True
        thread.join(15)
        for stub_server in (evil_server, jobs_server, dashboard_server):
            stub_server.shutdown()
            stub_server.server_close()


@dataclass
class Reply:
    status: int
    headers: dict[str, str]
    body: bytes
    raw_headers: list[tuple[str, str]]


def send_raw(port: int, payload: bytes, *, timeout: float = 8.0) -> Reply:
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as sock:
        sock.sendall(payload)
        data = b""
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            data += chunk
    head, _, body = data.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    status = int(lines[0].split(" ", 2)[1])
    headers = {}
    raw_headers = []
    for line in lines[1:]:
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()
        raw_headers.append((name.strip().lower(), value.strip()))
    return Reply(status, headers, body, raw_headers)


def get(port: int, target: str, *, extra: str = "", method: str = "GET") -> Reply:
    request = f"{method} {target} HTTP/1.1\r\nHost: gw\r\nConnection: close\r\n{extra}\r\n"
    return send_raw(port, request.encode("latin-1"))


def test_the_ssrf_payload_never_reaches_any_backend_over_a_real_connection(gateway) -> None:
    before = (len(gateway.jobs.hits), len(gateway.dashboard.hits), len(gateway.evil.hits))
    evil_authority = gateway.evil.base.removeprefix("http://")
    reply = get(gateway.port, f"/api/jobs@{evil_authority}/latest/meta-data")
    assert reply.status == 404
    assert (len(gateway.jobs.hits), len(gateway.dashboard.hits), len(gateway.evil.hits)) == before


def test_a_normal_proxied_request_reaches_the_backend_with_its_path_query_and_token(
    gateway,
) -> None:
    reply = get(gateway.port, "/api/jobs/v1/jobs?limit=5", extra="Authorization: Bearer tok\r\n")
    assert reply.status == 200
    assert json.loads(reply.body) == {"kind": "jobs", "path": "/v1/jobs?limit=5"}
    hit = gateway.jobs.hits[-1]
    assert hit["authorization"] == "Bearer tok"
    assert hit["x-forwarded-for"] == "127.0.0.1"


def test_the_dashboard_prefix_is_rewritten_for_real(gateway) -> None:
    reply = get(gateway.port, "/api/dashboard/economy?seed=1")
    assert json.loads(reply.body)["path"] == "/dashboard/economy?seed=1"


def test_security_headers_and_no_server_banner_on_a_real_response(gateway) -> None:
    reply = get(gateway.port, "/")
    assert reply.status == 200
    assert reply.headers["x-content-type-options"] == "nosniff"
    assert reply.headers["x-frame-options"] == "DENY"
    assert "default-src 'none'" in reply.headers["content-security-policy"]
    assert "x-gateway-request-id" in reply.headers
    assert "server" not in reply.headers, "uvicorn's banner must not be sent"
    assert "strict-transport-security" not in reply.headers


def test_a_backend_server_banner_is_not_relayed(gateway) -> None:
    reply = get(gateway.port, "/api/jobs/v1/jobs")
    assert "server" not in reply.headers


def test_a_proxied_response_carries_exactly_one_date_header(gateway) -> None:
    """Found by driving the real stack: the backend's Date was relayed on top of
    the gateway's own, so every proxied response had two."""
    reply = get(gateway.port, "/api/jobs/v1/jobs")
    assert [name for name, _ in reply.raw_headers].count("date") == 1


def test_an_encoded_slash_is_refused_by_the_real_servers_own_raw_path(gateway) -> None:
    before = len(gateway.jobs.hits)
    reply = get(gateway.port, "/api/jobs/v1/jobs/a%2Fb")
    assert reply.status == 400
    assert len(gateway.jobs.hits) == before


def test_an_encoded_question_mark_reaches_the_backend_still_encoded(gateway) -> None:
    get(gateway.port, "/api/jobs/v1/jobs/a%3Fb=1")
    assert gateway.jobs.hits[-1]["path"] == "/v1/jobs/a%3Fb=1"


@pytest.mark.parametrize(
    "target",
    ["/%00", "/api/jobs/%2e%2e/x", "/api/jobs/..%2fx", "http://evil.example/api/jobs", "/a%zz"],
)
def test_hostile_request_targets_are_400_over_a_real_connection(gateway, target) -> None:
    before = len(gateway.jobs.hits)
    assert get(gateway.port, target).status == 400
    assert len(gateway.jobs.hits) == before


def test_non_ascii_query_bytes_are_a_client_error_never_a_server_error(gateway) -> None:
    payload = b"GET /api/jobs/v1/jobs?q=\xc3\xa9 HTTP/1.1\r\nHost: gw\r\nConnection: close\r\n\r\n"
    assert send_raw(gateway.port, payload).status == 400


def test_a_backend_redirect_is_handed_to_the_client_never_followed(gateway) -> None:
    before = len(gateway.evil.hits)
    reply = get(gateway.port, "/api/jobs/redirect", extra="Authorization: Bearer tok\r\n")
    assert reply.status == 302
    assert reply.headers["location"] == f"{gateway.evil.base}/stolen"
    assert len(gateway.evil.hits) == before, "the gateway must never contact the redirect target"


def test_a_backend_relative_location_is_made_public(gateway) -> None:
    reply = get(gateway.port, "/api/jobs/created", method="POST", extra="Content-Length: 0\r\n")
    assert reply.status == 202
    assert reply.headers["location"] == "/api/jobs/v1/jobs/abc"


def test_head_has_headers_and_no_body_on_the_wire(gateway) -> None:
    reply = get(gateway.port, "/assets/app.js", method="HEAD")
    assert reply.status == 200
    assert reply.body == b""
    assert reply.headers["content-length"] == str(len("console.log(1)"))
    assert "immutable" in reply.headers["cache-control"]


def test_an_oversize_declared_body_is_413_before_any_backend_call(gateway) -> None:
    before = len(gateway.jobs.hits)
    reply = get(
        gateway.port,
        "/api/jobs/v1/jobs",
        method="POST",
        extra="Content-Length: 999999\r\nContent-Type: application/json\r\n",
    )
    assert reply.status == 413
    assert len(gateway.jobs.hits) == before


def test_a_post_body_within_budget_round_trips(gateway) -> None:
    body = b'{"kind":"qmacro"}'
    payload = (
        b"POST /api/jobs/v1/jobs HTTP/1.1\r\nHost: gw\r\nConnection: close\r\n"
        b"Content-Type: application/json\r\nContent-Length: "
        + str(len(body)).encode()
        + b"\r\n\r\n"
    ) + body
    assert send_raw(gateway.port, payload).status == 200


def test_a_slow_backend_does_not_stall_the_health_probe_on_the_real_server(gateway) -> None:
    results: dict[str, float] = {}

    def slow_call() -> None:
        started = time.monotonic()
        get(gateway.port, "/api/jobs/slow")
        results["slow"] = time.monotonic() - started

    thread = threading.Thread(target=slow_call)
    thread.start()
    time.sleep(0.3)  # let the slow request reach the backend
    started = time.monotonic()
    assert get(gateway.port, "/health/live").status == 200
    results["health"] = time.monotonic() - started
    thread.join(10)
    assert results["slow"] >= 1.0
    assert results["health"] < 0.5, f"health probe stalled behind a slow backend: {results}"


def test_an_unreachable_backend_is_a_502_that_names_nothing_internal(tmp_path_factory) -> None:
    dist = tmp_path_factory.mktemp("dist502")
    (dist / "index.html").write_text("<title>x</title>")
    dead = socket.socket()
    dead.bind(("127.0.0.1", 0))
    dead_port = dead.getsockname()[1]
    dead.close()  # nothing listens here now
    app = WebGatewayService(
        dist,
        f"http://127.0.0.1:{dead_port}",
        f"http://127.0.0.1:{dead_port}",
        config=GatewayConfig(rate_limit_per_second=0),
    )
    options = uvicorn_options(
        host="127.0.0.1", port=0, tls_cert=None, tls_key=None, max_connections=8
    )
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", **options))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.02)
    try:
        port = server.servers[0].sockets[0].getsockname()[1]
        reply = get(port, "/api/jobs/v1/jobs")
        assert reply.status == 502
        assert str(dead_port).encode() not in reply.body and b"127.0.0.1" not in reply.body
        assert reply.headers["x-content-type-options"] == "nosniff"
    finally:
        server.should_exit = True
        thread.join(15)
