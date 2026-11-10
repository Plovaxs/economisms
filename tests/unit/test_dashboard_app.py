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


async def _request_async(app, path, token):
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
            "query_string": b"",
            "headers": headers,
        },
        receive,
        send,
    )
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(m["body"] for m in sent if m["type"] == "http.response.body")
    return start["status"], body.decode("utf-8")


def request(app, path, token):
    return asyncio.run(_request_async(app, path, token))


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
    import asyncio as _asyncio

    async def _go():
        sent = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent.append(message)

        await app(
            {
                "type": "http",
                "method": "GET",
                "path": "/dashboard/pricing",
                "query_string": b"strike=105&maturity=0.5",
                "headers": [
                    (b"host", b"localhost"),
                    (b"authorization", ("Bearer " + ALICE).encode()),
                ],
            },
            receive,
            send,
        )
        start = next(m for m in sent if m["type"] == "http.response.start")
        return start["status"]

    status = _asyncio.run(_go())
    assert status == 200


def test_unknown_path_is_404(app) -> None:
    status, _ = request(app, "/dashboard/does-not-exist", ALICE)
    assert status == 404
