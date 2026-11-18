from __future__ import annotations

import asyncio
import json
import logging
import threading
from dataclasses import dataclass, field
from typing import Any

import pytest

from prometheus.webgateway.app import GatewayConfig, WebGatewayService
from prometheus.webgateway.headers import API_CSP, SPA_CSP
from prometheus.webgateway.proxy import (
    UpstreamRequestError,
    UpstreamResponse,
    UpstreamResponseTooLargeError,
    UpstreamUnavailableError,
)

JOBS = "http://127.0.0.1:8765"
DASHBOARD = "http://127.0.0.1:8766"


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


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@dataclass
class Resp:
    status: int
    body: bytes
    headers: dict[str, str]
    raw_headers: list[tuple[str, str]] = field(default_factory=list)

    def json(self) -> Any:
        return json.loads(self.body)


@pytest.fixture
def dist_root(tmp_path):
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<html>spa shell</html>")
    (root / "assets" / "app.js").write_bytes(b"console.log('hi');")
    return root


def make_app(dist_root, transport=None, **config):
    return WebGatewayService(
        dist_root,
        JOBS,
        DASHBOARD,
        transport or _FakeTransport(),
        config=GatewayConfig(**config) if config else GatewayConfig(rate_limit_per_second=0),
    )


async def request_async(
    app,
    method,
    path,
    *,
    query=b"",
    headers=(),
    body=b"",
    chunks=None,
    client=("203.0.113.7", 5555),
    scheme="http",
    raw_path=None,
) -> Resp | None:
    sent: list[dict[str, Any]] = []
    pending = list(chunks) if chunks is not None else [body]

    async def receive():
        if pending:
            chunk = pending.pop(0)
            return {"type": "http.request", "body": chunk, "more_body": bool(pending)}
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "query_string": query if isinstance(query, bytes) else query.encode("ascii"),
        "headers": [(k.encode("latin-1"), v.encode("latin-1")) for k, v in headers],
        "client": client,
        "scheme": scheme,
    }
    if raw_path is not None:
        scope["raw_path"] = raw_path
    await app(scope, receive, send)
    start = next((m for m in sent if m["type"] == "http.response.start"), None)
    if start is None:
        return None
    response_body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    raw = [(k.decode("latin-1"), v.decode("latin-1")) for k, v in start["headers"]]
    return Resp(start["status"], response_body, {k: v for k, v in raw}, raw)


def request(app, method, path, **kwargs) -> Resp:
    result = asyncio.run(request_async(app, method, path, **kwargs))
    assert result is not None
    return result


# --- the behaviours the first gateway already had, unchanged ------------------------


def test_health_endpoint_is_public(dist_root) -> None:
    resp = request(make_app(dist_root), "GET", "/health/live")
    assert (resp.status, resp.body) == (200, b"live")


def test_serves_a_real_static_file_from_the_dist_root(dist_root) -> None:
    resp = request(make_app(dist_root), "GET", "/assets/app.js")
    assert resp.status == 200
    assert resp.body == b"console.log('hi');"
    assert "javascript" in resp.headers["content-type"]


def test_unmatched_path_falls_back_to_the_spa_shell(dist_root) -> None:
    resp = request(make_app(dist_root), "GET", "/lab/pde-solver")
    assert (resp.status, resp.body) == (200, b"<html>spa shell</html>")


def test_a_missing_asset_is_a_404_not_the_html_shell(dist_root) -> None:
    resp = request(make_app(dist_root), "GET", "/assets/missing.js")
    assert resp.status == 404
    assert b"spa shell" not in resp.body


def test_api_jobs_strips_the_prefix_exactly_like_vites_dev_proxy(dist_root) -> None:
    fake = _FakeTransport()
    request(make_app(dist_root, fake), "GET", "/api/jobs/v1/jobs/abc123")
    assert fake.calls[0]["url"] == f"{JOBS}/v1/jobs/abc123"


def test_api_dashboard_rewrites_the_prefix_exactly_like_vites_dev_proxy(dist_root) -> None:
    fake = _FakeTransport()
    request(make_app(dist_root, fake), "GET", "/api/dashboard/experiments")
    assert fake.calls[0]["url"] == f"{DASHBOARD}/dashboard/experiments"


def test_query_string_is_preserved_through_the_proxy(dist_root) -> None:
    fake = _FakeTransport()
    request(make_app(dist_root, fake), "GET", "/api/dashboard/economy", query=b"n_steps=3&seed=1")
    assert fake.calls[0]["url"] == f"{DASHBOARD}/dashboard/economy?n_steps=3&seed=1"


def test_authorization_header_is_forwarded_unchanged(dist_root) -> None:
    fake = _FakeTransport()
    request(
        make_app(dist_root, fake),
        "GET",
        "/api/jobs/v1/jobs",
        headers=[("authorization", "Bearer secret-token")],
    )
    assert dict(fake.calls[0]["headers"])["authorization"] == "Bearer secret-token"


def test_host_and_content_length_are_not_forwarded_to_the_upstream(dist_root) -> None:
    fake = _FakeTransport()
    request(
        make_app(dist_root, fake),
        "GET",
        "/api/jobs/v1/jobs",
        headers=[("host", "localhost"), ("content-length", "0")],
    )
    names = {name for name, _ in fake.calls[0]["headers"]}
    assert "host" not in names and "content-length" not in names


def test_post_body_is_forwarded_to_the_jobs_api_unchanged(dist_root) -> None:
    fake = _FakeTransport()
    request(make_app(dist_root, fake), "POST", "/api/jobs/v1/jobs", body=b'{"kind":"qmacro"}')
    assert fake.calls[0]["method"] == "POST"
    assert fake.calls[0]["body"] == b'{"kind":"qmacro"}'


def test_upstreams_own_response_is_relayed_through_unchanged(dist_root) -> None:
    fake = _FakeTransport(
        response=UpstreamResponse(404, (("content-type", "application/json"),), b'{"e":"nf"}')
    )
    resp = request(make_app(dist_root, fake), "GET", "/api/jobs/v1/jobs/missing")
    assert (resp.status, resp.body) == (404, b'{"e":"nf"}')


def test_an_unreachable_upstream_maps_to_502_not_a_raw_exception(dist_root) -> None:
    fake = _FakeTransport(error=UpstreamUnavailableError("upstream unavailable"))
    resp = request(make_app(dist_root, fake), "GET", "/api/jobs/v1/jobs")
    assert resp.status == 502
    assert b"unavailable" in resp.body


def test_lifespan_startup_and_shutdown_are_acknowledged(dist_root) -> None:
    app = make_app(dist_root)
    sent = []
    messages = iter([{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}])

    async def receive():
        return next(messages)

    async def send(message):
        sent.append(message)

    asyncio.run(app({"type": "lifespan"}, receive, send))
    assert [m["type"] for m in sent] == ["lifespan.startup.complete", "lifespan.shutdown.complete"]


def test_websocket_connections_are_refused_not_crashed(dist_root) -> None:
    app = make_app(dist_root)
    sent = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "websocket.connect"}

    asyncio.run(app({"type": "websocket"}, receive, send))
    assert sent == [{"type": "websocket.close", "code": 1008}]


# --- request-target attacks: every one a confirmed bug in the first gateway ----------


@pytest.mark.parametrize(
    "path",
    [
        "/api/jobs@evil.example/latest/meta-data",
        "/api/jobs@169.254.169.254/",
        "/api/jobs:80@evil.example/",
        "/api/jobsX/v1",
        "/api/jobs-admin",
        "/api/nope",
        "/api/",
    ],
)
def test_ssrf_and_prefix_confusion_payloads_never_reach_the_transport(dist_root, path) -> None:
    fake = _FakeTransport()
    resp = request(make_app(dist_root, fake), "GET", path)
    assert resp.status == 404
    assert fake.calls == []
    assert resp.headers["content-type"] == "application/json"


@pytest.mark.parametrize(
    "path",
    [
        "/api/jobs/../../admin",
        "/api/jobs/%2e%2e/admin",
        "/api/jobs/./x",
        "/api/jobs/a%2Fb",
        "/api/jobs\\evil",
        "/api/jobs/%00",
        "/api/jobs//x",
        "/api/jobs/%zz",
        "/%00",
        "/assets/%2e%2e/%2e%2e/etc/passwd",
        "/x" * 1500,
    ],
)
def test_malformed_and_traversing_targets_are_400_and_never_proxied(dist_root, path) -> None:
    fake = _FakeTransport()
    app = make_app(dist_root, fake)
    # A real server hands the app BOTH the decoded `path` and the exact `raw_path`.
    from urllib.parse import quote

    raw = path if path.isascii() and "\x00" not in path else quote(path, safe="/%")
    resp = request(app, "GET", path, raw_path=raw.encode("ascii", "replace"))
    assert resp.status == 400
    assert fake.calls == []
    assert resp.json()["error"]["code"] == "invalid_request_target"


def test_a_host_suffix_payload_cannot_change_a_portless_upstream_hostname(dist_root) -> None:
    """Confirmed against the old gateway over a real socket: with
    `--jobs-url http://jobs-api`, `/api/jobs.attacker.example/x` made it
    resolve and dial `jobs-api.attacker.example`."""
    fake = _FakeTransport()
    app = WebGatewayService(
        dist_root, "http://jobs-api", DASHBOARD, fake, config=GatewayConfig(rate_limit_per_second=0)
    )
    resp = request(app, "GET", "/api/jobs.attacker.example/x")
    assert resp.status == 404
    assert fake.calls == []
    request(app, "GET", "/api/jobs/v1/jobs")
    assert fake.calls[0]["url"] == "http://jobs-api/v1/jobs"


def test_a_percent_encoded_question_mark_stays_in_the_path_instead_of_becoming_a_query(
    dist_root,
) -> None:
    fake = _FakeTransport()
    request(
        make_app(dist_root, fake),
        "GET",
        "/api/jobs/v1/jobs/a?injected=1",
        raw_path=b"/api/jobs/v1/jobs/a%3Finjected=1",
    )
    assert fake.calls[0]["url"] == f"{JOBS}/v1/jobs/a%3Finjected=1"
    assert "?" not in fake.calls[0]["url"]


def test_without_raw_path_a_decoded_question_mark_is_re_encoded(dist_root) -> None:
    fake = _FakeTransport()
    request(make_app(dist_root, fake), "GET", "/api/jobs/v1/jobs/a?injected=1")
    assert fake.calls[0]["url"] == f"{JOBS}/v1/jobs/a%3Finjected%3D1"


@pytest.mark.parametrize("query", [b"q=\xc3\xa9", b"a b", b"a#b", b"a=%zz", b"a=<b>", b"x" * 3000])
def test_a_malformed_query_is_400_not_an_unhandled_exception(dist_root, query) -> None:
    fake = _FakeTransport()
    resp = request(make_app(dist_root, fake), "GET", "/api/jobs/v1/jobs", query=query)
    assert resp.status == 400
    assert fake.calls == []


def test_the_upstream_authority_is_asserted_even_if_routing_were_bypassed(
    dist_root, monkeypatch, caplog
) -> None:
    fake = _FakeTransport()
    app = make_app(dist_root, fake)
    from prometheus.webgateway import app as app_module
    from prometheus.webgateway.routing import Route, RouteKind

    monkeypatch.setattr(
        app_module, "match_route", lambda raw: Route(RouteKind.JOBS, "@evil.example/x")
    )
    with caplog.at_level(logging.ERROR, logger="prometheus.webgateway"):
        resp = request(app, "GET", "/api/jobs/anything")
    assert resp.status == 500
    assert fake.calls == []
    assert "authority differs" in caplog.text


# --- methods ------------------------------------------------------------------------


def test_head_on_a_static_file_returns_headers_and_no_body(dist_root) -> None:
    resp = request(make_app(dist_root), "HEAD", "/assets/app.js")
    assert resp.status == 200
    assert resp.body == b""
    assert resp.headers["content-length"] == str(len(b"console.log('hi');"))


def test_head_on_the_health_endpoint(dist_root) -> None:
    resp = request(make_app(dist_root), "HEAD", "/health/live")
    assert (resp.status, resp.body) == (200, b"")


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH", "OPTIONS", "TRACE"])
def test_static_files_and_health_only_accept_get_and_head(dist_root, method) -> None:
    for path in ("/assets/app.js", "/health/live", "/"):
        resp = request(make_app(dist_root), method, path)
        assert resp.status == 405
        assert resp.headers["allow"] == "GET, HEAD"


@pytest.mark.parametrize("method", ["TRACE", "CONNECT", "PROPFIND"])
def test_unsupported_methods_are_refused_before_the_proxy(dist_root, method) -> None:
    fake = _FakeTransport()
    resp = request(make_app(dist_root, fake), method, "/api/jobs/v1/jobs")
    assert resp.status == 405
    assert "GET" in resp.headers["allow"] and "TRACE" not in resp.headers["allow"]
    assert fake.calls == []


# --- bounded bodies -----------------------------------------------------------------


def test_a_declared_oversize_body_is_413_without_calling_the_backend(dist_root) -> None:
    fake = _FakeTransport()
    app = make_app(dist_root, fake, max_request_body_bytes=100)
    resp = request(
        app,
        "POST",
        "/api/jobs/v1/jobs",
        headers=[("content-length", "101")],
        body=b"x" * 101,
    )
    assert resp.status == 413
    assert fake.calls == []


def test_an_undeclared_streamed_oversize_body_is_cut_off_at_the_budget(dist_root) -> None:
    fake = _FakeTransport()
    app = make_app(dist_root, fake, max_request_body_bytes=100)
    resp = request(app, "POST", "/api/jobs/v1/jobs", chunks=[b"x" * 60, b"x" * 60])
    assert resp.status == 413
    assert fake.calls == []


def test_a_body_exactly_at_the_budget_is_forwarded(dist_root) -> None:
    fake = _FakeTransport()
    app = make_app(dist_root, fake, max_request_body_bytes=100)
    resp = request(app, "POST", "/api/jobs/v1/jobs", chunks=[b"x" * 60, b"x" * 40])
    assert resp.status == 200
    assert len(fake.calls[0]["body"]) == 100


def test_a_client_that_disconnects_mid_body_gets_no_response_and_no_backend_call(
    dist_root,
) -> None:
    fake = _FakeTransport()
    app = make_app(dist_root, fake)
    sent: list[dict[str, Any]] = []
    messages = iter([{"type": "http.request", "body": b"par", "more_body": True}])

    async def receive():
        try:
            return next(messages)
        except StopIteration:
            return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/jobs/v1/jobs",
        "query_string": b"",
        "headers": [],
        "client": ("203.0.113.7", 1),
    }
    asyncio.run(app(scope, receive, send))
    assert sent == [] and fake.calls == []


def test_a_body_that_never_finishes_arriving_is_408(dist_root) -> None:
    fake = _FakeTransport()
    app = make_app(dist_root, fake, body_timeout_seconds=0.05, rate_limit_per_second=0)
    sent: list[dict[str, Any]] = []

    async def receive():
        await asyncio.sleep(5)
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/jobs/v1/jobs",
        "query_string": b"",
        "headers": [],
        "client": ("203.0.113.7", 1),
    }
    asyncio.run(app(scope, receive, send))
    assert sent[0]["status"] == 408
    assert fake.calls == []


# --- failures never leak detail -----------------------------------------------------


def test_an_unexpected_exception_is_a_generic_500_and_is_logged_server_side(
    dist_root, caplog
) -> None:
    fake = _FakeTransport(error=RuntimeError("secret internal detail: /srv/data/creds.json"))
    with caplog.at_level(logging.ERROR, logger="prometheus.webgateway"):
        resp = request(make_app(dist_root, fake), "GET", "/api/jobs/v1/jobs")
    assert resp.status == 500
    assert b"secret" not in resp.body and b"creds" not in resp.body
    assert resp.json()["error"]["code"] == "internal_error"
    assert "secret internal detail" in caplog.text  # ...but it IS in the server log
    assert resp.headers["x-content-type-options"] == "nosniff"  # even error pages are hardened


def test_an_oversized_upstream_response_is_a_502_with_its_own_code(dist_root) -> None:
    fake = _FakeTransport(error=UpstreamResponseTooLargeError("upstream response is too large"))
    resp = request(make_app(dist_root, fake), "GET", "/api/jobs/v1/jobs")
    assert resp.status == 502
    assert resp.json()["error"]["code"] == "upstream_response_too_large"


def test_a_request_the_transport_rejects_is_a_400_not_a_502(dist_root) -> None:
    fake = _FakeTransport(error=UpstreamRequestError("request cannot be forwarded"))
    resp = request(make_app(dist_root, fake), "GET", "/api/jobs/v1/jobs")
    assert resp.status == 400


def test_the_502_body_never_names_the_internal_upstream_address(dist_root) -> None:
    fake = _FakeTransport(error=UpstreamUnavailableError("upstream unavailable"))
    resp = request(make_app(dist_root, fake), "GET", "/api/jobs/v1/jobs")
    assert b"127.0.0.1" not in resp.body and b"8765" not in resp.body


# --- security and cache headers on EVERY response -----------------------------------

_ALWAYS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "cross-origin-opener-policy": "same-origin",
    "cross-origin-resource-policy": "same-origin",
    "x-permitted-cross-domain-policies": "none",
}


def _scenarios(dist_root):
    ok = _FakeTransport()
    down = _FakeTransport(error=UpstreamUnavailableError("upstream unavailable"))
    boom = _FakeTransport(error=RuntimeError("boom"))
    return {
        "static": (make_app(dist_root), "GET", "/assets/app.js", {}),
        "spa": (make_app(dist_root), "GET", "/lab/x", {}),
        "static-404": (make_app(dist_root), "GET", "/assets/none.js", {}),
        "health": (make_app(dist_root), "GET", "/health/live", {}),
        "proxied": (make_app(dist_root, ok), "GET", "/api/jobs/v1/jobs", {}),
        "api-404": (make_app(dist_root), "GET", "/api/zzz", {}),
        "400": (make_app(dist_root), "GET", "/api/jobs/../x", {"raw_path": b"/api/jobs/../x"}),
        "405": (make_app(dist_root), "POST", "/", {}),
        "413": (
            make_app(dist_root, max_request_body_bytes=1, rate_limit_per_second=0),
            "POST",
            "/api/jobs/v1/jobs",
            {"body": b"xx"},
        ),
        "502": (make_app(dist_root, down), "GET", "/api/jobs/v1/jobs", {}),
        "500": (make_app(dist_root, boom), "GET", "/api/jobs/v1/jobs", {}),
        "429": (
            make_app(dist_root, rate_limit_per_second=1, rate_limit_burst=1),
            "GET",
            "/lab/y",
            {"_twice": True},
        ),
    }


@pytest.mark.parametrize(
    "name",
    [
        "static",
        "spa",
        "static-404",
        "health",
        "proxied",
        "api-404",
        "400",
        "405",
        "413",
        "502",
        "500",
        "429",
    ],
)
def test_every_kind_of_response_carries_the_enforced_security_headers(dist_root, name) -> None:
    app, method, path, extra = _scenarios(dist_root)[name]
    extra = dict(extra)
    if extra.pop("_twice", False):
        request(app, method, path, **extra)
    resp = request(app, method, path, **extra)
    for header, value in _ALWAYS.items():
        assert resp.headers[header] == value, (name, header)
    assert "camera=()" in resp.headers["permissions-policy"]
    assert "content-security-policy" in resp.headers
    assert "x-gateway-request-id" in resp.headers
    assert "strict-transport-security" not in resp.headers  # cleartext: never claimed


def test_the_html_shell_gets_the_spa_csp_and_everything_else_the_api_csp(dist_root) -> None:
    app = make_app(dist_root)
    assert request(app, "GET", "/").headers["content-security-policy"] == SPA_CSP
    assert request(app, "GET", "/assets/app.js").headers["content-security-policy"] == API_CSP
    assert request(app, "GET", "/api/zzz").headers["content-security-policy"] == API_CSP


def test_the_spa_csp_is_strict_with_no_third_party_origin_and_no_unsafe_directive() -> None:
    assert "http" not in SPA_CSP and "unsafe" not in SPA_CSP and "*" not in SPA_CSP
    for directive in ("default-src 'none'", "script-src 'self'", "frame-ancestors 'none'"):
        assert directive in SPA_CSP
    assert "object-src 'none'" in SPA_CSP and "base-uri 'none'" in SPA_CSP


def test_hsts_and_upgrade_insecure_requests_are_only_sent_over_https(dist_root) -> None:
    app = make_app(dist_root)
    https = request(app, "GET", "/", scheme="https")
    assert "max-age=" in https.headers["strict-transport-security"]
    assert https.headers["content-security-policy"].endswith("upgrade-insecure-requests")
    plain = request(app, "GET", "/", scheme="http")
    assert "strict-transport-security" not in plain.headers
    assert "upgrade-insecure-requests" not in plain.headers["content-security-policy"]


def test_an_upstream_cannot_weaken_the_enforced_headers_or_leak_its_banner(dist_root) -> None:
    fake = _FakeTransport(
        response=UpstreamResponse(
            200,
            (
                ("content-type", "application/json"),
                ("x-frame-options", "ALLOWALL"),
                ("x-content-type-options", "sniff"),
                ("server", "uvicorn"),
                ("x-powered-by", "secret-framework"),
                ("strict-transport-security", "max-age=0"),
            ),
            b"{}",
        )
    )
    resp = request(make_app(dist_root, fake), "GET", "/api/jobs/v1/jobs")
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert "server" not in resp.headers and "x-powered-by" not in resp.headers
    assert "strict-transport-security" not in resp.headers
    assert [k for k, _ in resp.raw_headers].count("x-frame-options") == 1


def test_an_upstream_that_chose_its_own_csp_keeps_it(dist_root) -> None:
    fake = _FakeTransport(
        response=UpstreamResponse(200, (("content-security-policy", "default-src 'self'"),), b"")
    )
    resp = request(make_app(dist_root, fake), "GET", "/api/dashboard/x")
    assert resp.headers["content-security-policy"] == "default-src 'self'"


def test_hashed_assets_are_cached_forever_and_the_shell_is_always_revalidated(dist_root) -> None:
    app = make_app(dist_root)
    assert "immutable" in request(app, "GET", "/assets/app.js").headers["cache-control"]
    assert request(app, "GET", "/").headers["cache-control"] == "no-cache"
    assert request(app, "GET", "/lab/x").headers["cache-control"] == "no-cache"
    assert request(app, "GET", "/index.html").headers["cache-control"] == "no-cache"


def test_proxied_api_responses_are_not_cacheable_unless_the_upstream_says_so(dist_root) -> None:
    assert (
        request(make_app(dist_root), "GET", "/api/jobs/v1/jobs").headers["cache-control"]
        == "no-store"
    )
    fake = _FakeTransport(
        response=UpstreamResponse(200, (("cache-control", "private, max-age=5"),), b"{}")
    )
    resp = request(make_app(dist_root, fake), "GET", "/api/jobs/v1/jobs")
    assert resp.headers["cache-control"] == "private, max-age=5"


# --- header forwarding ---------------------------------------------------------------


def test_hop_by_hop_and_connection_named_headers_are_not_forwarded(dist_root) -> None:
    fake = _FakeTransport()
    request(
        make_app(dist_root, fake),
        "POST",
        "/api/jobs/v1/jobs",
        headers=[
            ("connection", "keep-alive, X-Custom-Hop"),
            ("keep-alive", "timeout=5"),
            ("te", "trailers"),
            ("upgrade", "websocket"),
            ("proxy-authorization", "Basic abc"),
            ("transfer-encoding", "chunked"),
            ("x-custom-hop", "named in Connection"),
            ("expect", "100-continue"),
            ("authorization", "Bearer t"),
            ("idempotency-key", "k1"),
        ],
        body=b"{}",
    )
    names = {name for name, _ in fake.calls[0]["headers"]}
    for dropped in (
        "connection", "keep-alive", "te", "upgrade", "proxy-authorization",
        "transfer-encoding", "x-custom-hop", "expect",
    ):  # fmt: skip
        assert dropped not in names, dropped
    assert {"authorization", "idempotency-key"} <= names


def test_client_supplied_forwarding_headers_are_replaced_not_trusted(dist_root) -> None:
    fake = _FakeTransport()
    request(
        make_app(dist_root, fake),
        "GET",
        "/api/jobs/v1/jobs",
        headers=[
            ("x-forwarded-for", "10.0.0.99"),
            ("x-forwarded-proto", "https"),
            ("x-real-ip", "10.0.0.99"),
            ("forwarded", "for=10.0.0.99"),
            ("x-request-id", "client-chosen"),
        ],
        client=("203.0.113.7", 1),
    )
    forwarded = fake.calls[0]["headers"]
    values = {name: value for name, value in forwarded}
    assert values["x-forwarded-for"] == "203.0.113.7"
    assert values["x-forwarded-proto"] == "http"
    assert "x-real-ip" not in values and "forwarded" not in values
    assert values["x-request-id"] != "client-chosen"
    assert [n for n, _ in forwarded].count("x-forwarded-for") == 1


def test_malformed_request_headers_are_400(dist_root) -> None:
    fake = _FakeTransport()
    app = make_app(dist_root, fake)
    for bad in ([("bad name", "v")], [("x-a", "line\x00nul")], [("x-a", "a\x7fb")]):
        assert request(app, "GET", "/api/jobs/v1/jobs", headers=bad).status == 400
    many = [(f"x-h{i}", "v") for i in range(70)]
    assert request(app, "GET", "/api/jobs/v1/jobs", headers=many).status == 400
    big = [("x-big", "v" * 17000)]
    assert request(app, "GET", "/api/jobs/v1/jobs", headers=big).status == 400
    assert fake.calls == []


def test_upstream_hop_by_hop_headers_are_dropped_and_length_is_recomputed(dist_root) -> None:
    fake = _FakeTransport(
        response=UpstreamResponse(
            200,
            (
                ("connection", "close"),
                ("transfer-encoding", "chunked"),
                ("keep-alive", "timeout=5"),
                ("content-length", "9999"),
                ("date", "Wed, 18 Nov 2026 19:10:56 GMT"),
                ("set-cookie", "a=1"),
                ("set-cookie", "b=2"),
                ("etag", '"abc"'),
            ),
            b"hello",
        )
    )
    resp = request(make_app(dist_root, fake), "GET", "/api/jobs/v1/jobs/x/artifact")
    assert resp.headers["content-length"] == "5"
    assert [v for k, v in resp.raw_headers if k == "set-cookie"] == ["a=1", "b=2"]
    assert resp.headers["etag"] == '"abc"'
    for dropped in ("connection", "transfer-encoding", "keep-alive", "date"):
        assert dropped not in resp.headers


def test_a_relative_location_from_the_backend_is_rewritten_into_the_public_namespace(
    dist_root,
) -> None:
    fake = _FakeTransport(response=UpstreamResponse(202, (("location", "/v1/jobs/abc"),), b"{}"))
    resp = request(make_app(dist_root, fake), "POST", "/api/jobs/v1/jobs", body=b"{}")
    assert resp.headers["location"] == "/api/jobs/v1/jobs/abc"


def test_a_redirect_naming_the_internal_upstream_never_leaks_its_address(dist_root) -> None:
    fake = _FakeTransport(
        response=UpstreamResponse(302, (("location", f"{DASHBOARD}/dashboard/economy"),), b"")
    )
    resp = request(make_app(dist_root, fake), "GET", "/api/dashboard/x")
    assert resp.headers["location"] == "/api/dashboard/economy"


def test_every_response_names_a_gateway_request_id_that_matches_its_error_body(dist_root) -> None:
    resp = request(make_app(dist_root), "GET", "/api/zzz")
    assert resp.json()["error"]["request_id"] == resp.headers["x-gateway-request-id"]
    other = request(make_app(dist_root), "GET", "/api/zzz")
    assert other.headers["x-gateway-request-id"] != resp.headers["x-gateway-request-id"]


# --- rate limiting -------------------------------------------------------------------


def _limited(dist_root, clock=None, **extra):
    return WebGatewayService(
        dist_root,
        JOBS,
        DASHBOARD,
        _FakeTransport(),
        config=GatewayConfig(rate_limit_per_second=1, rate_limit_burst=3, **extra),
        clock=clock or _Clock(),
    )


def test_a_client_is_throttled_after_its_burst_with_a_retry_after(dist_root) -> None:
    app = _limited(dist_root)
    statuses = [request(app, "GET", "/lab/x").status for _ in range(5)]
    assert statuses == [200, 200, 200, 429, 429]
    denied = request(app, "GET", "/lab/x")
    assert int(denied.headers["retry-after"]) >= 1
    assert denied.json()["error"]["code"] == "rate_limited"


def test_each_client_address_has_its_own_budget(dist_root) -> None:
    app = _limited(dist_root)
    for _ in range(3):
        request(app, "GET", "/lab/x", client=("203.0.113.1", 1))
    assert request(app, "GET", "/lab/x", client=("203.0.113.1", 1)).status == 429
    assert request(app, "GET", "/lab/x", client=("203.0.113.2", 1)).status == 200


def test_the_budget_refills_over_time(dist_root) -> None:
    clock = _Clock()
    app = _limited(dist_root, clock)
    for _ in range(3):
        request(app, "GET", "/lab/x")
    assert request(app, "GET", "/lab/x").status == 429
    clock.now += 2.0
    assert request(app, "GET", "/lab/x").status == 200


def test_the_health_probe_is_never_rate_limited(dist_root) -> None:
    app = _limited(dist_root)
    for _ in range(3):
        request(app, "GET", "/lab/x")
    assert request(app, "GET", "/lab/x").status == 429
    assert request(app, "GET", "/health/live").status == 200


def test_malformed_requests_spend_the_budget_too(dist_root) -> None:
    app = _limited(dist_root)
    for _ in range(3):
        assert request(app, "GET", "/api/jobs/../x", raw_path=b"/api/jobs/../x").status == 400
    assert request(app, "GET", "/api/jobs/../x", raw_path=b"/api/jobs/../x").status == 429


def test_a_zero_rate_disables_limiting(dist_root) -> None:
    app = make_app(dist_root)
    assert app.limiter is None
    assert all(request(app, "GET", "/lab/x").status == 200 for _ in range(300))


def test_an_ipv6_client_is_limited_by_its_slash_64(dist_root) -> None:
    app = _limited(dist_root)
    for suffix in range(3):
        request(app, "GET", "/lab/x", client=(f"2001:db8:1:2::{suffix + 1}", 1))
    assert request(app, "GET", "/lab/x", client=("2001:db8:1:2:ffff::9", 1)).status == 429


def test_proxy_headers_are_ignored_by_default_so_they_cannot_dodge_the_limit(dist_root) -> None:
    app = _limited(dist_root)
    for i in range(3):
        request(app, "GET", "/lab/x", headers=[("x-forwarded-for", f"198.51.100.{i}")])
    assert (
        request(app, "GET", "/lab/x", headers=[("x-forwarded-for", "198.51.100.99")]).status == 429
    )


def test_a_trusted_proxy_hop_reads_the_real_client_from_x_forwarded_for(dist_root) -> None:
    app = _limited(dist_root, trusted_proxy_hops=1)
    proxy = ("10.0.0.1", 1)
    for _ in range(3):
        request(app, "GET", "/lab/x", client=proxy, headers=[("x-forwarded-for", "198.51.100.5")])
    over = request(
        app, "GET", "/lab/x", client=proxy, headers=[("x-forwarded-for", "198.51.100.5")]
    )
    other = request(
        app, "GET", "/lab/x", client=proxy, headers=[("x-forwarded-for", "198.51.100.6")]
    )
    assert (over.status, other.status) == (429, 200)


def test_a_forged_left_hand_entry_cannot_choose_the_limited_identity(dist_root) -> None:
    app = _limited(dist_root, trusted_proxy_hops=1)
    proxy = ("10.0.0.1", 1)
    for attacker_chosen in ("1.1.1.1", "2.2.2.2", "3.3.3.3", "4.4.4.4"):
        resp = request(
            app,
            "GET",
            "/lab/x",
            client=proxy,
            headers=[("x-forwarded-for", f"{attacker_chosen}, 198.51.100.5")],
        )
    assert resp.status == 429  # the proxy-appended rightmost entry is what counts


def test_a_garbage_forwarded_entry_falls_back_to_the_socket_peer(dist_root) -> None:
    fake = _FakeTransport()
    app = make_app(dist_root, fake, trusted_proxy_hops=1, rate_limit_per_second=0)
    request(
        app,
        "GET",
        "/api/jobs/v1/jobs",
        client=("10.0.0.1", 1),
        headers=[("x-forwarded-for", "not-an-ip")],
    )
    assert dict(fake.calls[0]["headers"])["x-forwarded-for"] == "10.0.0.1"


def test_denied_requests_are_logged_at_most_once_per_second_per_client(dist_root, caplog) -> None:
    clock = _Clock()
    app = _limited(dist_root, clock)
    with caplog.at_level(logging.INFO, logger="prometheus.webgateway.access"):
        for _ in range(3):
            request(app, "GET", "/lab/x")
        caplog.clear()
        for _ in range(50):
            request(app, "GET", "/lab/x")
        assert sum('"status": 429' in r.message for r in caplog.records) == 1
        clock.now += 1.5
        assert request(app, "GET", "/lab/x").status == 200  # the budget refilled one token
        assert request(app, "GET", "/lab/x").status == 429  # ...and is spent again
        assert sum('"status": 429' in r.message for r in caplog.records) == 2


# --- never blocks the event loop, never oversubscribes the backend --------------------


class _BlockingTransport:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def request(self, method, url, headers, body, *, timeout):
        self.calls += 1
        self.entered.set()
        assert self.release.wait(10), "test never released the backend"
        return UpstreamResponse(200, (), b"done")


def test_a_slow_backend_call_does_not_freeze_static_files_or_the_health_probe(dist_root) -> None:
    transport = _BlockingTransport()
    app = make_app(dist_root, transport)

    async def scenario():
        slow = asyncio.create_task(request_async(app, "GET", "/api/jobs/v1/jobs"))
        await asyncio.to_thread(transport.entered.wait, 5)
        health = await asyncio.wait_for(request_async(app, "GET", "/health/live"), timeout=3)
        static = await asyncio.wait_for(request_async(app, "GET", "/assets/app.js"), timeout=3)
        assert not slow.done(), "the proxied call must still be in flight"
        transport.release.set()
        return health, static, await slow

    health, static, slow = asyncio.run(scenario())
    assert health is not None and static is not None and slow is not None
    assert (health.status, static.status, slow.status) == (200, 200, 200)


def test_upstream_concurrency_is_capped_and_the_slot_is_released_afterwards(dist_root) -> None:
    transport = _BlockingTransport()
    app = make_app(dist_root, transport, max_upstream_inflight=1, rate_limit_per_second=0)

    async def scenario():
        first = asyncio.create_task(request_async(app, "GET", "/api/jobs/v1/jobs"))
        await asyncio.to_thread(transport.entered.wait, 5)
        second = await request_async(app, "GET", "/api/jobs/v1/jobs")
        transport.release.set()
        first_result = await first
        third = await request_async(app, "GET", "/api/jobs/v1/jobs")
        return first_result, second, third

    first, second, third = asyncio.run(scenario())
    assert second is not None and second.status == 503
    assert second.headers["retry-after"] == "1"
    assert first is not None and first.status == 200
    assert third is not None and third.status == 200
    assert transport.calls == 2


def test_a_cancelled_request_keeps_its_slot_until_the_backend_thread_really_finishes(
    dist_root,
) -> None:
    transport = _BlockingTransport()
    app = make_app(dist_root, transport, max_upstream_inflight=1, rate_limit_per_second=0)

    async def scenario():
        task = asyncio.create_task(request_async(app, "GET", "/api/jobs/v1/jobs"))
        await asyncio.to_thread(transport.entered.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert app._inflight == 1, "the backend call is still running; its slot is still taken"
        blocked = await request_async(app, "GET", "/api/jobs/v1/jobs")
        transport.release.set()
        for _ in range(100):
            if app._inflight == 0:
                break
            await asyncio.sleep(0.02)
        return blocked, app._inflight

    blocked, inflight = asyncio.run(scenario())
    assert blocked is not None and blocked.status == 503
    assert inflight == 0


# --- the structured access log --------------------------------------------------------


def test_one_json_access_line_per_request_with_no_query_and_no_credential(
    dist_root, caplog
) -> None:
    fake = _FakeTransport(
        response=UpstreamResponse(200, (("x-request-id", "backend-req-1"),), b"{}")
    )
    with caplog.at_level(logging.INFO, logger="prometheus.webgateway.access"):
        request(
            make_app(dist_root, fake),
            "GET",
            "/api/dashboard/economy",
            query=b"seed=7&token=hunter2",
            headers=[("authorization", "Bearer s3cr3t-bearer-value")],
        )
    assert len(caplog.records) == 1
    line = caplog.records[0].message
    event = json.loads(line)
    assert event["event"] == "gateway_request"
    assert event["status"] == 200 and event["route"] == "proxy:dashboard"
    assert event["method"] == "GET" and event["path"] == "/api/dashboard/economy"
    assert event["client"] == "203.0.113.7"
    assert event["upstream_status"] == 200 and event["upstream_request_id"] == "backend-req-1"
    assert event["duration_ms"] >= 0 and event["bytes"] == 2
    for secret in ("hunter2", "s3cr3t-bearer-value", "seed=7", "Bearer"):
        assert secret not in line


def test_a_hostile_path_cannot_forge_a_log_line(dist_root, caplog) -> None:
    with caplog.at_level(logging.INFO, logger="prometheus.webgateway.access"):
        request(
            make_app(dist_root),
            "GET",
            '/x\n{"event": "forged", "status": 200}',
            raw_path=b"/x%0A",
        )
    assert len(caplog.records) == 1
    assert "\n" not in caplog.records[0].message
    assert json.loads(caplog.records[0].message)["event"] == "gateway_request"


# --- construction ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "ftp://127.0.0.1:1",
        "file:///etc",
        "http://user:pw@127.0.0.1:1",
        "http://127.0.0.1:1/path",
        "http://127.0.0.1:1?x=1",
        "http://127.0.0.1:1#f",
        "127.0.0.1:1",
        "",
    ],
)
def test_an_upstream_url_must_be_a_bare_http_origin(dist_root, url) -> None:
    with pytest.raises(ValueError, match="bare http"):
        WebGatewayService(dist_root, url, DASHBOARD)
    with pytest.raises(ValueError, match="bare http"):
        WebGatewayService(dist_root, JOBS, url)


@pytest.mark.parametrize(
    "overrides",
    [
        {"max_request_body_bytes": 0},
        {"max_response_bytes": -1},
        {"max_upstream_inflight": 0},
        {"rate_limit_burst": 0},
        {"rate_limit_per_second": -1},
        {"trusted_proxy_hops": 9},
        {"trusted_proxy_hops": -1},
        {"upstream_timeout_seconds": 0},
        {"body_timeout_seconds": 601},
    ],
)
def test_gateway_config_rejects_nonsense(overrides) -> None:
    with pytest.raises(ValueError):
        GatewayConfig(**overrides)
