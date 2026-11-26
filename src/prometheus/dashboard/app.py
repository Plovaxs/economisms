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

import asyncio
import json
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from prometheus.core.ledger import Ledger, Sector
from prometheus.dashboard.audit_trail import audit_trail_as_json, render_audit_trail
from prometheus.dashboard.auth import (
    PortfolioShareRegistry,
    UnauthorizedPortfolioAccessError,
    require_portfolio_access,
)
from prometheus.dashboard.experiment_comparison import (
    experiment_comparison_as_json,
    render_experiment_comparison,
)
from prometheus.dashboard.export import build_export, render_printable_html
from prometheus.dashboard.html import escape, page
from prometheus.dashboard.inflationcast_view import inflationcast_as_json, render_inflationcast
from prometheus.dashboard.params import (
    SEED_RANGE,
    FloatRange,
    ParamError,
    float_param,
    int_param,
    parse_query,
    token_param,
    wants_json,
)
from prometheus.dashboard.transmission_view import render_transmission, transmission_as_json
from prometheus.dashboard.views import (
    balance_sheets_as_json,
    economy_explorer_as_json,
    hedge_actions_as_json,
    market_paths_as_json,
    portfolio_risk_as_json,
    pricing_diagnostics_as_json,
    render_balance_sheets,
    render_economy_explorer,
    render_hedge_actions,
    render_market_paths,
    render_portfolio_risk,
    render_pricing_diagnostics,
)
from prometheus.dashboard.worldsim_view import render_worldsim, worldsim_as_json
from prometheus.evidence.model_inventory import UnauthorizedModelUsageError, authorize_model_usage
from prometheus.evidence.model_registry import ModelRegistryEntry
from prometheus.evidence.validation_issue_tracker import REAL_FINDINGS
from prometheus.experiments.manifest import json_default
from prometheus.httpsec.concurrency import BoundedExecutor, Overloaded
from prometheus.httpsec.headers import API_CSP, NO_STORE_CACHE, finalize_headers
from prometheus.httpsec.ratelimit import TokenBucketLimiter
from prometheus.service.auth import (
    AuthenticationError,
    CredentialStore,
    CredentialUnavailable,
    Principal,
)

_JSON_CONTENT_TYPE = "application/json"
_HTML_CONTENT_TYPE = "text/html; charset=utf-8"


def _json_body(payload: Any) -> str:
    return json.dumps(payload, default=json_default)


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
    (
        "/dashboard/inflationcast",
        "INFLATIONCAST: CPI nowcasting -- classical vs. deep learning vs. hybrid quantum (FP-07)",
    ),
    (
        "/dashboard/worldsim",
        "WORLDSIM: a volatile simulated economy with households, assets, banks and monitoring",
    ),
    (
        "/dashboard/transmission",
        "WORLDSIM shock transmission map: where a shock enters and which links carry it",
    ),
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
        "approved",
        "reviewer",
        date(2026, 1, 2),
        "passed validation",
        approved_by="reviewer",
        content_hash="a" * 64,
    )
    return entry


LOGGER = logging.getLogger("prometheus.dashboard.audit")
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]

# The server-rendered HTML pages carry inline <style> and style attributes but
# no script, form or external resource, so the policy forbids all of those and
# permits only inline styles: an injected <script> or event handler is dead on
# arrival, and injected CSS has nowhere to send anything.
HTML_CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; img-src data:; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
_OWNER = re.compile(r"[A-Za-z0-9._:@-]{1,128}")
_MAX_PATH = 2048
_PRICE = FloatRange(0.0, 1e7, lo_open=True)
_MATURITY = FloatRange(0.01, 50.0)
_VOLATILITY = FloatRange(0.001, 5.0)
_RATE = FloatRange(-0.5, 1.0)
_DRIFT = FloatRange(-1.0, 1.0)
_ALPHA = FloatRange(0.5, 0.9999)
_SHOCK_SIZE = FloatRange(-1.0, 10.0)
_MAX_MARKET_PATH_CELLS = 2_000_000
_MAX_HEDGE_CELLS = 500_000


@dataclass(frozen=True, slots=True)
class DashboardPolicy:
    max_inflight: int = 4
    requests_per_second: float = 10.0
    burst: int = 60
    max_headers: int = 64
    max_header_bytes: int = 16_384

    def __post_init__(self) -> None:
        for name in ("max_inflight", "burst", "max_headers", "max_header_bytes"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f"{name} must be a positive integer")
        if not 0 < self.requests_per_second <= 10_000:
            raise ValueError("requests_per_second must be in (0,10000]")


class DashboardHTTPError(ValueError):
    def __init__(
        self, status: int, message: str, *, headers: tuple[tuple[bytes, bytes], ...] = ()
    ) -> None:
        self.status, self.message, self.headers = status, message, headers


def _error_body(message: str, want_json: bool) -> tuple[str, str]:
    if want_json:
        return _json_body({"error": message}), _JSON_CONTENT_TYPE
    # `message` can carry caller-supplied text (an unknown model id, a view
    # name): it is escaped here, at the one place every error page passes.
    return page("Error", "Error", f"<p>{escape(message)}</p>"), _HTML_CONTENT_TYPE


class DashboardService:
    def __init__(
        self,
        credentials: CredentialStore,
        portfolios: dict[str, Ledger],
        shares: PortfolioShareRegistry | None = None,
        *,
        policy: DashboardPolicy | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.credentials = credentials
        self.portfolios = portfolios
        self.shares = shares or PortfolioShareRegistry()
        self.policy = policy or DashboardPolicy()
        self.limiter = TokenBucketLimiter(
            rate_per_second=self.policy.requests_per_second,
            burst=self.policy.burst,
            clock=clock,
        )
        # The views compute (a model may train inside one request), so they run
        # in worker threads under a hard cap: on the event loop one request
        # would freeze every other, /health/live included.
        self.executor = BoundedExecutor(self.policy.max_inflight)

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
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] != "http":
            raise ValueError("this dashboard app serves HTTP only")
        request_id = uuid.uuid4().hex
        want_json = wants_json(scope.get("query_string", b""))
        context: dict[str, str | None] = {"subject": None}
        extra: tuple[tuple[bytes, bytes], ...] = ()
        try:
            status, body_str, content_type = await self._handle(scope, want_json, context)
        except DashboardHTTPError as exc:
            status, extra = exc.status, exc.headers
            body_str, content_type = _error_body(exc.message, want_json)
        except Exception:
            LOGGER.exception("unhandled dashboard failure request_id=%s", request_id)
            status = 500
            body_str, content_type = _error_body("unexpected dashboard failure", want_json)
        body = body_str.encode("utf-8")
        headers = [
            (b"content-type", content_type.encode("ascii")),
            (b"cache-control", NO_STORE_CACHE),
            (b"x-request-id", request_id.encode("ascii")),
            (b"content-length", str(len(body)).encode("ascii")),
            *extra,
        ]
        headers = finalize_headers(
            headers,
            https=scope.get("scheme") == "https",
            csp=HTML_CSP if content_type == _HTML_CONTENT_TYPE else API_CSP,
        )
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send(
            {
                "type": "http.response.body",
                "body": b"" if scope.get("method") == "HEAD" else body,
            }
        )
        LOGGER.info(
            json.dumps(
                {
                    "event": "dashboard_request",
                    "request_id": request_id,
                    "status": status,
                    "path": str(scope.get("path", ""))[:200],
                    "subject": context["subject"],
                },
                sort_keys=True,
            )
        )

    async def _handle(
        self, scope: dict[str, Any], want_json: bool, context: dict[str, str | None]
    ) -> tuple[int, str, str]:
        headers = self._request_headers(scope)
        path, method = scope["path"], scope["method"]
        if len(path) > _MAX_PATH:
            raise DashboardHTTPError(414, "request path exceeds the byte budget")
        if path == "/health/live":
            if method not in ("GET", "HEAD"):
                raise DashboardHTTPError(405, "only GET is supported")
            return 200, page("Health", "Health", "<p>live</p>"), _HTML_CONTENT_TYPE
        if method != "GET":
            raise DashboardHTTPError(405, "only GET is supported")
        try:
            query = parse_query(scope.get("query_string", b""))
        except ParamError as exc:
            raise DashboardHTTPError(exc.status, exc.message) from exc
        try:
            principal = await asyncio.to_thread(
                self.credentials.authenticate, headers.get("authorization")
            )
        except AuthenticationError as exc:
            raise DashboardHTTPError(
                401,
                "valid bearer credentials are required",
                headers=((b"www-authenticate", b"Bearer"),),
            ) from exc
        except CredentialUnavailable as exc:
            raise DashboardHTTPError(503, "service dependency is unavailable") from exc
        context["subject"] = principal.subject
        decision = self.limiter.acquire("owner:" + principal.owner)
        if not decision.allowed:
            raise DashboardHTTPError(
                429,
                "request rate budget is exhausted",
                headers=((b"retry-after", str(int(decision.retry_after_seconds) + 1).encode()),),
            )
        try:
            return await self.executor.run(self._dispatch, path, query, want_json, principal)
        except Overloaded as exc:
            raise DashboardHTTPError(
                503,
                "the dashboard is busy; retry shortly",
                headers=((b"retry-after", b"1"),),
            ) from exc
        except ParamError as exc:
            raise DashboardHTTPError(exc.status, exc.message) from exc

    def _request_headers(self, scope: dict[str, Any]) -> dict[str, str]:
        raw = scope.get("headers", [])
        if len(raw) > self.policy.max_headers or sum(len(k) + len(v) for k, v in raw) > (
            self.policy.max_header_bytes
        ):
            raise DashboardHTTPError(431, "request headers exceed budget")
        headers: dict[str, str] = {}
        for key, value in raw:
            try:
                name, text = key.decode("ascii").lower(), value.decode("ascii")
            except UnicodeDecodeError as exc:
                raise DashboardHTTPError(400, "headers must use ASCII") from exc
            if name == "authorization" and name in headers:
                raise DashboardHTTPError(400, "ambiguous duplicate authorization header")
            headers.setdefault(name, text)
        return headers

    def _dispatch(
        self, path: str, query: dict[str, list[str]], want_json: bool, principal: Principal
    ) -> tuple[int, str, str]:
        if path in ("/dashboard", "/dashboard/"):
            if want_json:
                return (
                    200,
                    _json_body({"links": [{"href": h, "label": lb} for h, lb in _INDEX_LINKS]}),
                    _JSON_CONTENT_TYPE,
                )
            items = "".join(
                f'<li><a href="{href}">{label}</a></li>' for href, label in _INDEX_LINKS
            )
            html = page("Dashboard", "ECONOSIM research dashboard", f"<ul>{items}</ul>")
            return 200, html, _HTML_CONTENT_TYPE

        if path == "/dashboard/experiments":
            if want_json:
                return 200, _json_body(experiment_comparison_as_json()), _JSON_CONTENT_TYPE
            return 200, render_experiment_comparison(), _HTML_CONTENT_TYPE

        if path == "/dashboard/economy":
            n_steps = int_param(query, "n_steps", 6, lo=1, hi=120)
            seed = int_param(query, "seed", 0, lo=SEED_RANGE[0], hi=SEED_RANGE[1])
            if want_json:
                payload = economy_explorer_as_json(n_steps=n_steps, seed=seed)
                return 200, _json_body(payload), _JSON_CONTENT_TYPE
            return 200, render_economy_explorer(n_steps=n_steps, seed=seed), _HTML_CONTENT_TYPE

        if path == "/dashboard/market-paths":
            market_path_kwargs: dict[str, Any] = dict(
                s0=float_param(query, "s0", 100.0, _PRICE),
                mu=float_param(query, "mu", 0.05, _DRIFT),
                sigma=float_param(query, "sigma", 0.2, _VOLATILITY),
                maturity=float_param(query, "maturity", 1.0, _MATURITY),
                n_steps=int_param(query, "n_steps", 50, lo=1, hi=365),
                n_paths=int_param(query, "n_paths", 2000, lo=1, hi=20_000),
                seed=int_param(query, "seed", 0, lo=SEED_RANGE[0], hi=SEED_RANGE[1]),
            )
            if market_path_kwargs["n_steps"] * market_path_kwargs["n_paths"] > (
                _MAX_MARKET_PATH_CELLS
            ):
                raise DashboardHTTPError(
                    400, f"n_steps * n_paths must not exceed {_MAX_MARKET_PATH_CELLS}"
                )
            if want_json:
                return (
                    200,
                    _json_body(market_paths_as_json(**market_path_kwargs)),
                    _JSON_CONTENT_TYPE,
                )
            return 200, render_market_paths(**market_path_kwargs), _HTML_CONTENT_TYPE

        if path == "/dashboard/hedge-actions":
            hedge_kwargs: dict[str, Any] = dict(
                s0=float_param(query, "s0", 100.0, _PRICE),
                mu=float_param(query, "mu", 0.05, _DRIFT),
                sigma=float_param(query, "sigma", 0.2, _VOLATILITY),
                strike=float_param(query, "strike", 100.0, _PRICE),
                maturity=float_param(query, "maturity", 1.0, _MATURITY),
                risk_free_rate=float_param(query, "rate", 0.03, _RATE),
                n_steps=int_param(query, "n_steps", 20, lo=1, hi=250),
                n_paths=int_param(query, "n_paths", 200, lo=1, hi=5_000),
                seed=int_param(query, "seed", 0, lo=SEED_RANGE[0], hi=SEED_RANGE[1]),
            )
            if hedge_kwargs["n_steps"] * hedge_kwargs["n_paths"] > _MAX_HEDGE_CELLS:
                raise DashboardHTTPError(
                    400, f"n_steps * n_paths must not exceed {_MAX_HEDGE_CELLS}"
                )
            if want_json:
                return 200, _json_body(hedge_actions_as_json(**hedge_kwargs)), _JSON_CONTENT_TYPE
            return 200, render_hedge_actions(**hedge_kwargs), _HTML_CONTENT_TYPE

        if path == "/dashboard/portfolio-risk":
            import numpy as np

            seed = int_param(query, "seed", 0, lo=SEED_RANGE[0], hi=SEED_RANGE[1])
            n = int_param(query, "n", 250, lo=10, hi=100_000)
            alpha = float_param(query, "alpha", 0.95, _ALPHA)
            pnl = np.random.default_rng(seed).normal(loc=0.0, scale=1000.0, size=n)
            if want_json:
                payload = portfolio_risk_as_json(pnl, alpha=alpha, horizon_label="1-day")
                return 200, _json_body(payload), _JSON_CONTENT_TYPE
            html = render_portfolio_risk(pnl, alpha=alpha, horizon_label="1-day")
            return 200, html, _HTML_CONTENT_TYPE

        if path == "/dashboard/audit-trail":
            if want_json:
                return 200, _json_body(audit_trail_as_json(_demo_audit_entry())), _JSON_CONTENT_TYPE
            return 200, render_audit_trail(_demo_audit_entry()), _HTML_CONTENT_TYPE

        if path == "/dashboard/model-usage":
            model_id = token_param(query, "model_id")
            application = token_param(query, "application")
            try:
                entry = authorize_model_usage(model_id, application)
            except UnauthorizedModelUsageError as exc:
                raise DashboardHTTPError(403, str(exc)) from exc
            if want_json:
                return (
                    200,
                    _json_body(
                        {
                            "model_id": model_id,
                            "requested_application": application,
                            "authorized": True,
                            "authorized_applications": list(entry.authorized_applications),
                        }
                    ),
                    _JSON_CONTENT_TYPE,
                )
            body = (
                f"<p>Model <code>{escape(model_id)}</code> is authorized for "
                f"<code>{escape(application)}</code>.</p>"
                f"<p>Authorized applications: "
                f"<code>{escape(', '.join(entry.authorized_applications))}</code></p>"
            )
            html = page("Model usage authorization", "Model usage authorization (MGR-11)", body)
            return 200, html, _HTML_CONTENT_TYPE

        if path == "/dashboard/inflationcast":
            inflationcast_kwargs = dict(
                seed=int_param(query, "seed", 0, lo=SEED_RANGE[0], hi=SEED_RANGE[1]),
                max_epochs=int_param(query, "max_epochs", 150, lo=1, hi=500),
                patience=int_param(query, "patience", 15, lo=1, hi=100),
                bootstrap_resamples=int_param(query, "bootstrap_resamples", 300, lo=10, hi=2_000),
            )
            if want_json:
                payload = inflationcast_as_json(**inflationcast_kwargs)
                return 200, _json_body(payload), _JSON_CONTENT_TYPE
            return 200, render_inflationcast(**inflationcast_kwargs), _HTML_CONTENT_TYPE

        if path == "/dashboard/worldsim":
            world_name = token_param(query, "scenario", "volatile")
            world_rule = token_param(query, "rule", "equal_weight")
            world_mode = token_param(query, "mode", "none")
            world_seed = int_param(query, "seed", 0, lo=SEED_RANGE[0], hi=SEED_RANGE[1])
            try:
                if want_json:
                    world_payload = worldsim_as_json(
                        name=world_name, seed=world_seed, rule=world_rule
                    )
                    return 200, _json_body(world_payload), _JSON_CONTENT_TYPE
                return (
                    200,
                    render_worldsim(
                        name=world_name, seed=world_seed, rule=world_rule, mode=world_mode
                    ),
                    _HTML_CONTENT_TYPE,
                )
            except ValueError as exc:
                raise DashboardHTTPError(400, str(exc)) from exc

        if path == "/dashboard/transmission":
            tm_name = token_param(query, "scenario", "stressed_connected")
            tm_shock = token_param(query, "shock", "equity_crash")
            tm_focus = token_param(query, "outcome", "output_gap")
            tm_mode = token_param(query, "mode", "none")
            tm_seeds = int_param(query, "seeds", 6, lo=3, hi=24)
            tm_size = float_param(query, "size", -1.0, _SHOCK_SIZE)
            tm_size_arg = None if tm_size < 0.0 else tm_size
            try:
                if want_json:
                    tm_payload = transmission_as_json(
                        name=tm_name,
                        shock=tm_shock,
                        size=tm_size_arg,
                        seeds=tm_seeds,
                        mode=tm_mode,
                    )
                    return 200, _json_body(tm_payload), _JSON_CONTENT_TYPE
                return (
                    200,
                    render_transmission(
                        name=tm_name,
                        shock=tm_shock,
                        size=tm_size_arg,
                        focus=tm_focus,
                        seeds=tm_seeds,
                        mode=tm_mode,
                    ),
                    _HTML_CONTENT_TYPE,
                )
            except ValueError as exc:
                raise DashboardHTTPError(400, str(exc)) from exc

        if path == "/dashboard/validation-issues":
            if want_json:
                payload = {
                    "findings": [
                        {
                            "finding_id": f.finding_id,
                            "component_id": f.component_id,
                            "severity": f.severity,
                            "owner": f.owner,
                            "expiry_date": f.expiry_date.isoformat(),
                            "disposition": f.disposition,
                        }
                        for f in REAL_FINDINGS
                    ]
                }
                return 200, _json_body(payload), _JSON_CONTENT_TYPE
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
            html = page("Validation issue tracker", "Validation issue tracker (MGR-10)", body)
            return 200, html, _HTML_CONTENT_TYPE

        if path == "/dashboard/export":
            view_name = token_param(query, "view")
            exportable: dict[str, tuple[str, Callable[[], str]]] = {
                "experiments": ("Experiment comparison", render_experiment_comparison),
                "audit-trail": ("Audit trail", lambda: render_audit_trail(_demo_audit_entry())),
                "inflationcast": ("INFLATIONCAST benchmark", lambda: render_inflationcast()),
            }
            if view_name not in exportable:
                raise DashboardHTTPError(
                    404, f"no exportable view named {view_name!r}; try one of {sorted(exportable)}"
                )
            method_summary, render = exportable[view_name]
            export = build_export(view_name, method_summary, render())
            return 200, render_printable_html(export), _HTML_CONTENT_TYPE

        if path == "/dashboard/pricing":
            from datetime import date

            from prometheus.volterra.instruments import EuropeanOption
            from prometheus.volterra.market import MarketSnapshot

            spot = float_param(query, "spot", 100.0, _PRICE)
            strike = float_param(query, "strike", 100.0, _PRICE)
            maturity = float_param(query, "maturity", 1.0, _MATURITY)
            volatility = float_param(query, "volatility", 0.2, _VOLATILITY)
            rate = float_param(query, "rate", 0.03, _RATE)
            market = MarketSnapshot(
                as_of=date.today(), spot=spot, risk_free_rate=rate, volatility=volatility
            )
            option = EuropeanOption(strike=strike, maturity=maturity, option_type="call")
            if want_json:
                payload = pricing_diagnostics_as_json(market, option)
                return 200, _json_body(payload), _JSON_CONTENT_TYPE
            return 200, render_pricing_diagnostics(market, option), _HTML_CONTENT_TYPE

        if path.startswith("/dashboard/portfolio/"):
            owner = path.removeprefix("/dashboard/portfolio/")
            if _OWNER.fullmatch(owner) is None:
                raise DashboardHTTPError(404, "portfolio not found")
            try:
                require_portfolio_access(principal, owner, self.shares)
            except UnauthorizedPortfolioAccessError as exc:
                raise DashboardHTTPError(403, str(exc)) from exc
            ledger = self.portfolios.get(owner)
            if ledger is None:
                raise DashboardHTTPError(404, "portfolio not found")
            if want_json:
                payload = balance_sheets_as_json(ledger, Sector.HOUSEHOLD)
                return 200, _json_body(payload), _JSON_CONTENT_TYPE
            return 200, render_balance_sheets(ledger, Sector.HOUSEHOLD), _HTML_CONTENT_TYPE

        raise DashboardHTTPError(404, "endpoint was not found")
