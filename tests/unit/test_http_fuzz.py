"""End-to-end property tests over all three ASGI apps.

The unit tests pin known attacks. These ask the opposite question: for ARBITRARY
request targets, headers, query strings and bodies -- not ones somebody thought of
-- does an app ever reach its catch-all 500? Every app has one, so a 500 means an
input class nobody handled, answered safely but still a bug; and for the gateway,
whatever bytes arrive, may it ever contact any host but the two it was configured
for? A property that holds for hundreds of generated inputs per app is stronger
evidence than the handful of examples a person would write.

The views the dashboard computes are replaced by cheap stubs (they are numerical
models, not parsers); everything BEFORE them -- header and query parsing, parameter
validation, authentication, routing, escaping, the response pipeline -- is real."""

from __future__ import annotations

import asyncio
import hashlib
import json
import urllib.parse
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from prometheus.dashboard import app as dashboard_module
from prometheus.dashboard.app import DashboardService
from prometheus.jobs.artifacts import ArtifactStore
from prometheus.jobs.store import JobStore
from prometheus.service.application import ResearchService
from prometheus.service.auth import CredentialStore
from prometheus.webgateway.app import GatewayConfig, WebGatewayService
from prometheus.webgateway.proxy import UpstreamResponse

TOKEN = "f" * 43
MARKER = "<script>alert(1)</script>"
FUZZ = settings(
    max_examples=300,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)

_TOKEN_CHARS = "!#$%&'*+.^_`|~0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-"
header_names = st.text(alphabet=_TOKEN_CHARS, min_size=1, max_size=16)
# What a real HTTP server can hand an app: printable ASCII, space, tab, obs-text.
header_values = st.text(
    alphabet=st.characters(min_codepoint=0x20, max_codepoint=0xFF, blacklist_characters="\x7f"),
    max_size=48,
)
header_pairs = st.lists(st.tuples(header_names, header_values), max_size=8)
methods = st.sampled_from(
    ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT", "FOO"]
)
chunks = st.binary(max_size=64)


async def call(app, scope_extra: dict[str, Any], body: bytes = b"") -> tuple[int, dict, bytes]:
    sent: list[dict[str, Any]] = []
    pending = [body] if body else [b""]

    async def receive():
        if pending:
            return {"type": "http.request", "body": pending.pop(), "more_body": False}
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "client": ("203.0.113.9", 4000), "scheme": "http", **scope_extra}
    await app(scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    payload = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return start["status"], dict(start["headers"]), payload


# ------------------------------------------------------------------ the gateway


class RecordingTransport:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def request(self, method, url, headers, body, *, timeout):
        self.urls.append(url)
        return UpstreamResponse(200, (("content-type", "application/json"),), b"{}")


@pytest.fixture(scope="module")
def gateway(tmp_path_factory):
    dist = tmp_path_factory.mktemp("fuzz-dist")
    (dist / "index.html").write_text("<html>shell</html>")
    (dist / "assets").mkdir()
    (dist / "assets" / "a.js").write_text("x" * 2000)
    transport = RecordingTransport()
    app = WebGatewayService(
        dist,
        "http://127.0.0.1:8765",
        "http://127.0.0.1:8766",
        transport,
        config=GatewayConfig(rate_limit_per_second=0),
    )
    return app, transport


# Pure random bytes almost never assemble "/api/jobs/../x"; a GRAMMAR of known prefixes and
# hostile segments does, so the fuzzer genuinely explores traversal, smuggling and encoding.
_HOSTILE_SEGMENTS = st.sampled_from(
    ["..", ".", "%2e%2e", "%2E%2e", "%2F", "%2f", "%5c", "a", "v1", "jobs", "x@evil.example", "@",
     ":", "", "%00", "%0d%0a", "%3F", "%23", "?", "#", " ", "\\", "%ff", "é", "%", "%zz", "..;"]
)  # fmt: skip
_structured_paths = st.builds(
    lambda prefix, segments: (prefix + "/" + "/".join(segments)).encode("latin-1", "replace"),
    st.sampled_from(
        ["/api/jobs", "/api/dashboard", "/api", "", "/assets", "/api/jobs.evil.example"]
    ),
    st.lists(_HOSTILE_SEGMENTS, max_size=6),
)

_path_bytes = st.one_of(
    _structured_paths,
    st.binary(max_size=120),
    st.text(alphabet="/@:?#\\%.;&=+ <>\"'`{}|^~!$*(),-_abcXYZ019\x00\r\n\t", max_size=60).map(
        lambda s: ("/api/" + s).encode("latin-1", "replace")
    ),
    st.sampled_from(
        [b"/api/jobs", b"/api/dashboard", b"/", b"/health/live", b"/health/ready"]
    ).flatmap(
        lambda base: st.text(alphabet="/@:%.?abc0", max_size=20).map(
            lambda s, base=base: base + s.encode("ascii")
        )
    ),
)


@FUZZ
@given(
    method=methods,
    raw_path=_path_bytes,
    query=st.binary(max_size=80),
    headers=header_pairs,
    body=chunks,
)
def test_the_gateway_never_reaches_its_catch_all_and_never_leaves_its_upstreams(
    gateway, method, raw_path, query, headers, body
) -> None:
    app, transport = gateway
    transport.urls.clear()
    path = urllib.parse.unquote(raw_path.decode("latin-1"))
    status, response_headers, payload = asyncio.run(
        call(
            app,
            {
                "method": method,
                "path": path,
                "raw_path": raw_path,
                "query_string": query,
                "headers": [(k.encode("latin-1"), v.encode("latin-1")) for k, v in headers],
            },
            body,
        )
    )
    assert status != 500, (
        f"catch-all reached for {method} {raw_path!r}?{query!r}: {payload[:120]!r}"
    )
    assert status in {200, 304, 400, 404, 405, 413, 429, 431}, status
    assert response_headers[b"x-content-type-options"] == b"nosniff"
    assert b"x-gateway-request-id" in response_headers
    if status >= 400 and method != "HEAD":  # a HEAD response carries no body
        assert json.loads(payload)["error"]["code"]
    for url in transport.urls:
        parts = urllib.parse.urlsplit(url)
        assert parts.netloc in ("127.0.0.1:8765", "127.0.0.1:8766"), url
        assert parts.path.startswith("/") and not parts.fragment and "@" not in parts.netloc
        assert ".." not in [segment for segment in parts.path.split("/")]


# ------------------------------------------------------------------ the dashboard

_JSON_VIEWS = (
    "economy_explorer_as_json",
    "market_paths_as_json",
    "hedge_actions_as_json",
    "portfolio_risk_as_json",
    "pricing_diagnostics_as_json",
    "inflationcast_as_json",
    "experiment_comparison_as_json",
    "audit_trail_as_json",
    "balance_sheets_as_json",
)
_HTML_VIEWS = (
    "render_economy_explorer",
    "render_market_paths",
    "render_hedge_actions",
    "render_portfolio_risk",
    "render_pricing_diagnostics",
    "render_inflationcast",
    "render_experiment_comparison",
    "render_audit_trail",
    "render_balance_sheets",
    "render_printable_html",
)


@pytest.fixture(scope="module")
def dashboard(tmp_path_factory):
    with pytest.MonkeyPatch.context() as patch:
        for name in _JSON_VIEWS:
            patch.setattr(dashboard_module, name, lambda *a, **k: {"ok": True})
        for name in _HTML_VIEWS:
            patch.setattr(dashboard_module, name, lambda *a, **k: "<p>ok</p>")
        patch.setattr(dashboard_module, "build_export", lambda *a, **k: object())
        root = tmp_path_factory.mktemp("fuzz-dash")
        auth = root / "auth.json"
        auth.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "credentials": [
                        {
                            "subject": "s",
                            "owner": "alice",
                            "scopes": ["read"],
                            "token_sha256": hashlib.sha256(TOKEN.encode()).hexdigest(),
                        }
                    ],
                }
            )
        )
        auth.chmod(0o600)
        yield DashboardService(CredentialStore(auth), portfolios={})


_DASH_PATHS = st.sampled_from(
    [
        "/dashboard",
        "/dashboard/",
        "/dashboard/economy",
        "/dashboard/market-paths",
        "/dashboard/hedge-actions",
        "/dashboard/portfolio-risk",
        "/dashboard/pricing",
        "/dashboard/inflationcast",
        "/dashboard/model-usage",
        "/dashboard/export",
        "/dashboard/experiments",
        "/dashboard/audit-trail",
        "/dashboard/validation-issues",
        "/dashboard/portfolio/alice",
        "/dashboard/nope",
        "/health/live",
    ]
)
_PARAM_NAMES = st.sampled_from(
    ["n_steps", "n_paths", "seed", "s0", "mu", "sigma", "maturity", "strike", "rate", "spot",
     "volatility", "n", "alpha", "max_epochs", "patience", "bootstrap_resamples", "model_id",
     "application", "view", "format"]
)  # fmt: skip
_PARAM_VALUES = st.one_of(
    st.just(MARKER),
    st.sampled_from(["json", "nan", "inf", "-1", "0", "1e999", "1_0", "0x10", "٣", "9" * 30, ""]),
    st.integers(min_value=-(10**13), max_value=10**13).map(str),
    st.floats(allow_nan=True, allow_infinity=True).map(repr),
    st.text(max_size=20),
)
_QUERIES = st.one_of(
    st.lists(st.tuples(_PARAM_NAMES, _PARAM_VALUES), max_size=10).map(
        lambda pairs: urllib.parse.urlencode(pairs).encode("ascii")
    ),
    st.binary(max_size=100),
)


@FUZZ
@given(path=_DASH_PATHS, query=_QUERIES, headers=header_pairs, authenticated=st.booleans())
def test_the_dashboard_never_reaches_its_catch_all_and_never_reflects_markup(
    dashboard, path, query, headers, authenticated
) -> None:
    pairs = [(k.encode("latin-1"), v.encode("latin-1")) for k, v in headers]
    if authenticated:
        pairs.append((b"authorization", b"Bearer " + TOKEN.encode()))
    status, response_headers, payload = asyncio.run(
        call(
            dashboard,
            {"method": "GET", "path": path, "query_string": query, "headers": pairs},
        )
    )
    assert status != 500, f"catch-all reached for {path}?{query!r}: {payload[:160]!r}"
    assert status in {200, 400, 401, 403, 404, 405, 414, 429, 431, 503}, status
    assert response_headers[b"x-content-type-options"] == b"nosniff"
    assert b"<script>alert" not in payload, "caller markup reflected unescaped"
    if not authenticated and path != "/health/live":
        assert status in {400, 401, 405, 414, 431}


# ------------------------------------------------------------------ the job API


@pytest.fixture(scope="module")
def service(tmp_path_factory):
    root = tmp_path_factory.mktemp("fuzz-service")
    auth = root / "auth"
    auth.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "credentials": [
                    {
                        "subject": "s",
                        "owner": "alice",
                        "scopes": ["read", "write"],
                        "token_sha256": hashlib.sha256(TOKEN.encode()).hexdigest(),
                    }
                ],
            }
        )
    )
    auth.chmod(0o600)
    return ResearchService(
        JobStore(root / "jobs.sqlite3"), ArtifactStore(root / "artifacts"), CredentialStore(auth)
    )


_json_values = st.recursive(
    st.none()
    | st.booleans()
    | st.integers()
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text(max_size=12),
    lambda children: (
        st.lists(children, max_size=4) | st.dictionaries(st.text(max_size=8), children, max_size=4)
    ),
    max_leaves=12,
)
_bodies = st.one_of(
    st.binary(max_size=200),
    _json_values.map(lambda v: json.dumps(v, allow_nan=False).encode()),
    st.fixed_dictionaries(
        {"kind": st.sampled_from(["economy", "qmacro", "x", 1, None]), "config": _json_values}
    ).map(lambda v: json.dumps(v, allow_nan=False).encode()),
)
_SERVICE_PATHS = st.one_of(
    st.sampled_from(["/v1/jobs", "/v1/openapi.json", "/health/live", "/health/ready", "/v1/nope"]),
    st.uuids().map(lambda u: f"/v1/jobs/{u}"),
    st.uuids().map(lambda u: f"/v1/jobs/{u}/artifact"),
    st.uuids().map(lambda u: f"/v1/jobs/{u}/cancel"),
    st.text(alphabet="/abc-0123456789%", max_size=30).map(lambda s: "/v1/jobs" + s),
)


@FUZZ
@given(
    method=st.sampled_from(["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"]),
    path=_SERVICE_PATHS,
    query=st.one_of(
        st.just(b""),
        st.binary(max_size=60),
        st.text(alphabet="limit=cursor&0123456789", max_size=24).map(str.encode),
    ),
    headers=header_pairs,
    body=_bodies,
    authenticated=st.booleans(),
    declare_json=st.booleans(),
)
def test_the_job_api_never_reaches_its_catch_all_for_any_request(
    service, method, path, query, headers, body, authenticated, declare_json
) -> None:
    pairs = [(b"host", b"localhost")]
    pairs += [
        (k.encode("latin-1"), v.encode("latin-1"))
        for k, v in headers
        if k.lower()
        not in {"host", "authorization", "content-length", "transfer-encoding", "content-encoding"}
    ]
    if authenticated:
        pairs.append((b"authorization", b"Bearer " + TOKEN.encode()))
    if declare_json:
        pairs.append((b"content-type", b"application/json"))
        pairs.append((b"idempotency-key", b"fuzz-key"))
    status, response_headers, payload = asyncio.run(
        call(
            service,
            {
                "method": method,
                "path": path,
                "query_string": query,
                "headers": pairs,
                "client": ("127.0.0.1", 4000),
            },
            body,
        )
    )
    assert status != 500, f"catch-all reached for {method} {path}?{query!r}: {payload[:200]!r}"
    assert status in {
        200,
        202,
        400,
        401,
        403,
        404,
        405,
        408,
        409,
        413,
        414,
        415,
        422,
        429,
        431,
        503,
    }, status
    assert response_headers[b"x-content-type-options"] == b"nosniff"
    parsed = json.loads(payload)
    if status >= 400:
        assert parsed["error"]["code"] and parsed["error"]["request_id"]
