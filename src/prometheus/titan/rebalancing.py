"""Multi-period portfolio rebalancing simulator (OPT-07): simulate a
portfolio of correlated assets over many periods, periodically
re-estimating the covariance (optionally Ledoit-Wolf shrunk, PR-024) from
a trailing window and re-optimizing (minimum-variance or target-return,
PR-023) against the realized prior holdings with an optional turnover
penalty, executing trades under proportional transaction costs.

This is the first closed loop connecting titan.covariance and
titan.portfolio across time -- both existed only as single-period,
standalone calls before this. `simulate_rebalancing` takes a plain
(n_total_periods, n_assets) returns array rather than generating its own
paths, so it composes with any return source (stochastica, historical
data, or a hand-built array for testing) instead of being coupled to one.

Causality: the covariance/expected-return estimate used to decide period
t's weights is built only from `returns[t : t + estimation_window]` --
strictly before period t -- and that decision is applied only to
`returns[t + estimation_window]`, the period immediately after the
window, which was not available when the decision was made. A later
period's return cannot affect any earlier period's weights; tested
directly (tests/unit/test_rebalancing.py), not just documented.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from prometheus.titan.covariance import shrink_covariance_ledoit_wolf
from prometheus.titan.portfolio import (
    PortfolioConstraints,
    minimum_variance_portfolio,
    target_return_portfolio,
)
from prometheus.titan.risk_metrics import historical_var, max_drawdown


@dataclass(frozen=True, slots=True)
class RebalancingConfig:
    n_periods: int
    estimation_window: int
    rebalance_every: int = 1
    use_shrinkage: bool = True
    target_return: float | None = None
    """None -> minimum-variance each rebalance; otherwise the Markowitz
    target-return formulation at this required period return."""
    cost_rate: float = 0.001
    turnover_penalty: float = 0.0
    constraints: PortfolioConstraints = field(default_factory=PortfolioConstraints)

    def __post_init__(self) -> None:
        if self.n_periods < 1:
            raise ValueError("n_periods must be >= 1")
        if self.estimation_window < 2:
            raise ValueError("estimation_window must be >= 2")
        if self.rebalance_every < 1:
            raise ValueError("rebalance_every must be >= 1")
        if self.cost_rate < 0:
            raise ValueError("cost_rate must be non-negative")
        if self.turnover_penalty < 0:
            raise ValueError("turnover_penalty must be non-negative")


class RebalancingFailure(RuntimeError):
    """Raised when a scheduled rebalance's optimization does not succeed --
    the simulation stops rather than silently carrying forward stale
    weights under a label of having rebalanced (ECO-16-style fail closed)."""


@dataclass(frozen=True, slots=True)
class PeriodRecord:
    period: int
    rebalanced: bool
    weights: np.ndarray
    period_return: float
    transaction_cost: float
    turnover: float
    wealth: float
    shrinkage_intensity: float | None


@dataclass(frozen=True, slots=True)
class RebalancingResult:
    periods: tuple[PeriodRecord, ...]
    final_wealth: float
    total_cost: float
    total_turnover: float
    max_drawdown: float
    historical_var_95: float


def simulate_rebalancing(returns: np.ndarray, config: RebalancingConfig) -> RebalancingResult:
    returns = np.asarray(returns, dtype=float)
    if returns.ndim != 2:
        raise ValueError("returns must be 2-D (n_total_periods, n_assets)")
    n_total, n_assets = returns.shape
    required = config.estimation_window + config.n_periods
    if n_total < required:
        raise ValueError(
            f"returns has {n_total} periods, but estimation_window "
            f"({config.estimation_window}) + n_periods ({config.n_periods}) = "
            f"{required} are required"
        )

    weights = np.zeros(n_assets)
    wealth = 1.0
    total_cost = 0.0
    total_turnover = 0.0
    records: list[PeriodRecord] = []

    for t in range(config.n_periods):
        window = returns[t : t + config.estimation_window]
        rebalanced = t % config.rebalance_every == 0
        shrinkage_intensity: float | None = None

        if rebalanced:
            if config.use_shrinkage:
                shrink_result = shrink_covariance_ledoit_wolf(window)
                covariance = shrink_result.covariance
                shrinkage_intensity = shrink_result.shrinkage_intensity
            else:
                covariance = np.cov(window, rowvar=False, ddof=0)

            prior_for_penalty = weights if config.turnover_penalty > 0 else None
            if config.target_return is None:
                opt_result = minimum_variance_portfolio(
                    covariance,
                    config.constraints,
                    prior_weights=prior_for_penalty,
                    turnover_penalty=config.turnover_penalty,
                )
            else:
                expected_returns = window.mean(axis=0)
                opt_result = target_return_portfolio(
                    expected_returns,
                    covariance,
                    config.target_return,
                    config.constraints,
                    prior_weights=prior_for_penalty,
                    turnover_penalty=config.turnover_penalty,
                )
            if not opt_result.success:
                raise RebalancingFailure(
                    f"portfolio optimization failed at period {t}: {opt_result.status_message}"
                )
            target_weights = opt_result.weights
        else:
            target_weights = weights

        trade = target_weights - weights
        turnover = float(np.sum(np.abs(trade)))
        cost = config.cost_rate * turnover * wealth
        weights = target_weights

        realized_return = float(returns[t + config.estimation_window] @ weights)
        wealth = wealth * (1.0 + realized_return) - cost

        total_cost += cost
        total_turnover += turnover
        records.append(
            PeriodRecord(
                period=t,
                rebalanced=rebalanced,
                weights=target_weights,
                period_return=realized_return,
                transaction_cost=cost,
                turnover=turnover,
                wealth=wealth,
                shrinkage_intensity=shrinkage_intensity,
            )
        )

    wealth_path = np.array([1.0] + [r.wealth for r in records])
    period_returns = np.array([r.period_return for r in records])

    return RebalancingResult(
        periods=tuple(records),
        final_wealth=wealth,
        total_cost=total_cost,
        total_turnover=total_turnover,
        max_drawdown=max_drawdown(wealth_path),
        historical_var_95=historical_var(-period_returns, 0.95),
    )
