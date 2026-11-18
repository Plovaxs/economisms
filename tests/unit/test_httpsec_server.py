"""Every process this project ships runs under the SAME hardened uvicorn
configuration; these tests pin that for the shared function AND for each of
the three entry points that must actually use it."""

from __future__ import annotations

from pathlib import Path

import pytest

from prometheus.dashboard.__main__ import main as dashboard_main
from prometheus.httpsec.server import uvicorn_options
from prometheus.service.__main__ import main as service_main
from prometheus.webgateway.__main__ import main as gateway_main


def test_the_shared_options_are_hardened() -> None:
    options = uvicorn_options(
        host="127.0.0.1", port=9, tls_cert=None, tls_key=None, max_connections=7
    )
    assert options["server_header"] is False
    assert options["proxy_headers"] is False
    assert options["access_log"] is False
    assert options["ws"] == "none"
    assert options["workers"] == 1
    assert options["interface"] == "asgi3" and options["lifespan"] == "on"
    assert options["limit_concurrency"] == 7
    assert options["timeout_keep_alive"] == 5
    assert options["h11_max_incomplete_event_size"] == 16384
    assert options["ssl_certfile"] is None and options["ssl_keyfile"] is None


def test_tls_paths_become_strings() -> None:
    options = uvicorn_options(
        host="0.0.0.0",
        port=443,
        tls_cert=Path("/c.pem"),
        tls_key=Path("/k.pem"),
        max_connections=1,
    )
    assert options["ssl_certfile"] == "/c.pem" and options["ssl_keyfile"] == "/k.pem"


@pytest.fixture
def captured(monkeypatch):
    calls = []
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: calls.append((app, kwargs)))
    return calls


def test_the_dashboard_entry_point_uses_the_shared_options(tmp_path, captured) -> None:
    creds = tmp_path / "auth.json"
    token = tmp_path / "token"
    init = [
        "init-auth",
        "--credentials",
        str(creds),
        "--token-file",
        str(token),
        "--owner",
        "alice",
    ]
    assert dashboard_main(init) == 0
    assert dashboard_main(["serve", "--credentials", str(creds), "--port", "0", "--demo"]) == 0
    _, kwargs = captured[0]
    assert kwargs["server_header"] is False and kwargs["limit_concurrency"] == 32
    assert kwargs["proxy_headers"] is False and kwargs["ws"] == "none"


def test_the_job_api_entry_point_uses_the_shared_options(tmp_path, captured) -> None:
    creds = tmp_path / "auth.json"
    assert (
        service_main(
            [
                "init-auth",
                "--credentials",
                str(creds),
                "--token-file",
                str(tmp_path / "t"),
                "--owner",
                "alice",
            ]
        )
        == 0
    )
    assert (
        service_main(
            ["serve", "--root", str(tmp_path / "root"), "--credentials", str(creds), "--port", "0"]
        )
        == 0
    )
    _, kwargs = captured[0]
    assert kwargs["server_header"] is False and kwargs["limit_concurrency"] == 32
    assert kwargs["proxy_headers"] is False and kwargs["ws"] == "none"


def test_the_gateway_entry_point_uses_the_shared_options(tmp_path, captured) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<title>x</title>")
    assert gateway_main(["serve", "--dist", str(dist), "--port", "0"]) == 0
    _, kwargs = captured[0]
    assert kwargs["server_header"] is False and kwargs["limit_concurrency"] == 128
