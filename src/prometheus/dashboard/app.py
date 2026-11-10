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
from prometheus.dashboard.audit_trail import render_audit_trail
from prometheus.dashboard.auth import (
    PortfolioShareRegistry,
    UnauthorizedPortfolioAccessError,
    require_portfolio_access,
)
from prometheus.dashboard.experiment_comparison import render_experiment_comparison
from prometheus.dashboard.export import build_export, render_printable_html
from prometheus.dashboard.html import page
from prometheus.dashboard.views import (
    render_balance_sheets,
    render_economy_explorer,
    render_hedge_actions,
    render_market_paths,
    render_portfolio_risk,
    render_pricing_diagnostics,
)
from prometheus.evidence.model_inventory import UnauthorizedModelUsageError, authorize_model_usage
from prometheus.evidence.model_registry import ModelRegistryEntry
from prometheus.evidence.validation_issue_tracker import REAL_FINDINGS
from prometheus.service.auth import AuthenticationError, CredentialStore

_INDEX_LINKS: tuple[tuple[str, str], ...] = (
    ("/dashboard/economy", "Economic simulation explorer (UIX-01)"),
    ("/dashboard/market-paths", "Market paths and uncertainty (UIX-03)"),
    ("/dashboard/pricing", "Derivative pricing diagnostics and Greeks (UIX-04)"),
    ("/dashboard/hedge-actions", "Hedge actions and timing (UIX-05)"),
    ("/dashboard/portfolio-risk", "Portfolio VaR/ES and drawdown (UIX-06)"),
    ("/dashboard/experiments", "Experiment comparison, with real losses (UIX-07)"),
    ("/dashboard/audit-trail", "Model registry audit trail (UIX-09)"),
    ("/dashboard/portfolio/alice", "A real owner-scoped portfolio (UIX-02/UIX-10)"),
    (
        "/dashboard/model-usage?model_id=recessionnet&application=research",
        "Model usage authorization check (MGR-11)",
    ),
    ("/dashboard/validation-issues", "Validation issue tracker (MGR-10)"),
)


def _demo_audit_entry() -> ModelRegistryEntry:
    """A REALISTIC entry built via the registry's own real `transition`
    calls (not hand-typed `StateTransition` objects) -- see
    `dashboard.audit_trail`'s own docstring for why this is disclosed
    as a realistic demonstration, not a real production promotion."""
    from datetime import date

    entry = ModelRegistryEntry("recessionnet-hybrid-quantum-v1")
    entry.transition(
        "evaluated", "ci", date(2026, 1, 1), "offline backtest completed", approved_by="n/a"
    )
    entry.transition(
        "approved", "reviewer", date(2026, 1, 2), "passed validation",
        approved_by="reviewer", content_hash="a" * 64,
    )
    return entry

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
        if scope["type"] == "lifespan":
            # Real ASGI servers (uvicorn) send a lifespan scope before any
            # HTTP request to probe startup/shutdown -- discovered by
            # actually running this app under uvicorn, not just by unit
            # tests that construct an "http" scope directly (see
            # service.application.ResearchService's identical handling,
            # reused here rather than invented a second way).
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return
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

        if path in ("/dashboard", "/dashboard/"):
            items = "".join(
                f'<li><a href="{href}">{label}</a></li>' for href, label in _INDEX_LINKS
            )
            return 200, page("Dashboard", "ECONOSIM research dashboard", f"<ul>{items}</ul>")

        if path == "/dashboard/experiments":
            return 200, render_experiment_comparison()

        if path == "/dashboard/economy":
            n_steps = int(query.get("n_steps", ["6"])[0])
            seed = int(query.get("seed", ["0"])[0])
            return 200, render_economy_explorer(n_steps=n_steps, seed=seed)

        if path == "/dashboard/market-paths":
            return 200, render_market_paths(
                s0=float(query.get("s0", ["100"])[0]),
                mu=float(query.get("mu", ["0.05"])[0]),
                sigma=float(query.get("sigma", ["0.2"])[0]),
                maturity=float(query.get("maturity", ["1.0"])[0]),
                n_steps=int(query.get("n_steps", ["50"])[0]),
                n_paths=int(query.get("n_paths", ["2000"])[0]),
                seed=int(query.get("seed", ["0"])[0]),
            )

        if path == "/dashboard/hedge-actions":
            return 200, render_hedge_actions(
                s0=float(query.get("s0", ["100"])[0]),
                mu=float(query.get("mu", ["0.05"])[0]),
                sigma=float(query.get("sigma", ["0.2"])[0]),
                strike=float(query.get("strike", ["100"])[0]),
                maturity=float(query.get("maturity", ["1.0"])[0]),
                risk_free_rate=float(query.get("rate", ["0.03"])[0]),
                n_steps=int(query.get("n_steps", ["20"])[0]),
                n_paths=int(query.get("n_paths", ["200"])[0]),
                seed=int(query.get("seed", ["0"])[0]),
            )

        if path == "/dashboard/portfolio-risk":
            import numpy as np

            seed = int(query.get("seed", ["0"])[0])
            n = int(query.get("n", ["250"])[0])
            pnl = np.random.default_rng(seed).normal(loc=0.0, scale=1000.0, size=n)
            return 200, render_portfolio_risk(
                pnl, alpha=float(query.get("alpha", ["0.95"])[0]), horizon_label="1-day"
            )

        if path == "/dashboard/audit-trail":
            return 200, render_audit_trail(_demo_audit_entry())

        if path == "/dashboard/model-usage":
            model_id = query.get("model_id", [""])[0]
            application = query.get("application", [""])[0]
            try:
                entry = authorize_model_usage(model_id, application)
            except UnauthorizedModelUsageError as exc:
                raise DashboardHTTPError(403, str(exc)) from exc
            body = (
                f"<p>Model <code>{model_id}</code> is authorized for "
                f"<code>{application}</code>.</p>"
                f"<p>Authorized applications: "
                f"<code>{', '.join(entry.authorized_applications)}</code></p>"
            )
            return 200, page(
                "Model usage authorization", "Model usage authorization (MGR-11)", body
            )

        if path == "/dashboard/validation-issues":
            rows = "".join(
                f"<tr><td>{f.finding_id}</td><td>{f.component_id}</td>"
                f"<td>{f.severity}</td><td>{f.owner}</td><td>{f.expiry_date}</td>"
                f"<td>{f.disposition}</td></tr>"
                for f in REAL_FINDINGS
            )
            body = (
                "<table><thead><tr><th>ID</th><th>Component</th><th>Severity</th>"
                "<th>Owner</th><th>Expiry</th><th>Disposition</th></tr></thead>"
                f"<tbody>{rows}</tbody></table>"
            )
            return 200, page(
                "Validation issue tracker", "Validation issue tracker (MGR-10)", body
            )

        if path == "/dashboard/export":
            view_name = query.get("view", [""])[0]
            exportable: dict[str, tuple[str, Callable[[], str]]] = {
                "experiments": ("Experiment comparison", render_experiment_comparison),
                "audit-trail": (
                    "Audit trail", lambda: render_audit_trail(_demo_audit_entry())
                ),
            }
            if view_name not in exportable:
                raise DashboardHTTPError(
                    404, f"no exportable view named {view_name!r}; try one of "
                    f"{sorted(exportable)}"
                )
            method_summary, render = exportable[view_name]
            export = build_export(view_name, method_summary, render())
            return 200, render_printable_html(export)

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
