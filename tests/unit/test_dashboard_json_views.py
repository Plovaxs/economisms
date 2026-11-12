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


def _auth_entry(token: str, owner: str) -> dict[str, object]:
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
                "credentials": [_auth_entry(ALICE, "alice"), _auth_entry(BOB, "bob")],
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
    response_headers = {k.decode("ascii").lower(): v.decode("ascii") for k, v in start["headers"]}
    return start["status"], response_headers, body.decode("utf-8")


def request_json(app, path, token, query=""):
    sep = "&" if query else ""
    full_query = query + sep + "format=json"
    status, headers, body = asyncio.run(_request_async(app, path, token, full_query))
    return status, headers, body


def test_index_json_lists_every_real_wired_view(app) -> None:
    status, headers, body = request_json(app, "/dashboard", ALICE)
    assert status == 200
    assert headers["content-type"].startswith("application/json")
    payload = json.loads(body)
    hrefs = {link["href"] for link in payload["links"]}
    assert "/dashboard/economy" in hrefs
    assert "/dashboard/inflationcast" in hrefs


def test_economy_json_has_real_step_and_shock_values(app) -> None:
    status, headers, body = request_json(app, "/dashboard/economy", ALICE, "n_steps=3&seed=1")
    assert status == 200
    assert headers["content-type"].startswith("application/json")
    payload = json.loads(body)
    assert payload["provenance"] == "synthetic"
    assert len(payload["steps"]) == 3
    assert payload["steps"][0]["step"] == 1
    assert isinstance(payload["steps"][0]["ledger_total_usd"], float)
    assert all("shock_id" in s for s in payload["shocks"])


def test_market_paths_json_has_real_percentiles(app) -> None:
    status, headers, body = request_json(
        app, "/dashboard/market-paths", ALICE, "sigma=0.4&n_paths=500"
    )
    assert status == 200
    payload = json.loads(body)
    assert payload["p5"] <= payload["p50"] <= payload["p95"]
    assert payload["n_paths"] == 500


def test_pricing_json_has_real_black_scholes_values(app) -> None:
    status, headers, body = request_json(
        app, "/dashboard/pricing", ALICE, "strike=105&maturity=0.5"
    )
    assert status == 200
    payload = json.loads(body)
    assert payload["pricing_method"] == "Black-Scholes closed-form"
    assert payload["price"] > 0
    assert "delta" in payload and "gamma" in payload


def test_hedge_actions_json_has_real_ratio_series(app) -> None:
    status, headers, body = request_json(
        app, "/dashboard/hedge-actions", ALICE, "n_steps=5&n_paths=50"
    )
    assert status == 200
    payload = json.loads(body)
    assert len(payload["ratios_path_0"]) == 5


def test_portfolio_risk_json_has_real_var_and_es(app) -> None:
    status, headers, body = request_json(app, "/dashboard/portfolio-risk", ALICE, "alpha=0.99")
    assert status == 200
    payload = json.loads(body)
    assert payload["alpha"] == 0.99
    assert isinstance(payload["var"], float)
    assert isinstance(payload["es"], float)


def test_audit_trail_json_has_real_transition_history(app) -> None:
    status, headers, body = request_json(app, "/dashboard/audit-trail", ALICE)
    assert status == 200
    payload = json.loads(body)
    assert payload["model_id"] == "recessionnet-hybrid-quantum-v1"
    to_states = [t["to_state"] for t in payload["history"]]
    assert "evaluated" in to_states
    assert "approved" in to_states


def test_model_usage_json_authorized_for_a_real_known_model(app) -> None:
    status, headers, body = request_json(
        app, "/dashboard/model-usage", ALICE, "model_id=recessionnet&application=research"
    )
    assert status == 200
    payload = json.loads(body)
    assert payload["authorized"] is True
    assert "research" in payload["authorized_applications"]


def test_model_usage_json_rejects_unauthorized_application(app) -> None:
    status, headers, body = request_json(
        app, "/dashboard/model-usage", ALICE, "model_id=recessionnet&application=live_trading"
    )
    assert status == 403
    assert headers["content-type"].startswith("application/json")
    payload = json.loads(body)
    assert "not authorized" in payload["error"].lower()


def test_validation_issues_json_lists_real_tracked_findings(app) -> None:
    status, headers, body = request_json(app, "/dashboard/validation-issues", ALICE)
    assert status == 200
    payload = json.loads(body)
    finding_ids = {f["finding_id"] for f in payload["findings"]}
    assert "VAL-2026-001" in finding_ids


def test_experiments_json_includes_every_real_comparison_row(app) -> None:
    status, headers, body = request_json(app, "/dashboard/experiments", ALICE)
    assert status == 200
    payload = json.loads(body)
    assert payload["provenance"] == "real"
    verdicts = [r["verdict"] for r in payload["rows"]]
    assert any("NOT SIGNIFICANT" in v for v in verdicts)


def test_inflationcast_json_has_every_real_candidate(app) -> None:
    status, headers, body = request_json(
        app, "/dashboard/inflationcast", ALICE,
        "max_epochs=10&patience=3&bootstrap_resamples=20",
    )
    assert status == 200
    payload = json.loads(body)
    assert set(payload["models"]) == {
        "naive_persistence", "linear_regression", "classical_matched_mlp",
        "hybrid_quantum", "gru",
    }
    assert "gru_calibration" in payload


def test_owner_can_view_their_own_portfolio_as_json(app) -> None:
    status, headers, body = request_json(app, "/dashboard/portfolio/alice", ALICE)
    assert status == 200
    payload = json.loads(body)
    assert payload["sector"] == "household"
    account_ids = {e["account_id"] for e in payload["entries"]}
    assert any("alice-hh" in a for a in account_ids)


def test_a_different_owner_is_refused_json_access_to_alices_portfolio(app) -> None:
    status, headers, body = request_json(app, "/dashboard/portfolio/alice", BOB)
    assert status == 403
    assert headers["content-type"].startswith("application/json")


def test_json_request_with_no_token_still_gets_a_real_401(app) -> None:
    status, headers, body = request_json(app, "/dashboard/experiments", None)
    assert status == 401
    assert headers["content-type"].startswith("application/json")
    payload = json.loads(body)
    assert "error" in payload


def test_html_mode_is_still_the_default_with_no_format_param(app) -> None:
    """The existing HTML behavior must be completely unaffected -- this
    is the same request shape every pre-existing dashboard test uses."""
    status, headers, body = asyncio.run(_request_async(app, "/dashboard/experiments", ALICE))
    assert status == 200
    assert headers["content-type"].startswith("text/html")
    assert "<table>" in body
