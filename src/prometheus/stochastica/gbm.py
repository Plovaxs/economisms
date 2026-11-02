"""Geometric Brownian motion (Tier 0 -- analytical).

dS/S = mu*dt + sigma*dW  =>  S_t = S_0 * exp((mu - 0.5*sigma^2)*t + sigma*W_t)

Paths are drawn from the *exact* lognormal transition density at each step
rather than an Euler discretization of S itself, so there is no time-
discretization bias to characterize for this particular model -- SDE-01's
"known distributions, reproducible path construction" is satisfied exactly,
not approximately.
"""

from __future__ import annotations

import numpy as np

from prometheus.stochastica.correlated import correlated_normal_draws


def simulate_gbm_paths(
    s0: float,
    mu: float,
    sigma: float,
    maturity: float,
    n_steps: int,
    n_paths: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Return an (n_paths, n_steps + 1) array of price paths; column 0 is s0."""
    if s0 <= 0:
        raise ValueError("s0 must be positive")
    if sigma < 0:
        raise ValueError("sigma must be non-negative")
    if maturity <= 0:
        raise ValueError("maturity must be positive")
    if n_steps < 1:
        raise ValueError("n_steps must be >= 1")
    if n_paths < 1:
        raise ValueError("n_paths must be >= 1")

    dt = maturity / n_steps
    z = rng.standard_normal((n_paths, n_steps))
    log_increments = (mu - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * z
    cumulative_log_returns = np.cumsum(log_increments, axis=1)

    paths = np.empty((n_paths, n_steps + 1))
    paths[:, 0] = s0
    paths[:, 1:] = s0 * np.exp(cumulative_log_returns)
    return paths


def terminal_moments(s0: float, mu: float, sigma: float, maturity: float) -> tuple[float, float]:
    """Exact (mean, variance) of S_T under the GBM SDE above -- the
    reference a Monte Carlo terminal distribution should be checked against
    (SDE-01)."""
    mean = s0 * np.exp(mu * maturity)
    variance = (s0**2) * np.exp(2 * mu * maturity) * (np.exp(sigma**2 * maturity) - 1.0)
    return float(mean), float(variance)


def piecewise_gbm_terminal_moments(
    s0: float, mu_path: list[float], sigma: float, dt: float
) -> tuple[float, float]:
    """Exact (mean, variance) of S_T for a GBM whose drift is piecewise
    constant across equal-length periods: mu_path[t] applies over period t.
    log(S_T/S0) is Gaussian with mean sum(mu_path)*dt - 0.5*sigma^2*T and
    variance sigma^2*T (T = len(mu_path)*dt) -- the same lognormal
    structure as constant-drift GBM with mu*T replaced by the time-integral
    of drift, sum(mu_path)*dt. Reduces to terminal_moments() when every
    entry of mu_path is equal."""
    n_steps = len(mu_path)
    if n_steps < 1:
        raise ValueError("mu_path must be non-empty")
    if s0 <= 0:
        raise ValueError("s0 must be positive")
    maturity = n_steps * dt
    integrated_drift = sum(mu_path) * dt
    mean = s0 * np.exp(integrated_drift)
    variance = (s0**2) * np.exp(2 * integrated_drift) * (np.exp(sigma**2 * maturity) - 1.0)
    return float(mean), float(variance)


def simulate_piecewise_drift_gbm_paths(
    s0: float,
    mu_path: list[float],
    sigma: float,
    dt: float,
    n_paths: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """A GBM path simulator whose drift is piecewise constant: mu_path[t]
    applies over period t = [t*dt, (t+1)*dt). Returns shape
    (n_paths, len(mu_path) + 1). Random draws are generated period by
    period in chronological order, so a later entry of mu_path can never
    influence an earlier period's simulated values -- a no-lookahead
    guarantee that is tested explicitly, not merely asserted."""
    n_steps = len(mu_path)
    if n_steps < 1:
        raise ValueError("mu_path must be non-empty")
    if s0 <= 0:
        raise ValueError("s0 must be positive")
    if sigma < 0:
        raise ValueError("sigma must be non-negative")
    if n_paths < 1:
        raise ValueError("n_paths must be >= 1")
    if dt <= 0:
        raise ValueError("dt must be positive")

    sqrt_dt = np.sqrt(dt)
    log_increments = np.empty((n_paths, n_steps))
    for t in range(n_steps):
        z = rng.standard_normal(n_paths)
        log_increments[:, t] = (mu_path[t] - 0.5 * sigma**2) * dt + sigma * sqrt_dt * z

    cumulative = np.cumsum(log_increments, axis=1)
    paths = np.empty((n_paths, n_steps + 1))
    paths[:, 0] = s0
    paths[:, 1:] = s0 * np.exp(cumulative)
    return paths


def simulate_correlated_gbm_paths(
    s0: np.ndarray,
    mu: np.ndarray,
    sigma: np.ndarray,
    correlation: np.ndarray,
    maturity: float,
    n_steps: int,
    n_paths: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """SDE-02: a multi-asset GBM simulator with correlated Brownian
    increments. `correlation` is validated as a proper correlation/
    covariance structure by correlated_normal_draws (VAL-04). Returns an
    array of shape (n_paths, n_steps + 1, n_assets)."""
    s0 = np.asarray(s0, dtype=float)
    mu = np.asarray(mu, dtype=float)
    sigma = np.asarray(sigma, dtype=float)
    n_assets = s0.shape[0]
    if mu.shape != (n_assets,) or sigma.shape != (n_assets,):
        raise ValueError("s0, mu and sigma must all have shape (n_assets,)")
    if correlation.shape != (n_assets, n_assets):
        raise ValueError("correlation must have shape (n_assets, n_assets)")
    if np.any(s0 <= 0):
        raise ValueError("every s0 entry must be positive")
    if np.any(sigma < 0):
        raise ValueError("every sigma entry must be non-negative")
    if n_steps < 1 or n_paths < 1:
        raise ValueError("n_steps and n_paths must each be >= 1")

    dt = maturity / n_steps
    paths = np.empty((n_paths, n_steps + 1, n_assets))
    paths[:, 0, :] = s0

    log_s = np.log(s0) * np.ones((n_paths, n_assets))
    for t in range(n_steps):
        z = correlated_normal_draws(rng, n_paths, correlation)
        log_s = log_s + (mu - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * z
        paths[:, t + 1, :] = np.exp(log_s)
    return paths
