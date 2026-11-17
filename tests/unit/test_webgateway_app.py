from __future__ import annotations

import asyncio

import pytest

from prometheus.webgateway.app import WebGatewayService
from prometheus.webgateway.proxy import UpstreamResponse, UpstreamUnavailableError


class _FakeTransport:
    def __init__(self, response=None, error=None):
        self._response = response or UpstreamResponse(
            200, (("content-type", "application/json"),), b"{}"
        )
        self._error = error
        self.calls = []

    def request(self, method, url, headers, body, *, timeout):
        self.calls.append(
            {"method": method, "url": url, "headers": headers, "body": body, "timeout": timeout}
        )
        if self._error is not None:
            raise self._error
        return self._response


@pytest.fixture
def dist_root(tmp_path):
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<html>spa shell</html>")
    (root / "assets" / "app.js").write_bytes(b"console.log('hi');")
    return root


async def _request_async(app, method, path, *, query="", headers=(), body=b""):
    sent = []
    body_sent = {"done": False}

    async def receive():
        if body_sent["done"]:
            return {"type": "http.request", "body": b"", "more_body": False}
        body_sent["done"] = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "query_string": query.encode("ascii"),
        "headers": [(k.encode("ascii"), v.encode("latin-1")) for k, v in headers],
    }
    await app(scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    response_body = b"".join(m["body"] for m in sent if m["type"] == "http.response.body")
    response_headers = {k.decode("ascii"): v.decode("latin-1") for k, v in start["headers"]}
    return start["status"], response_body, response_headers


def request(app, method, path, **kwargs):
    return asyncio.run(_request_async(app, method, path, **kwargs))


def test_health_endpoint_is_public(dist_root) -> None:
    app = WebGatewayService(dist_root, "http://127.0.0.1:8765", "http://127.0.0.1:8766")
    status, body, _ = request(app, "GET", "/health/live")
    assert status == 200
    assert body == b"live"


def test_serves_a_real_static_file_from_the_dist_root(dist_root) -> None:
    app = WebGatewayService(dist_root, "http://127.0.0.1:8765", "http://127.0.0.1:8766")
    status, body, headers = request(app, "GET", "/assets/app.js")
    assert status == 200
    assert body == b"console.log('hi');"
    assert "javascript" in headers["content-type"]


def test_unmatched_path_falls_back_to_the_spa_shell(dist_root) -> None:
    app = WebGatewayService(dist_root, "http://127.0.0.1:8765", "http://127.0.0.1:8766")
    status, body, _ = request(app, "GET", "/lab/pde-solver")
    assert status == 200
    assert body == b"<html>spa shell</html>"


def test_api_jobs_strips_the_prefix_exactly_like_vites_dev_proxy(dist_root) -> None:
    fake = _FakeTransport()
    app = WebGatewayService(dist_root, "http://127.0.0.1:8765", "http://127.0.0.1:8766", fake)
    request(app, "GET", "/api/jobs/v1/jobs/abc123")
    assert fake.calls[0]["url"] == "http://127.0.0.1:8765/v1/jobs/abc123"


def test_api_dashboard_rewrites_the_prefix_exactly_like_vites_dev_proxy(dist_root) -> None:
    fake = _FakeTransport()
    app = WebGatewayService(dist_root, "http://127.0.0.1:8765", "http://127.0.0.1:8766", fake)
    request(app, "GET", "/api/dashboard/experiments")
    assert fake.calls[0]["url"] == "http://127.0.0.1:8766/dashboard/experiments"


def test_query_string_is_preserved_through_the_proxy(dist_root) -> None:
    fake = _FakeTransport()
    app = WebGatewayService(dist_root, "http://127.0.0.1:8765", "http://127.0.0.1:8766", fake)
    request(app, "GET", "/api/dashboard/economy", query="n_steps=3&seed=1")
    assert fake.calls[0]["url"] == "http://127.0.0.1:8766/dashboard/economy?n_steps=3&seed=1"


def test_authorization_header_is_forwarded_unchanged(dist_root) -> None:
    fake = _FakeTransport()
    app = WebGatewayService(dist_root, "http://127.0.0.1:8765", "http://127.0.0.1:8766", fake)
    request(app, "GET", "/api/jobs/v1/jobs", headers=[("authorization", "Bearer secret-token")])
    forwarded = dict(fake.calls[0]["headers"])
    assert forwarded["authorization"] == "Bearer secret-token"


def test_host_and_content_length_are_not_forwarded_to_the_upstream(dist_root) -> None:
    fake = _FakeTransport()
    app = WebGatewayService(dist_root, "http://127.0.0.1:8765", "http://127.0.0.1:8766", fake)
    request(
        app,
        "GET",
        "/api/jobs/v1/jobs",
        headers=[("host", "localhost"), ("content-length", "0")],
    )
    forwarded_names = {name for name, _ in fake.calls[0]["headers"]}
    assert "host" not in forwarded_names
    assert "content-length" not in forwarded_names


def test_post_body_is_forwarded_to_the_jobs_api_unchanged(dist_root) -> None:
    fake = _FakeTransport()
    app = WebGatewayService(dist_root, "http://127.0.0.1:8765", "http://127.0.0.1:8766", fake)
    request(app, "POST", "/api/jobs/v1/jobs", body=b'{"kind":"qmacro"}')
    assert fake.calls[0]["method"] == "POST"
    assert fake.calls[0]["body"] == b'{"kind":"qmacro"}'


def test_upstreams_own_response_is_relayed_through_unchanged(dist_root) -> None:
    fake = _FakeTransport(
        response=UpstreamResponse(
            404, (("content-type", "application/json"),), b'{"error":"not found"}'
        )
    )
    app = WebGatewayService(dist_root, "http://127.0.0.1:8765", "http://127.0.0.1:8766", fake)
    status, body, _ = request(app, "GET", "/api/jobs/v1/jobs/missing")
    assert status == 404
    assert body == b'{"error":"not found"}'


def test_an_unreachable_upstream_maps_to_502_not_a_raw_exception(dist_root) -> None:
    fake = _FakeTransport(
        error=UpstreamUnavailableError("upstream unavailable: connection refused")
    )
    app = WebGatewayService(dist_root, "http://127.0.0.1:8765", "http://127.0.0.1:8766", fake)
    status, body, _ = request(app, "GET", "/api/jobs/v1/jobs")
    assert status == 502
    assert b"unavailable" in body


def test_lifespan_startup_and_shutdown_are_acknowledged(dist_root) -> None:
    app = WebGatewayService(dist_root, "http://127.0.0.1:8765", "http://127.0.0.1:8766")
    sent = []
    messages = iter([{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}])

    async def receive():
        return next(messages)

    async def send(message):
        sent.append(message)

    asyncio.run(app({"type": "lifespan"}, receive, send))
    assert [m["type"] for m in sent] == [
        "lifespan.startup.complete",
        "lifespan.shutdown.complete",
    ]
