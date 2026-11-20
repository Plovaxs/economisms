"""The dashboard's views, as the desktop's "Explorers": quick, deterministic, no queue.

Each explorer is the same real computation the web dashboard serves (`dashboard.views`:
`economy_explorer_as_json`, `market_paths_as_json`, ...), called directly. Where the web view
returns a few summary numbers, an explorer adds the curve a person actually wants to look at (the
percentile fan of the simulated paths, the option value against the spot) computed from the *same*
seeded simulation, so the headline numbers and the picture can never disagree -- a test asserts
that they do not.

Parameter bounds are the dashboard's own (`dashboard.app`'s `_PRICE`, `_VOLATILITY`, ... and its
two cell limits), copied here as numbers and pinned to the originals by a test, so an explorer can
never be asked for an allocation the web view would have refused.

Importing this module is cheap: it imports neither numpy nor torch. The computations import what
they need when they run, and they run in a child process (`compute_child`), never in the window's
own process.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from prometheus.desktop.forms import FieldSpec, Path, assemble

SEED_MAX = 2**32 - 1
MAX_MARKET_PATH_CELLS = 2_000_000
MAX_HEDGE_CELLS = 500_000
HISTOGRAM_BINS = 40
MAX_SERIES_POINTS = 2_000


def _number(
    key: str,
    label: str,
    default: float,
    minimum: float,
    maximum: float,
    *,
    integer: bool = False,
    exclusive_minimum: bool = False,
) -> FieldSpec:
    return FieldSpec(
        key=key,
        path=(key,),
        label=label,
        kind="int" if integer else "float",
        default=default,
        minimum=minimum,
        maximum=maximum,
        exclusive_minimum=exclusive_minimum,
    )


def _seed() -> FieldSpec:
    return _number("seed", "Seed", 0, 0, SEED_MAX, integer=True)


def _price(key: str, label: str, default: float = 100.0) -> FieldSpec:
    return _number(key, label, default, 0.0, 1e7, exclusive_minimum=True)


def _maturity(label: str = "Maturity (years)") -> FieldSpec:
    return _number("maturity", label, 1.0, 0.01, 50.0)


def _volatility(key: str = "sigma", label: str = "Volatility (annual)") -> FieldSpec:
    return _number(key, label, 0.2, 0.001, 5.0)


def _drift() -> FieldSpec:
    return _number("mu", "Drift (annual)", 0.05, -1.0, 1.0)


def _rate(key: str = "rate") -> FieldSpec:
    return _number(key, "Risk-free rate", 0.03, -0.5, 1.0)


def _option_type() -> FieldSpec:
    return FieldSpec(
        key="option_type",
        path=("option_type",),
        label="Option type",
        kind="choice",
        default="call",
        choices=("call", "put"),
    )


def _cell_limit(first: str, second: str, limit: int) -> Callable[[Mapping[str, Any]], str | None]:
    def check(params: Mapping[str, Any]) -> str | None:
        if params[first] * params[second] > limit:
            return (
                f"{first.replace('_', ' ')} × {second.replace('_', ' ')} must not exceed {limit:,}"
            )
        return None

    return check


@dataclass(frozen=True, slots=True)
class Explorer:
    name: str
    title: str
    summary: str
    fields: tuple[FieldSpec, ...] = ()
    cross_check: Callable[[Mapping[str, Any]], str | None] | None = None
    """A limit that involves two parameters at once, where a per-field range cannot say it."""


EXPLORERS: tuple[Explorer, ...] = (
    Explorer(
        "economy",
        "Economy",
        "A real household-and-firm economy stepped forward with posted ledger transactions and "
        "drawn macro shocks: the aggregate ledger balance after each step, and the shocks.",
        (_number("n_steps", "Steps (months)", 6, 1, 120, integer=True), _seed()),
    ),
    Explorer(
        "market_paths",
        "Market paths",
        "Simulated geometric-Brownian-motion price paths (synthetic, clearly labelled) and the "
        "5th / 50th / 95th percentile fan they trace.",
        (
            _price("s0", "Starting price"),
            _drift(),
            _volatility(),
            _maturity("Horizon (years)"),
            _number("n_steps", "Time steps", 50, 1, 365, integer=True),
            _number("n_paths", "Paths", 2000, 1, 20_000, integer=True),
            _seed(),
        ),
        _cell_limit("n_steps", "n_paths", MAX_MARKET_PATH_CELLS),
    ),
    Explorer(
        "pricing",
        "Option pricing",
        "The closed-form Black–Scholes price and Greeks of a European option, and its value and "
        "delta across a range of spot prices.",
        (
            _price("spot", "Spot price"),
            _price("strike", "Strike"),
            _maturity(),
            _volatility("volatility", "Volatility (annual)"),
            _rate(),
            _option_type(),
        ),
    ),
    Explorer(
        "hedge_actions",
        "Hedge ratios",
        "The Black–Scholes delta-hedge ratio at each step along one simulated price path.",
        (
            _price("s0", "Starting price"),
            _drift(),
            _volatility(),
            _price("strike", "Strike"),
            _maturity(),
            _rate("risk_free_rate"),
            _number("n_steps", "Hedge steps", 20, 1, 250, integer=True),
            _number("n_paths", "Paths", 200, 1, 5000, integer=True),
            _seed(),
        ),
        _cell_limit("n_steps", "n_paths", MAX_HEDGE_CELLS),
    ),
    Explorer(
        "portfolio_risk",
        "Portfolio risk",
        "Historical value-at-risk, expected shortfall and maximum drawdown of a simulated P&L "
        "series, with its loss distribution.",
        (
            _seed(),
            _number("n", "Observations", 250, 10, 100_000, integer=True),
            _number("alpha", "Confidence level", 0.95, 0.5, 0.9999),
        ),
    ),
    Explorer(
        "experiments",
        "Experiment comparison",
        "The recorded head-to-head experiments: champion, challenger and the metric each was "
        "judged on, as written in docs/RESULTS_AND_LIMITATIONS.md.",
    ),
    Explorer(
        "validation_issues",
        "Validation issues",
        "The independent-validation findings this repository has recorded against its own "
        "code, with severity, owner and disposition.",
    ),
)

_BY_NAME = {explorer.name: explorer for explorer in EXPLORERS}


def explorer(name: str) -> Explorer:
    return _BY_NAME[name]


def validate(name: str, values: Mapping[Path, Any]) -> tuple[dict[str, Any], dict[Path, str]]:
    """Parse and range-check editor values for explorer `name`. Returns `(params, errors)`;
    `errors` is keyed by field path, with `()` for a problem involving several fields."""
    chosen = explorer(name)
    params, errors = assemble(chosen.fields, values)
    if not errors and chosen.cross_check is not None:
        problem = chosen.cross_check(params)
        if problem is not None:
            errors[()] = problem
    return params, errors


def defaults(name: str) -> dict[Path, Any]:
    return {spec.path: spec.default for spec in explorer(name).fields}


# ---------------------------------------------------------------------------------- computing
# Everything below runs in the child process. Imports are local so that merely importing this
# module (the window does, to build its forms) never loads numpy or torch.


def _compute_economy(params: Mapping[str, Any]) -> dict[str, Any]:
    from prometheus.dashboard.views import economy_explorer_as_json

    return economy_explorer_as_json(n_steps=params["n_steps"], seed=params["seed"])


def _compute_market_paths(params: Mapping[str, Any]) -> dict[str, Any]:
    import numpy as np

    from prometheus.dashboard.views import market_paths_as_json
    from prometheus.stochastica.gbm import simulate_gbm_paths

    summary = market_paths_as_json(**params)
    rng = np.random.default_rng(params["seed"])  # the same stream the summary was drawn from
    paths = simulate_gbm_paths(
        params["s0"],
        params["mu"],
        params["sigma"],
        params["maturity"],
        params["n_steps"],
        params["n_paths"],
        rng,
    )
    lower, median, upper = np.percentile(paths, [5, 50, 95], axis=0)
    years = np.linspace(0.0, params["maturity"], paths.shape[1])
    summary["fan"] = {
        "x_label": "Time (years)",
        "x": years.tolist(),
        "5th percentile": lower.tolist(),
        "Median": median.tolist(),
        "95th percentile": upper.tolist(),
        "band": ["5th percentile", "95th percentile"],
    }
    return summary


def _compute_pricing(params: Mapping[str, Any]) -> dict[str, Any]:
    from datetime import date

    from prometheus.dashboard.views import pricing_diagnostics_as_json
    from prometheus.volterra.black_scholes import black_scholes_greeks, black_scholes_price
    from prometheus.volterra.instruments import EuropeanOption
    from prometheus.volterra.market import MarketSnapshot

    today = date.today()
    option = EuropeanOption(
        strike=params["strike"], maturity=params["maturity"], option_type=params["option_type"]
    )
    market = MarketSnapshot(
        as_of=today,
        spot=params["spot"],
        risk_free_rate=params["rate"],
        volatility=params["volatility"],
    )
    summary = pricing_diagnostics_as_json(market, option)
    spots = [params["strike"] * (0.5 + step / 40) for step in range(41)]
    values: list[float] = []
    deltas: list[float] = []
    payoffs: list[float] = []
    for spot in spots:
        at = MarketSnapshot(
            as_of=today,
            spot=spot,
            risk_free_rate=params["rate"],
            volatility=params["volatility"],
        )
        values.append(black_scholes_price(at, option))
        deltas.append(black_scholes_greeks(at, option).delta)
        intrinsic = (
            spot - params["strike"] if params["option_type"] == "call" else params["strike"] - spot
        )
        payoffs.append(max(0.0, intrinsic))
    summary["value_curve"] = {
        "x_label": "Spot price",
        "x": spots,
        "Option value": values,
        "Payoff at expiry": payoffs,
    }
    summary["delta_curve"] = {"x_label": "Spot price", "x": spots, "Delta": deltas}
    return summary


def _compute_hedge_actions(params: Mapping[str, Any]) -> dict[str, Any]:
    from prometheus.dashboard.views import hedge_actions_as_json

    return hedge_actions_as_json(**params)


def _compute_portfolio_risk(params: Mapping[str, Any]) -> dict[str, Any]:
    import numpy as np

    from prometheus.dashboard.views import portfolio_risk_as_json

    pnl = np.random.default_rng(params["seed"]).normal(loc=0.0, scale=1000.0, size=params["n"])
    summary = portfolio_risk_as_json(pnl, alpha=params["alpha"], horizon_label="1-day")
    counts, edges = np.histogram(-pnl, bins=HISTOGRAM_BINS)
    summary["loss_histogram"] = {
        "x_label": "Loss",
        "x": ((edges[:-1] + edges[1:]) / 2).tolist(),
        "Observations": counts.tolist(),
    }
    cumulative = np.cumsum(pnl)
    stride = max(1, len(cumulative) // MAX_SERIES_POINTS)
    summary["cumulative_pnl"] = cumulative[::stride].tolist()
    return summary


def _compute_experiments(_: Mapping[str, Any]) -> dict[str, Any]:
    from prometheus.dashboard.experiment_comparison import experiment_comparison_as_json

    return experiment_comparison_as_json()


def _compute_validation_issues(_: Mapping[str, Any]) -> dict[str, Any]:
    from prometheus.evidence.validation_issue_tracker import REAL_FINDINGS

    return {
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


_COMPUTE: dict[str, Callable[[Mapping[str, Any]], dict[str, Any]]] = {
    "economy": _compute_economy,
    "market_paths": _compute_market_paths,
    "pricing": _compute_pricing,
    "hedge_actions": _compute_hedge_actions,
    "portfolio_risk": _compute_portfolio_risk,
    "experiments": _compute_experiments,
    "validation_issues": _compute_validation_issues,
}


def compute(name: str, params: Mapping[str, Any]) -> dict[str, Any]:
    """Run explorer `name` on already-validated `params` (see `validate`)."""
    return _COMPUTE[name](params)
