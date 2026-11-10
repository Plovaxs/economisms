"""A minimal, real ASGI dashboard service -- read-only GET views over
`prometheus.dashboard.views`/`experiment_comparison`, authenticated the
same way `service.application.ResearchService` already authenticates
its job API (`service.auth.CredentialStore`, identical bearer-token
convention), with `dashboard.auth.require_portfolio_access` enforcing
UIX-10 on the one route whose data is genuinely owner-scoped
(`/dashboard/portfolio/<owner>`).

A SEPARATE, parallel ASGI app from `service.application.ResearchService`
rather than new routes bolted onto it: `ResearchService` is a tightly
bounded, strictly-JSON job API (fixed content-type, strict body/header
budgets, a job-submission schema-validation pipeline) -- adding
HTML-rendering routes into that class would risk its own invariants for
no real benefit, when a second small app reusing the identical auth
primitive is just as honest and far lower-risk. Both apps can run as
separate ASGI processes/ports in a real deployment, the same way this
project's job API and worker are already separate processes.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import parse_qs

from prometheus.core.ledger import Ledger, Sector
from prometheus.dashboard.auth import (
    PortfolioShareRegistry,
    UnauthorizedPortfolioAccessError,
    require_portfolio_access,
)
from prometheus.dashboard.experiment_comparison import render_experiment_comparison
from prometheus.dashboard.html import page
from prometheus.dashboard.views import render_balance_sheets, render_pricing_diagnostics
from prometheus.service.auth import AuthenticationError, CredentialStore

LOGGER = logging.getLogger("prometheus.dashboard.audit")
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]


class DashboardHTTPError(ValueError):
    def __init__(self, status: int, message: str) -> None:
        self.status, self.message = status, message


class DashboardService:
    def __init__(
        self,
        credentials: CredentialStore,
        portfolios: dict[str, Ledger],
        shares: PortfolioShareRegistry | None = None,
    ) -> None:
        self.credentials = credentials
        self.portfolios = portfolios
        self.shares = shares or PortfolioShareRegistry()

    async def __call__(self, scope: dict[str, Any], receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            raise ValueError("this dashboard app serves HTTP only")
        request_id = uuid.uuid4().hex
        try:
            status, html = self._dispatch(scope)
        except DashboardHTTPError as exc:
            status, html = exc.status, page("Error", "Error", f"<p>{exc.message}</p>")
        body = html.encode("utf-8")
        headers = [
            (b"content-type", b"text/html; charset=utf-8"),
            (b"cache-control", b"no-store"),
            (b"x-content-type-options", b"nosniff"),
            (b"x-request-id", request_id.encode("ascii")),
            (b"content-length", str(len(body)).encode("ascii")),
        ]
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})

    def _dispatch(self, scope: dict[str, Any]) -> tuple[int, str]:
        path, method = scope["path"], scope["method"]
        if path == "/health/live":
            return 200, page("Health", "Health", "<p>live</p>")
        if method != "GET":
            raise DashboardHTTPError(405, "only GET is supported")
        raw_headers = scope.get("headers", [])
        headers = {k.decode("ascii").lower(): v.decode("ascii") for k, v in raw_headers}
        try:
            principal = self.credentials.authenticate(headers.get("authorization"))
        except AuthenticationError as exc:
            raise DashboardHTTPError(401, "valid bearer credentials are required") from exc

        query = parse_qs(scope.get("query_string", b"").decode("ascii"))

        if path == "/dashboard/experiments":
            return 200, render_experiment_comparison()

        if path == "/dashboard/pricing":
            from datetime import date

            from prometheus.volterra.instruments import EuropeanOption
            from prometheus.volterra.market import MarketSnapshot

            spot = float(query.get("spot", ["100"])[0])
            strike = float(query.get("strike", ["100"])[0])
            maturity = float(query.get("maturity", ["1.0"])[0])
            volatility = float(query.get("volatility", ["0.2"])[0])
            rate = float(query.get("rate", ["0.03"])[0])
            market = MarketSnapshot(
                as_of=date.today(), spot=spot, risk_free_rate=rate, volatility=volatility
            )
            option = EuropeanOption(strike=strike, maturity=maturity, option_type="call")
            return 200, render_pricing_diagnostics(market, option)

        if path.startswith("/dashboard/portfolio/"):
            owner = path.removeprefix("/dashboard/portfolio/")
            if not owner:
                raise DashboardHTTPError(404, "portfolio owner is required")
            try:
                require_portfolio_access(principal, owner, self.shares)
            except UnauthorizedPortfolioAccessError as exc:
                raise DashboardHTTPError(403, str(exc)) from exc
            ledger = self.portfolios.get(owner)
            if ledger is None:
                raise DashboardHTTPError(404, "portfolio not found")
            return 200, render_balance_sheets(ledger, Sector.HOUSEHOLD)

        raise DashboardHTTPError(404, "endpoint was not found")
