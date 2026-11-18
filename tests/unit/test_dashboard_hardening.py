"""The dashboard behind the gateway: every numeric parameter bounded, caller
text escaped, compute off the event loop under a hard cap, per-owner rate
limits, a catch-all, security headers and an audit log.

Before this, `GET /dashboard/portfolio-risk?n=100000000000` made numpy
allocate an 800 GB array for a caller holding nothing but a read-only
token, one slow view froze `/health/live`, and a non-ASCII query was an
unhandled exception."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import threading
from typing import Any

import pytest

from prometheus.dashboard import app as app_module
from prometheus.dashboard.app import HTML_CSP, DashboardPolicy, DashboardService, _error_body
from prometheus.evidence.model_inventory import UnauthorizedModelUsageError
from prometheus.httpsec.headers import API_CSP
from prometheus.service.auth import CredentialStore

ALICE, BOB = "a" * 43, "b" * 43
ALWAYS = {
    b"x-content-type-options": b"nosniff",
    b"x-frame-options": b"DENY",
    b"referrer-policy": b"no-referrer",
    b"cross-origin-opener-policy": b"same-origin",
    b"cross-origin-resource-policy": b"same-origin",
}


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def auth_entry(token: str, owner: str) -> dict[str, object]:
    return {
        "subject": owner + "-sub",
        "owner": owner,
        "scopes": ["read"],
        "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
    }


@pytest.fixture
def credentials(tmp_path):
    path = tmp_path / "auth.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "credentials": [auth_entry(ALICE, "alice"), auth_entry(BOB, "bob")],
            }
        )
    )
    path.chmod(0o600)
    return CredentialStore(path)


def make_app(credentials, **kwargs) -> DashboardService:
    return DashboardService(credentials, portfolios={}, **kwargs)


async def call(
    app,
    path,
    *,
    token=ALICE,
    query=b"",
    method="GET",
    headers=(),
    scheme="http",
):
    sent: list[dict[str, Any]] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    pairs = [(b"host", b"localhost"), *headers]
    if token is not None:
        pairs.append((b"authorization", ("Bearer " + token).encode()))
    await app(
        {
            "type": "http",
            "method": method,
            "path": path,
            "query_string": query if isinstance(query, bytes) else query.encode("ascii"),
            "headers": pairs,
            "client": ("127.0.0.1", 4000),
            "scheme": scheme,
        },
        receive,
        send,
    )
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return start["status"], body, dict(start["headers"])


def get(app, path, **kwargs):
    return asyncio.run(call(app, path, **kwargs))


def boom(*args, **kwargs):
    raise AssertionError("a view must never be computed for a rejected request")


# --- every numeric parameter is bounded: nothing computes for a rejected request ------

HOSTILE = [
    ("/dashboard/portfolio-risk", "n=100000000000", "portfolio_risk_as_json"),
    ("/dashboard/portfolio-risk", "n=9", "portfolio_risk_as_json"),
    ("/dashboard/portfolio-risk", "alpha=1", "portfolio_risk_as_json"),
    ("/dashboard/portfolio-risk", "alpha=nan", "portfolio_risk_as_json"),
    ("/dashboard/portfolio-risk", "seed=-1", "portfolio_risk_as_json"),
    ("/dashboard/inflationcast", "max_epochs=1000000", "inflationcast_as_json"),
    ("/dashboard/inflationcast", "patience=0", "inflationcast_as_json"),
    ("/dashboard/inflationcast", "bootstrap_resamples=99999999", "inflationcast_as_json"),
    ("/dashboard/market-paths", "n_paths=20001", "market_paths_as_json"),
    ("/dashboard/market-paths", "n_steps=366", "market_paths_as_json"),
    ("/dashboard/market-paths", "n_steps=365&n_paths=20000", "market_paths_as_json"),
    ("/dashboard/market-paths", "sigma=0", "market_paths_as_json"),
    ("/dashboard/market-paths", "sigma=nan", "market_paths_as_json"),
    ("/dashboard/market-paths", "s0=-1", "market_paths_as_json"),
    ("/dashboard/market-paths", "s0=1e999", "market_paths_as_json"),
    ("/dashboard/hedge-actions", "n_paths=5001", "hedge_actions_as_json"),
    ("/dashboard/hedge-actions", "n_steps=250&n_paths=5000", "hedge_actions_as_json"),
    ("/dashboard/hedge-actions", "rate=2", "hedge_actions_as_json"),
    ("/dashboard/economy", "n_steps=0", "economy_explorer_as_json"),
    ("/dashboard/economy", "n_steps=121", "economy_explorer_as_json"),
    ("/dashboard/economy", "n_steps=abc", "economy_explorer_as_json"),
    ("/dashboard/economy", "n_steps=1&n_steps=2", "economy_explorer_as_json"),
    ("/dashboard/economy", "seed=4294967296", "economy_explorer_as_json"),
    ("/dashboard/pricing", "maturity=0", "pricing_diagnostics_as_json"),
    ("/dashboard/pricing", "strike=0", "pricing_diagnostics_as_json"),
    ("/dashboard/pricing", "volatility=100", "pricing_diagnostics_as_json"),
]


@pytest.mark.parametrize(("path", "query", "view"), HOSTILE)
def test_out_of_range_parameters_are_400_and_nothing_is_computed(
    credentials, monkeypatch, path, query, view
) -> None:
    monkeypatch.setattr(app_module, view, boom)
    status, body, _ = get(make_app(credentials), path, query=query + "&format=json")
    assert status == 400, body
    assert "error" in json.loads(body)


def test_values_exactly_at_the_limits_are_computed(credentials, monkeypatch) -> None:
    seen = {}

    def spy(**kwargs):
        seen.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(app_module, "market_paths_as_json", spy)
    status, _, _ = get(
        make_app(credentials),
        "/dashboard/market-paths",
        query="n_paths=20000&n_steps=100&sigma=5&s0=10000000&format=json",
    )
    assert status == 200
    assert seen["n_paths"] == 20000 and seen["n_steps"] == 100
    assert seen["sigma"] == 5.0 and seen["s0"] == 1e7


def test_the_portfolio_risk_allocation_that_used_to_be_possible_is_refused(
    credentials, monkeypatch
) -> None:
    import numpy as np

    def no_allocation(*args, **kwargs):
        raise AssertionError("numpy must never be asked for this array")

    monkeypatch.setattr(np.random, "default_rng", no_allocation)
    status, _, _ = get(
        make_app(credentials), "/dashboard/portfolio-risk", query="n=100000000000&format=json"
    )
    assert status == 400


# --- malformed input is a client error, never an unhandled exception ------------------


def test_a_non_ascii_query_is_400_json(credentials) -> None:
    status, body, headers = get(make_app(credentials), "/dashboard/economy", query=b"q=\xc3\xa9")
    assert status == 400
    assert headers[b"content-type"] == b"application/json"


def test_an_oversize_query_is_414(credentials) -> None:
    status, _, _ = get(make_app(credentials), "/dashboard/economy", query=b"x=" + b"a" * 3000)
    assert status == 414


def test_an_oversize_path_is_414(credentials) -> None:
    assert get(make_app(credentials), "/dashboard/" + "a" * 3000)[0] == 414


def test_non_ascii_header_bytes_are_400_not_a_crash(credentials) -> None:
    status, _, _ = get(
        make_app(credentials), "/dashboard/economy", headers=[(b"x-note", "é".encode("latin-1"))]
    )
    assert status == 400


def test_two_authorization_headers_are_ambiguous_and_refused(credentials) -> None:
    status, _, _ = get(
        make_app(credentials),
        "/dashboard/economy",
        headers=[(b"authorization", b"Bearer " + BOB.encode())],
    )
    assert status == 400


def test_too_many_or_too_large_headers_are_431(credentials) -> None:
    many = [(f"x-h{i}".encode(), b"v") for i in range(70)]
    assert get(make_app(credentials), "/dashboard/economy", headers=many)[0] == 431
    big = [(b"x-big", b"v" * 17000)]
    assert get(make_app(credentials), "/dashboard/economy", headers=big)[0] == 431


def test_only_get_is_supported(credentials) -> None:
    for method in ("POST", "PUT", "DELETE", "PATCH", "OPTIONS"):
        status, _, _ = get(make_app(credentials), "/dashboard/economy", method=method)
        assert status == 405


def test_unauthenticated_requests_learn_nothing_about_which_paths_exist(
    credentials, monkeypatch
) -> None:
    monkeypatch.setattr(app_module, "economy_explorer_as_json", boom)
    app = make_app(credentials)
    for path in ("/dashboard/economy", "/dashboard/nope", "/anything/else"):
        status, _, headers = get(app, path, token=None)
        assert status == 401, path
        assert headers[b"www-authenticate"] == b"Bearer"
    assert get(app, "/dashboard/economy", token="z" * 43)[0] == 401


def test_a_portfolio_owner_outside_the_identifier_grammar_is_404(credentials) -> None:
    app = make_app(credentials)
    for owner in ("a/b", "a b", "<script>", "a" * 200, ""):
        status, _, _ = get(app, "/dashboard/portfolio/" + owner)
        assert status == 404, repr(owner)


# --- caller-supplied text is never reflected into HTML unescaped ----------------------


def test_the_error_page_escapes_whatever_message_it_is_given() -> None:
    html, content_type = _error_body("<script>alert(1)</script>", want_json=False)
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert content_type.startswith("text/html")


def test_an_unauthorized_model_message_is_escaped_in_the_html_error_page(
    credentials, monkeypatch
) -> None:
    def deny(model_id, application):
        raise UnauthorizedModelUsageError("<img src=x onerror=alert(1)>")

    monkeypatch.setattr(app_module, "authorize_model_usage", deny)
    status, body, _ = get(
        make_app(credentials), "/dashboard/model-usage", query="model_id=m&application=a"
    )
    assert status == 403
    assert b"<img" not in body and b"&lt;img" in body


def test_hostile_model_id_application_and_view_values_are_rejected_not_reflected(
    credentials,
) -> None:
    app = make_app(credentials)
    for path, query in (
        ("/dashboard/model-usage", "model_id=<script>alert(1)</script>&application=x"),
        ("/dashboard/model-usage", "model_id=m&application=%3Cb%3E"),
        ("/dashboard/export", "view=%3Cscript%3E"),
    ):
        status, body, _ = get(app, path, query=query)
        assert status == 400
        assert b"<script>" not in body and b"alert(1)" not in body


def test_a_unknown_but_well_formed_view_name_is_a_404(credentials) -> None:
    status, body, _ = get(make_app(credentials), "/dashboard/export", query="view=nope")
    assert status == 404
    assert b"nope" in body  # a validated token may be echoed, escaped


# --- security headers on every response ------------------------------------------------


def _scenarios(credentials, monkeypatch):
    monkeypatch.setattr(
        app_module,
        "pricing_diagnostics_as_json",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")),
    )
    app = make_app(credentials)
    return {
        "html-200": (app, "/dashboard", {}),
        "json-200": (app, "/dashboard", {"query": "format=json"}),
        "health": (app, "/health/live", {"token": None}),
        "400": (app, "/dashboard/economy", {"query": "n_steps=0&format=json"}),
        "401": (app, "/dashboard", {"token": None}),
        "404": (app, "/dashboard/nope", {"query": "format=json"}),
        "405": (app, "/dashboard", {"method": "POST"}),
        "500": (app, "/dashboard/pricing", {"query": "format=json"}),
    }


@pytest.mark.parametrize(
    "name", ["html-200", "json-200", "health", "400", "401", "404", "405", "500"]
)
def test_every_response_carries_the_enforced_security_headers(
    credentials, monkeypatch, name
) -> None:
    app, path, kwargs = _scenarios(credentials, monkeypatch)[name]
    _, _, headers = get(app, path, **kwargs)
    for header, value in ALWAYS.items():
        assert headers[header] == value, (name, header)
    assert b"camera=()" in headers[b"permissions-policy"]
    assert headers[b"cache-control"] == b"no-store"
    assert b"x-request-id" in headers
    assert b"strict-transport-security" not in headers
    assert b"server" not in headers


def test_html_pages_get_a_script_less_csp_and_json_gets_the_api_one(credentials) -> None:
    app = make_app(credentials)
    _, _, html = get(app, "/dashboard")
    assert html[b"content-security-policy"] == HTML_CSP.encode()
    assert b"script-src" not in html[b"content-security-policy"]
    assert b"default-src 'none'" in html[b"content-security-policy"]
    _, _, js = get(app, "/dashboard", query="format=json")
    assert js[b"content-security-policy"] == API_CSP.encode()


def test_hsts_is_sent_only_over_https(credentials) -> None:
    app = make_app(credentials)
    assert b"max-age" in get(app, "/dashboard", scheme="https")[2][b"strict-transport-security"]
    assert b"strict-transport-security" not in get(app, "/dashboard", scheme="http")[2]


# --- a catch-all: no detail to the client, full detail to the log -----------------------


def test_an_unexpected_failure_is_a_generic_500_logged_server_side(
    credentials, monkeypatch, caplog
) -> None:
    def fail(**kwargs):
        raise RuntimeError("secret detail: /srv/data/auth.json")

    monkeypatch.setattr(app_module, "economy_explorer_as_json", fail)
    with caplog.at_level(logging.INFO, logger="prometheus.dashboard.audit"):
        status, body, headers = get(
            make_app(credentials), "/dashboard/economy", query="format=json"
        )
    assert status == 500
    assert json.loads(body) == {"error": "unexpected dashboard failure"}
    assert b"secret" not in body and b"auth.json" not in body
    assert "secret detail" in caplog.text
    assert headers[b"x-content-type-options"] == b"nosniff"


def test_the_html_500_is_generic_too(credentials, monkeypatch) -> None:
    monkeypatch.setattr(
        app_module,
        "render_economy_explorer",
        lambda **k: (_ for _ in ()).throw(ValueError("x /etc")),
    )
    status, body, _ = get(make_app(credentials), "/dashboard/economy")
    assert status == 500
    assert b"/etc" not in body and b"unexpected dashboard failure" in body


# --- compute never blocks the event loop; concurrency is bounded ------------------------


class Gate:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def view(self, **kwargs):
        self.calls += 1
        self.entered.set()
        assert self.release.wait(10), "test never released the view"
        return {"ok": True}


def test_a_slow_view_does_not_freeze_the_health_probe(credentials, monkeypatch) -> None:
    gate = Gate()
    monkeypatch.setattr(app_module, "economy_explorer_as_json", gate.view)
    app = make_app(credentials)

    async def scenario():
        slow = asyncio.create_task(call(app, "/dashboard/economy", query="format=json"))
        await asyncio.to_thread(gate.entered.wait, 5)
        health = await asyncio.wait_for(call(app, "/health/live", token=None), timeout=3)
        assert not slow.done(), "the view must still be computing"
        gate.release.set()
        return health, await slow

    health, slow = asyncio.run(scenario())
    assert health[0] == 200 and slow[0] == 200


def test_concurrent_views_are_capped_and_the_slot_is_released(credentials, monkeypatch) -> None:
    gate = Gate()
    monkeypatch.setattr(app_module, "economy_explorer_as_json", gate.view)
    app = make_app(credentials, policy=DashboardPolicy(max_inflight=1, burst=1000))

    async def scenario():
        first = asyncio.create_task(call(app, "/dashboard/economy", query="format=json"))
        await asyncio.to_thread(gate.entered.wait, 5)
        second = await call(app, "/dashboard/economy", query="format=json")
        gate.release.set()
        first_result = await first
        third = await call(app, "/dashboard/economy", query="format=json")
        return first_result, second, third

    first, second, third = asyncio.run(scenario())
    assert second[0] == 503 and second[2][b"retry-after"] == b"1"
    assert first[0] == 200 and third[0] == 200
    assert gate.calls == 2


def test_a_cancelled_request_keeps_its_slot_until_the_thread_finishes(
    credentials, monkeypatch
) -> None:
    gate = Gate()
    monkeypatch.setattr(app_module, "economy_explorer_as_json", gate.view)
    app = make_app(credentials, policy=DashboardPolicy(max_inflight=1, burst=1000))

    async def scenario():
        task = asyncio.create_task(call(app, "/dashboard/economy", query="format=json"))
        await asyncio.to_thread(gate.entered.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert app.executor.inflight == 1
        blocked = await call(app, "/dashboard/economy", query="format=json")
        gate.release.set()
        for _ in range(100):
            if app.executor.inflight == 0:
                break
            await asyncio.sleep(0.02)
        return blocked, app.executor.inflight

    blocked, inflight = asyncio.run(scenario())
    assert blocked[0] == 503 and inflight == 0


# --- per-owner rate limiting ------------------------------------------------------------


def test_each_owner_has_a_budget_and_unauthenticated_calls_spend_nobody_elses(
    credentials, monkeypatch
) -> None:
    monkeypatch.setattr(app_module, "economy_explorer_as_json", lambda **k: {"ok": 1})
    clock = Clock()
    app = make_app(credentials, policy=DashboardPolicy(requests_per_second=1, burst=2), clock=clock)
    for _ in range(10):
        assert get(app, "/dashboard/economy", token=None, query="format=json")[0] == 401
    statuses = [get(app, "/dashboard/economy", query="format=json")[0] for _ in range(3)]
    assert statuses == [200, 200, 429]
    status, _, headers = get(app, "/dashboard/economy", query="format=json")
    assert status == 429 and int(headers[b"retry-after"]) >= 1
    assert get(app, "/dashboard/economy", token=BOB, query="format=json")[0] == 200
    clock.now += 5
    assert get(app, "/dashboard/economy", query="format=json")[0] == 200


def test_the_health_probe_is_never_rate_limited(credentials) -> None:
    clock = Clock()
    app = make_app(credentials, policy=DashboardPolicy(requests_per_second=1, burst=1), clock=clock)
    assert all(get(app, "/health/live", token=None)[0] == 200 for _ in range(20))


# --- health and the audit log ------------------------------------------------------------


def test_health_is_get_and_head_only(credentials) -> None:
    app = make_app(credentials)
    assert get(app, "/health/live", token=None)[0] == 200
    status, body, headers = get(app, "/health/live", token=None, method="HEAD")
    assert status == 200 and body == b"" and int(headers[b"content-length"]) > 0
    assert get(app, "/health/live", token=None, method="POST")[0] == 405


def test_one_audit_line_per_request_with_no_query_and_no_credential(
    credentials, monkeypatch, caplog
) -> None:
    monkeypatch.setattr(app_module, "economy_explorer_as_json", lambda **k: {"ok": 1})
    with caplog.at_level(logging.INFO, logger="prometheus.dashboard.audit"):
        get(make_app(credentials), "/dashboard/economy", query="seed=7&format=json")
    assert len(caplog.records) == 1
    line = caplog.records[0].message
    event = json.loads(line)
    assert event["event"] == "dashboard_request" and event["status"] == 200
    assert event["subject"] == "alice-sub" and event["path"] == "/dashboard/economy"
    assert len(event["request_id"]) == 32
    for leaked in (ALICE, "seed=7", "Bearer"):
        assert leaked not in line


def test_a_hostile_path_cannot_forge_an_audit_line(credentials, caplog) -> None:
    with caplog.at_level(logging.INFO, logger="prometheus.dashboard.audit"):
        get(make_app(credentials), '/x\n{"event": "forged"}', token=None)
    assert len(caplog.records) == 1 and "\n" not in caplog.records[0].message


# --- construction -------------------------------------------------------------------------


def test_websocket_connections_are_refused(credentials) -> None:
    sent = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "websocket.connect"}

    asyncio.run(make_app(credentials)({"type": "websocket"}, receive, send))
    assert sent == [{"type": "websocket.close", "code": 1008}]


@pytest.mark.parametrize(
    "overrides",
    [
        {"max_inflight": 0},
        {"burst": 0},
        {"requests_per_second": 0},
        {"requests_per_second": 100_000},
        {"max_headers": 0},
        {"max_header_bytes": -1},
    ],
)
def test_dashboard_policy_rejects_nonsense(overrides) -> None:
    with pytest.raises(ValueError):
        DashboardPolicy(**overrides)
