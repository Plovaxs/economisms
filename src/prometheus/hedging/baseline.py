"""Black-Scholes delta baseline and a cost-aware no-trade-band variant.

Both produce a (n_paths, n_steps) array of *target holdings*, one per
rehedge decision, each causal by construction: the decision at step t uses
only the price at step t (and, for the no-trade band, the policy's own
prior holding) -- never a later price (HDG-05's "no future path information").
"""

from __future__ import annotations

import numpy as np
from scipy.stats import norm

from prometheus.volterra.instruments import OptionType


def black_scholes_delta_vectorized(
    spot: np.ndarray,
    strike: float,
    risk_free_rate: float,
    volatility: float,
    time_to_maturity: np.ndarray | float,
    option_type: OptionType,
    dividend_yield: float = 0.0,
) -> np.ndarray:
    """A vectorized Black-Scholes delta, used instead of looping scalar
    calls to volterra.black_scholes.black_scholes_greeks so that generating
    hedge ratios across thousands of paths and steps stays fast. Consistency
    with the scalar formula is checked in tests."""
    ttm = np.maximum(np.asarray(time_to_maturity, dtype=float), 1e-10)
    drift_term = (risk_free_rate - dividend_yield + 0.5 * volatility**2) * ttm
    d1 = (np.log(spot / strike) + drift_term) / (volatility * np.sqrt(ttm))
    disc_q = np.exp(-dividend_yield * ttm)
    result: np.ndarray
    if option_type == "call":
        result = disc_q * norm.cdf(d1)
    else:
        result = disc_q * (norm.cdf(d1) - 1.0)
    return result


def black_scholes_delta_hedge_ratios(
    price_paths: np.ndarray,
    dt: float,
    strike: float,
    maturity: float,
    risk_free_rate: float,
    volatility: float,
    option_type: OptionType,
    dividend_yield: float = 0.0,
) -> np.ndarray:
    """HDG-02: the model-consistent delta hedge. Returns shape
    (n_paths, n_steps), where n_steps = price_paths.shape[1] - 1."""
    n_paths, n_plus_1 = price_paths.shape
    n_steps = n_plus_1 - 1
    ratios = np.empty((n_paths, n_steps))
    for t in range(n_steps):
        remaining = max(maturity - t * dt, 1e-10)
        ratios[:, t] = black_scholes_delta_vectorized(
            price_paths[:, t],
            strike,
            risk_free_rate,
            volatility,
            remaining,
            option_type,
            dividend_yield,
        )
    return ratios


def apply_no_trade_band(target_ratios: np.ndarray, band_width: float) -> np.ndarray:
    """HDG-03: only rehedge when the gap between the currently-held
    position and the new target exceeds `band_width`; otherwise keep the
    previous holding. Reduces turnover (and therefore transaction cost) at
    the expense of tracking the target less tightly."""
    if band_width < 0:
        raise ValueError("band_width must be non-negative")
    n_paths, n_steps = target_ratios.shape
    actual = np.empty((n_paths, n_steps))
    current = np.zeros(n_paths)
    for t in range(n_steps):
        gap = target_ratios[:, t] - current
        move = np.abs(gap) > band_width
        current = np.where(move, target_ratios[:, t], current)
        actual[:, t] = current
    return actual
