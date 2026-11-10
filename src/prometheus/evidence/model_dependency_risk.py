"""MGR-06: "Evaluate model dependency interactions and aggregated
model risk"; acceptance: "System-level error propagation analyzed, not
just local scores."

MGR-04's `model_validation_report` already aggregates each active
model's own LOCAL validation evidence (one record per model). MGR-06
goes one step further: it traces a REAL dependency already present in
this repository -- a desk that delta-hedges using the grid PDE
solver's Delta instead of the exact closed-form Delta feeds that
Delta directly into the shared self-financing hedge simulator used by
every policy in `hedging` (HDG-13) -- and actually RUNS that
substitution through the real simulator, rather than reporting the
Delta error in isolation the way `pde_solvers.benchmark.
greeks_error_report` (PDE-08) already does on its own.

`propagate_pde_delta_error_to_portfolio_es` hedges the SAME simulated
price paths twice with the shared `hedging.simulate.
simulate_self_financing_hedge` engine -- once with the exact
closed-form Delta, once with the grid solver's own Delta at the same
spot/strike -- and reports both the local score (the Delta error
itself) and the resulting shift in a downstream, AGGREGATE portfolio
risk statistic (`titan.risk_metrics.historical_expected_shortfall`).
A local Delta error that looked small in isolation can still move the
aggregate Expected Shortfall by a materially different amount once it
is carried through real path-dependent trading and transaction costs;
this module is what makes that propagation checkable rather than
asserted.

Deliberately a STATIC (buy-and-hold) delta hedge, not a dynamically
rebalanced one: holding the hedge ratio fixed at its day-0 value
isolates the propagated Delta-ESTIMATION error from the separate
effect of rebalancing timing/frequency. `hedging.rate_hedge`/
`rl_agent`'s own dynamically-rehedged policies are evaluated
elsewhere (HDG-01..14) and are not what is being measured here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

from prometheus.hedging.simulate import simulate_self_financing_hedge
from prometheus.pde_solvers.benchmark import greeks_error_report
from prometheus.pde_solvers.problem import BlackScholesPDESpec
from prometheus.titan.risk_metrics import historical_expected_shortfall
from prometheus.volterra.black_scholes import black_scholes_greeks, black_scholes_price
from prometheus.volterra.instruments import EuropeanOption
from prometheus.volterra.market import MarketSnapshot

_ARBITRARY_AS_OF = date(2024, 1, 1)
"""Black-Scholes is time-homogeneous (PDE-solvers' own `benchmark.py`
makes the identical disclosure); only `maturity`, a duration, enters
the math, so which calendar date is used here is immaterial."""


@dataclass(frozen=True, slots=True)
class ModelDependencyEdge:
    upstream_model: str
    downstream_model: str
    interaction: str


MODEL_DEPENDENCY_GRAPH: tuple[ModelDependencyEdge, ...] = (
    ModelDependencyEdge(
        upstream_model="pde-solvers",
        downstream_model="deep-hedge",
        interaction=(
            "A desk that delta-hedges using the grid PDE solver's Delta "
            "(rather than the exact closed-form Delta) feeds that Delta "
            "directly into `hedging.simulate.simulate_self_financing_hedge`, "
            "the shared accounting engine used by every policy in "
            "`hedging` (HDG-13)."
        ),
    ),
)
"""The real, already-present dependency this module traces -- not an
aspirational graph of models that might someday interact."""


@dataclass(frozen=True, slots=True)
class ErrorPropagationReport:
    local_delta_error: float
    """PDE-08's own local score: grid Delta minus closed-form Delta."""
    aggregate_es_using_exact_delta: float
    aggregate_es_using_grid_delta: float
    alpha: float

    @property
    def aggregate_es_shift(self) -> float:
        """The system-level consequence of the local error: how much
        the downstream, aggregate Expected Shortfall moves when the
        grid Delta is used in place of the exact one."""
        return self.aggregate_es_using_grid_delta - self.aggregate_es_using_exact_delta


def propagate_pde_delta_error_to_portfolio_es(
    spec: BlackScholesPDESpec,
    price_paths: np.ndarray,
    dt: float,
    *,
    cost_rate: float,
    alpha: float = 0.95,
    n_space: int = 400,
    n_time: int = 400,
) -> ErrorPropagationReport:
    if price_paths.ndim != 2 or price_paths.shape[1] < 2:
        raise ValueError("price_paths must have shape (n_paths, n_steps + 1)")
    n_paths, n_plus_1 = price_paths.shape
    n_steps = n_plus_1 - 1
    spot = float(price_paths[0, 0])

    error_report = greeks_error_report(spec, spot, n_space=n_space, n_time=n_time)
    if error_report.delta_error is None:
        raise ValueError("greeks_error_report did not return a Delta error for this spec")

    market = MarketSnapshot(
        as_of=_ARBITRARY_AS_OF,
        spot=spot,
        risk_free_rate=spec.risk_free_rate,
        volatility=spec.volatility,
    )
    option = EuropeanOption(spec.strike, spec.maturity, spec.option_type)
    exact_delta = black_scholes_greeks(market, option).delta
    exact_price = black_scholes_price(market, option)
    grid_delta = exact_delta + error_report.delta_error

    def aggregate_es(delta: float) -> float:
        hedge_ratios = np.full((n_paths, n_steps), delta)
        result = simulate_self_financing_hedge(
            price_paths,
            dt,
            spec.strike,
            spec.option_type,
            spec.risk_free_rate,
            cost_rate,
            exact_price,
            hedge_ratios,
        )
        return historical_expected_shortfall(result.terminal_loss, alpha)

    return ErrorPropagationReport(
        local_delta_error=error_report.delta_error,
        aggregate_es_using_exact_delta=aggregate_es(exact_delta),
        aggregate_es_using_grid_delta=aggregate_es(grid_delta),
        alpha=alpha,
    )
