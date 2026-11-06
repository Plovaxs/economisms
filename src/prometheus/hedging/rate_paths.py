"""Classical GBM and causal delta targets under a declared macro rate schedule.

Rates at observation t are current closing rates; interval [t,t+1] uses
that rate. A supplied schedule describes a realized macro bank, not future
information available to delta. Pricing volatility stays at its declared
assumption even if realized market volatility is stressed.
"""

from __future__ import annotations

import numpy as np

from prometheus.hedging.baseline import black_scholes_delta_vectorized
from prometheus.volterra.instruments import OptionType


def rate_scheduled_gbm(
    spot: float,
    equity_risk_premium: float,
    volatility: float,
    dt: float,
    decision_rates: np.ndarray,
    standard_normals: np.ndarray,
) -> np.ndarray:
    rates = np.asarray(decision_rates, dtype=float)
    z = np.asarray(standard_normals, dtype=float)
    if rates.ndim != 1 or len(rates) < 2 or not np.all(np.isfinite(rates)):
        raise ValueError("decision_rates must be a finite observation-time vector")
    if z.ndim != 2 or z.shape[0] < 1 or z.shape[1] != len(rates) - 1:
        raise ValueError("standard_normals must have shape (positive n_paths, n_intervals)")
    if not np.all(np.isfinite(z)) or not all(
        np.isfinite(value) for value in (spot, equity_risk_premium, volatility, dt)
    ):
        raise ValueError("market inputs must be finite")
    if min(spot, volatility, dt) <= 0:
        raise ValueError("spot, volatility and dt must be positive")
    paths = np.empty((z.shape[0], len(rates)))
    paths[:, 0] = spot
    for t in range(z.shape[1]):
        paths[:, t + 1] = paths[:, t] * np.exp(
            (rates[t] + equity_risk_premium - 0.5 * volatility**2) * dt
            + volatility * np.sqrt(dt) * z[:, t]
        )
    if not np.all(np.isfinite(paths)) or np.any(paths <= 0):
        raise ValueError("rate-scheduled GBM produced invalid prices")
    return paths


def rate_scheduled_delta(
    paths: np.ndarray,
    dt: float,
    strike: float,
    volatility: float,
    option_type: OptionType,
    decision_rates: np.ndarray,
) -> np.ndarray:
    prices = np.asarray(paths, dtype=float)
    rates = np.asarray(decision_rates, dtype=float)
    if prices.ndim != 2 or min(prices.shape) < 1 or prices.shape[1] < 2:
        raise ValueError("paths require positive paths and at least two observation times")
    if rates.shape != (prices.shape[1],) or not np.all(np.isfinite(rates)):
        raise ValueError("one finite decision rate is required per observation time")
    if not np.all(np.isfinite(prices)) or np.any(prices <= 0):
        raise ValueError("prices must be finite and positive")
    if not all(np.isfinite(v) and v > 0 for v in (dt, strike, volatility)):
        raise ValueError("dt, strike and volatility must be finite and positive")
    if option_type not in ("call", "put"):
        raise ValueError("option_type must be call or put")
    n_steps = prices.shape[1] - 1
    targets = np.empty((prices.shape[0], n_steps))
    for t in range(n_steps):
        targets[:, t] = black_scholes_delta_vectorized(
            prices[:, t], strike, rates[t], volatility, (n_steps - t) * dt, option_type
        )
    return targets
