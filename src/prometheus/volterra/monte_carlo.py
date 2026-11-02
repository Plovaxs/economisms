"""Monte Carlo pricing with standard errors and an optional control variate.

PRI-06 / PRI-13: every price returned carries a standard error; nothing is
reported as a bare number. Paths are simulated under the risk-neutral
measure explicitly -- drift = risk_free_rate - dividend_yield, never an
agent's or calibration's physical-measure mu (SDE-09) -- using the same
stochastica.gbm engine as the physical-measure simulator, with the measure
made correct by construction here rather than left to the caller.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from prometheus.stochastica.gbm import simulate_gbm_paths
from prometheus.volterra.instruments import EuropeanOption
from prometheus.volterra.market import MarketSnapshot


@dataclass(frozen=True, slots=True)
class MonteCarloResult:
    price: float
    standard_error: float
    n_paths: int
    control_variate_used: bool


def _payoff(option: EuropeanOption, terminal: np.ndarray) -> np.ndarray:
    if option.option_type == "call":
        return np.maximum(terminal - option.strike, 0.0)
    return np.maximum(option.strike - terminal, 0.0)


def monte_carlo_price_vanilla(
    market: MarketSnapshot,
    option: EuropeanOption,
    n_paths: int,
    n_steps: int,
    rng: np.random.Generator,
    use_control_variate: bool = True,
) -> MonteCarloResult:
    risk_neutral_drift = market.risk_free_rate - market.dividend_yield
    paths = simulate_gbm_paths(
        market.spot,
        risk_neutral_drift,
        market.volatility,
        option.maturity,
        n_steps,
        n_paths,
        rng,
    )
    terminal = paths[:, -1]
    discount = np.exp(-market.risk_free_rate * option.maturity)
    discounted_payoff = discount * _payoff(option, terminal)

    if use_control_variate:
        control = discount * terminal
        control_mean = market.spot * np.exp(-market.dividend_yield * option.maturity)
        covariance_matrix = np.cov(discounted_payoff, control)
        var_control = covariance_matrix[1, 1]
        beta = covariance_matrix[0, 1] / var_control if var_control > 0 else 0.0
        estimator = discounted_payoff - beta * (control - control_mean)
    else:
        estimator = discounted_payoff

    price = float(estimator.mean())
    standard_error = float(estimator.std(ddof=1) / np.sqrt(n_paths))
    return MonteCarloResult(
        price=price,
        standard_error=standard_error,
        n_paths=n_paths,
        control_variate_used=use_control_variate,
    )
