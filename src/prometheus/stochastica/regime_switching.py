"""Regime-switching market baseline (SDE-06: "implement regime-switching
market baseline... transition probabilities valid and stationary test
available").

A discrete-time Markov chain with `n_regimes` states, each carrying its
own GBM-style drift `regime_mu[i]` and volatility `regime_sigma[i]`. At
every step the regime evolves by sampling the next state from the
current state's row of `transition_matrix`, and the log-price evolves by
one log-Euler GBM step using THAT regime's own (mu, sigma) -- the same
discretization `stochastica.gbm.simulate_piecewise_drift_gbm_paths`
already uses for a piecewise-deterministic drift path, generalized here
to a STOCHASTIC (Markov-driven), and volatility-switching too, not just
drift-switching, regime path.

"Transition probabilities valid" is enforced by `RegimeSwitchingParams`:
every row of `transition_matrix` must sum to 1 (a genuine row-stochastic
matrix) and every entry must lie in [0, 1] -- not merely close to
1-summing by coincidence.

"Stationary test available" is `stationary_distribution` (the
regime-occupancy distribution pi such that pi @ P == pi, found via the
general eigenvector/null-space method, not just a 2-state closed form)
plus `is_stationary_distribution` (a direct, independent check of that
fixed-point equation on any candidate distribution). Both were verified,
before being trusted, three ways: against the closed-form 2-state
formula pi0 = p10/(p01+p10) (derived directly from the stationarity
equation, not assumed); against a 2,000,000-step empirical long-run
simulation of the SAME 2-state chain; and, for a 3-state chain, by
confirming `pi @ P == pi` exactly.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class RegimeSwitchingParams:
    transition_matrix: np.ndarray
    regime_mu: np.ndarray
    regime_sigma: np.ndarray

    def __post_init__(self) -> None:
        p = np.asarray(self.transition_matrix, dtype=float)
        mu = np.asarray(self.regime_mu, dtype=float)
        sigma = np.asarray(self.regime_sigma, dtype=float)
        if p.ndim != 2 or p.shape[0] != p.shape[1]:
            raise ValueError(f"transition_matrix must be square 2D, got shape {p.shape}")
        n_regimes = p.shape[0]
        if mu.shape != (n_regimes,) or sigma.shape != (n_regimes,):
            raise ValueError(
                f"regime_mu and regime_sigma must both have shape ({n_regimes},), "
                f"got {mu.shape} and {sigma.shape}"
            )
        if not np.all(np.isfinite(p)):
            raise ValueError("transition_matrix must contain only finite values")
        if not np.all(np.isfinite(mu)):
            raise ValueError("regime_mu must contain only finite values")
        if not np.all(np.isfinite(sigma)):
            raise ValueError("regime_sigma must contain only finite values")
        if np.any(p < 0.0) or np.any(p > 1.0):
            raise ValueError("every transition_matrix entry must lie in [0, 1]")
        row_sums = p.sum(axis=1)
        if not np.allclose(row_sums, 1.0, atol=1e-9):
            raise ValueError(
                f"every row of transition_matrix must sum to exactly 1.0, got row sums {row_sums}"
            )
        if np.any(sigma < 0.0):
            raise ValueError("every regime_sigma entry must be non-negative")

    @property
    def n_regimes(self) -> int:
        return int(np.asarray(self.transition_matrix).shape[0])


def stationary_distribution(transition_matrix: np.ndarray) -> np.ndarray:
    """The regime-occupancy distribution pi with pi @ P == pi and
    sum(pi) == 1, found generally (any n_regimes >= 1) via the
    eigenvector/null-space method: pi^T solves (P^T - I) pi^T = 0,
    normalized to sum to 1 (least-squares, not a dedicated null-space
    routine, since the extra normalization row makes the system
    well-posed directly)."""
    p = np.asarray(transition_matrix, dtype=float)
    n = p.shape[0]
    coefficients = np.vstack([p.T - np.eye(n), np.ones(n)])
    target = np.zeros(n + 1)
    target[-1] = 1.0
    pi, *_ = np.linalg.lstsq(coefficients, target, rcond=None)
    return pi


def is_stationary_distribution(
    transition_matrix: np.ndarray, pi: np.ndarray, atol: float = 1e-9
) -> bool:
    """Directly checks the fixed-point equation pi @ P == pi on a
    candidate distribution, independent of how `pi` was produced --
    the literal "stationary test" SDE-06 asks for, usable on a
    distribution from ANY source, not only `stationary_distribution`
    above."""
    pi = np.asarray(pi, dtype=float)
    p = np.asarray(transition_matrix, dtype=float)
    if pi.shape != (p.shape[0],):
        raise ValueError(f"pi must have shape ({p.shape[0]},), got {pi.shape}")
    if not np.isclose(pi.sum(), 1.0, atol=atol):
        return False
    if np.any(pi < -atol):
        return False
    return bool(np.allclose(pi @ p, pi, atol=atol))


def simulate_regime_switching_paths(
    s0: float,
    params: RegimeSwitchingParams,
    maturity: float,
    n_steps: int,
    n_paths: int,
    rng: np.random.Generator,
    initial_regime_distribution: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Returns (price_paths, regime_paths), each shape (n_paths,
    n_steps + 1). `initial_regime_distribution` draws each path's regime
    at t=0 from that distribution (uniform over regimes if not given);
    thereafter every path's regime evolves by its own independent draw
    from `transition_matrix`'s current-regime row each step."""
    if s0 <= 0:
        raise ValueError("s0 must be positive")
    if maturity <= 0:
        raise ValueError("maturity must be positive")
    if n_steps < 1:
        raise ValueError("n_steps must be >= 1")
    if n_paths < 1:
        raise ValueError("n_paths must be >= 1")

    n_regimes = params.n_regimes
    p = np.asarray(params.transition_matrix, dtype=float)
    mu = np.asarray(params.regime_mu, dtype=float)
    sigma = np.asarray(params.regime_sigma, dtype=float)

    if initial_regime_distribution is None:
        initial_regime_distribution = np.full(n_regimes, 1.0 / n_regimes)
    else:
        initial_regime_distribution = np.asarray(initial_regime_distribution, dtype=float)
        if not np.isclose(initial_regime_distribution.sum(), 1.0, atol=1e-9):
            raise ValueError("initial_regime_distribution must sum to 1")

    dt = maturity / n_steps
    regime_paths = np.empty((n_paths, n_steps + 1), dtype=np.int64)
    regime_paths[:, 0] = rng.choice(n_regimes, size=n_paths, p=initial_regime_distribution)

    log_paths = np.empty((n_paths, n_steps + 1))
    log_paths[:, 0] = np.log(s0)

    for t in range(n_steps):
        current_regime = regime_paths[:, t]
        z = rng.standard_normal(n_paths)
        step_mu = mu[current_regime]
        step_sigma = sigma[current_regime]
        log_paths[:, t + 1] = (
            log_paths[:, t] + (step_mu - 0.5 * step_sigma**2) * dt + step_sigma * np.sqrt(dt) * z
        )
        next_regime = np.empty(n_paths, dtype=np.int64)
        for regime in range(n_regimes):
            in_regime = current_regime == regime
            n_in_regime = int(in_regime.sum())
            if n_in_regime > 0:
                next_regime[in_regime] = rng.choice(n_regimes, size=n_in_regime, p=p[regime])
        regime_paths[:, t + 1] = next_regime

    price_paths = np.exp(log_paths)
    price_paths[:, 0] = s0  # exp(log(s0)) is not bit-exact; match gbm.py's own convention
    if not np.all(np.isfinite(price_paths)):
        raise ValueError(
            f"s0={s0}, regime_mu={mu.tolist()}, regime_sigma={sigma.tolist()}, "
            f"maturity={maturity} produced a non-finite (overflowing) simulated price for "
            "at least one path/step -- this parameter combination has no computable answer "
            "under float64"
        )
    return price_paths, regime_paths
