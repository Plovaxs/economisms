from __future__ import annotations

import asyncio
import hashlib
import json

import pytest

from prometheus.core.ledger import Ledger
from prometheus.core.money import Money
from prometheus.dashboard.app import DashboardService
from prometheus.econosim.agents import Household
from prometheus.service.auth import CredentialStore

ALICE, BOB = "a" * 43, "b" * 43


def auth_entry(token: str, owner: str) -> dict[str, object]:
    return {
        "subject": owner + "-sub",
        "owner": owner,
        "scopes": ["read"],
        "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
    }


@pytest.fixture
def app(tmp_path):
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "credentials": [auth_entry(ALICE, "alice"), auth_entry(BOB, "bob")],
            }
        )
    )
    auth_path.chmod(0o600)
    alice_ledger = Ledger()
    Household(alice_ledger, "alice-hh").receive_income(Money(5_000, "USD"), step=0)
    return DashboardService(CredentialStore(auth_path), portfolios={"alice": alice_ledger})


async def _request_async(app, path, token, query=""):
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    headers = [(b"host", b"localhost")]
    if token is not None:
        headers.append((b"authorization", ("Bearer " + token).encode()))
    await app(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "query_string": query.encode("ascii"),
            "headers": headers,
        },
        receive,
        send,
    )
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(m["body"] for m in sent if m["type"] == "http.response.body")
    return start["status"], body.decode("utf-8")


def request(app, path, token, query=""):
    return asyncio.run(_request_async(app, path, token, query))


def test_health_endpoint_is_public(app) -> None:
    status, body = request(app, "/health/live", None)
    assert status == 200
    assert "live" in body


def test_a_request_with_no_token_is_refused(app) -> None:
    status, _ = request(app, "/dashboard/experiments", None)
    assert status == 401


def test_owner_can_view_their_own_real_portfolio(app) -> None:
    status, body = request(app, "/dashboard/portfolio/alice", ALICE)
    assert status == 200
    assert "alice-hh:deposit" in body


def test_a_different_owner_is_refused_access_to_alices_real_portfolio(app) -> None:
    """UIX-10's real, end-to-end negative case: bob's own valid token
    authenticates fine, but is refused Alice's portfolio data."""
    status, _ = request(app, "/dashboard/portfolio/alice", BOB)
    assert status == 403


def test_experiment_comparison_is_reachable_with_a_valid_token(app) -> None:
    status, body = request(app, "/dashboard/experiments", ALICE)
    assert status == 200
    assert "NOT SIGNIFICANT" in body


def test_pricing_view_renders_with_query_parameters(app) -> None:
    status, body = request(app, "/dashboard/pricing", ALICE, "strike=105&maturity=0.5")
    assert status == 200
    assert "Black-Scholes" in body


def test_unknown_path_is_404(app) -> None:
    status, _ = request(app, "/dashboard/does-not-exist", ALICE)
    assert status == 404


def test_index_page_lists_every_real_wired_view(app) -> None:
    status, body = request(app, "/dashboard", ALICE)
    assert status == 200
    for href, _label in [
        ("/dashboard/economy", None),
        ("/dashboard/market-paths", None),
        ("/dashboard/pricing", None),
        ("/dashboard/hedge-actions", None),
        ("/dashboard/portfolio-risk", None),
        ("/dashboard/experiments", None),
        ("/dashboard/audit-trail", None),
    ]:
        assert href in body


def test_economy_explorer_is_reachable_with_a_valid_token(app) -> None:
    status, body = request(app, "/dashboard/economy", ALICE, "n_steps=3&seed=1")
    assert status == 200
    assert "SYNTHETIC" in body


def test_market_paths_view_is_reachable_and_uses_query_parameters(app) -> None:
    status, body = request(app, "/dashboard/market-paths", ALICE, "sigma=0.4&n_paths=500")
    assert status == 200
    assert "percentile" in body.lower()


def test_hedge_actions_view_is_reachable(app) -> None:
    status, body = request(app, "/dashboard/hedge-actions", ALICE, "n_steps=5&n_paths=50")
    assert status == 200
    assert "hedge ratio" in body.lower()


def test_portfolio_risk_view_is_reachable(app) -> None:
    status, body = request(app, "/dashboard/portfolio-risk", ALICE, "alpha=0.99")
    assert status == 200
    assert "Historical VaR" in body


def test_audit_trail_view_is_reachable_and_shows_a_realistic_transition_chain(app) -> None:
    status, body = request(app, "/dashboard/audit-trail", ALICE)
    assert status == 200
    assert "evaluated" in body
    assert "approved" in body


def test_export_view_requires_a_known_view_name(app) -> None:
    status, body = request(app, "/dashboard/export", ALICE, "view=not-a-real-view")
    assert status == 404
    assert "exportable" in body


def test_export_view_embeds_a_real_run_hash_for_a_known_view(app) -> None:
    status, body = request(app, "/dashboard/export", ALICE, "view=experiments")
    assert status == 200
    assert "run_hash" in body or "run hash" in body.lower()


def test_every_real_view_is_refused_without_a_valid_token(app) -> None:
    for path in (
        "/dashboard", "/dashboard/economy", "/dashboard/market-paths",
        "/dashboard/hedge-actions", "/dashboard/portfolio-risk",
        "/dashboard/audit-trail", "/dashboard/export",
        "/dashboard/validation-issues", "/dashboard/model-usage",
    ):
        status, _ = request(app, path, None)
        assert status == 401, f"{path} did not require authentication"


async def _run_lifespan(app) -> list[dict]:
    """A real ASGI lifespan handshake, the exact sequence a real server
    (uvicorn) sends before any HTTP request -- a bug here was caught
    ONLY by actually running this app under uvicorn (`python -m
    prometheus.dashboard serve`), not by any `"type": "http"` scope
    built directly, which is why this regression test drives the
    lifespan protocol explicitly rather than only the HTTP path."""
    sent = []
    messages = iter([{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}])

    async def receive():
        return next(messages)

    async def send(message):
        sent.append(message)

    await app({"type": "lifespan"}, receive, send)
    return sent


def test_the_app_completes_a_real_asgi_lifespan_handshake(app) -> None:
    """Regression test: uvicorn sends a 'lifespan' scope on startup
    before any request; this app previously raised
    ValueError("this dashboard app serves HTTP only") for it, which
    crashed real server startup (`python -m prometheus.dashboard serve`)
    while every unit test here still passed, since none exercised this
    scope type."""
    sent = asyncio.run(_run_lifespan(app))
    assert {"type": "lifespan.startup.complete"} in sent
    assert {"type": "lifespan.shutdown.complete"} in sent


def test_model_usage_is_authorized_for_a_real_known_model_and_application(app) -> None:
    status, body = request(
        app, "/dashboard/model-usage", ALICE, "model_id=recessionnet&application=research"
    )
    assert status == 200
    assert "authorized" in body.lower()


def test_model_usage_rejects_an_unsupported_application(app) -> None:
    """MGR-11's own acceptance wording: "authorization and UI reject
    unsupported decisions" -- a real, live 403 for a real model with a
    genuinely unauthorized requested application."""
    status, body = request(
        app, "/dashboard/model-usage", ALICE, "model_id=recessionnet&application=live_trading"
    )
    assert status == 403
    assert "not authorized" in body.lower()


def test_model_usage_rejects_an_unknown_model_id(app) -> None:
    status, _ = request(
        app, "/dashboard/model-usage", ALICE, "model_id=not-a-real-model&application=research"
    )
    assert status == 403


def test_validation_issues_view_lists_the_real_tracked_findings(app) -> None:
    status, body = request(app, "/dashboard/validation-issues", ALICE)
    assert status == 200
    assert "VAL-2026-001" in body
    assert "remediated" in body
