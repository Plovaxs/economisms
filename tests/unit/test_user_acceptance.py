from __future__ import annotations

import asyncio
import hashlib
import json

import pytest

from prometheus.core.ledger import Ledger
from prometheus.core.money import Money
from prometheus.dashboard.app import DashboardService
from prometheus.econosim.agents import Household
from prometheus.evidence.user_acceptance import (
    REAL_UAT_CASES,
    REQUIRED_PERSONAS,
    UATCase,
    UserAcceptanceRunError,
    verify_user_acceptance_run,
)
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
    sent: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    headers = [(b"host", b"localhost")]
    if token is not None:
        headers.append((b"authorization", ("Bearer " + token).encode()))
    await app(
        {
            "type": "http", "method": "GET", "path": path,
            "query_string": query.encode("ascii"), "headers": headers,
        },
        receive, send,
    )
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(m["body"] for m in sent if m["type"] == "http.response.body")
    return start["status"], body.decode("utf-8")


def request(app, path, token, query=""):
    return asyncio.run(_request_async(app, path, token, query))


def test_every_real_uat_case_is_recorded_as_passed() -> None:
    """LCH-09's own acceptance wording: "documented cases with
    approved pass/fail evidence" -- checked directly against the
    real, recorded run rather than asserted in prose."""
    assert len(REAL_UAT_CASES) >= 9
    for case in REAL_UAT_CASES:
        assert case.passed
        assert case.actual_status == case.expected_status


def test_both_named_personas_were_actually_exercised() -> None:
    covered = {c.persona for c in REAL_UAT_CASES}
    assert covered == set(REQUIRED_PERSONAS)


def test_verify_user_acceptance_run_passes_on_the_real_run() -> None:
    verify_user_acceptance_run()  # must not raise


def test_verify_user_acceptance_run_rejects_a_failed_case() -> None:
    failing = (
        UATCase(
            "bad-case", "analyst", "d", expected_status=200, actual_status=500, passed=False
        ),
    )
    with pytest.raises(UserAcceptanceRunError, match="bad-case"):
        verify_user_acceptance_run(failing)


def test_verify_user_acceptance_run_rejects_a_run_missing_a_persona() -> None:
    analyst_only = tuple(c for c in REAL_UAT_CASES if c.persona == "analyst")
    with pytest.raises(UserAcceptanceRunError, match="reviewer"):
        verify_user_acceptance_run(analyst_only)


def test_regression_the_9_real_uat_scenarios_still_pass_today(app) -> None:
    """The live run recorded in `evidence.user_acceptance` was executed
    once, by hand, against a real `uvicorn` process -- this regression
    test re-exercises the identical 9 scenarios through the same
    in-process ASGI harness every other dashboard test in this
    repository uses, so a future regression in any of these routes is
    caught on every CI run, not just the one dated manual run."""
    status, body = request(app, "/dashboard/economy", ALICE, "n_steps=3&seed=1")
    assert status == 200 and "SYNTHETIC" in body

    status, body = request(app, "/dashboard/pricing", ALICE, "strike=105&maturity=0.5")
    assert status == 200 and "Black-Scholes" in body

    status, body = request(app, "/dashboard/experiments", ALICE)
    assert status == 200 and "NOT SIGNIFICANT" in body

    status, body = request(app, "/dashboard/portfolio-risk", ALICE, "alpha=0.99")
    assert status == 200 and "Historical VaR" in body

    status, body = request(app, "/dashboard/audit-trail", ALICE)
    assert status == 200 and "approved" in body

    status, body = request(app, "/dashboard/validation-issues", ALICE)
    assert status == 200 and "remediated" in body.lower()

    status, body = request(
        app, "/dashboard/model-usage", ALICE, "model_id=recessionnet&application=research"
    )
    assert status == 200 and "authorized" in body.lower()

    status, body = request(
        app, "/dashboard/model-usage", ALICE, "model_id=recessionnet&application=live_trading"
    )
    assert status == 403 and "not authorized" in body.lower()

    status, _ = request(app, "/dashboard/portfolio/alice", BOB)
    assert status == 403
