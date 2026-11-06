"""Heston stochastic volatility (Tier 1 -- classical).

  dS = mu*S*dt + sqrt(v)*S*dW_s
  dv = kappa*(theta - v)*dt + xi*sqrt(v)*dW_v,   corr(dW_s, dW_v) = rho

Discretization: log-Euler on price (so S stays positive by construction)
combined with full-truncation Euler on variance (Lord, Koekkoek & van Dijk,
2010): wherever v appears in a drift, diffusion or square root it is first
floored at zero, and the stored variance path is floored at zero too. This
is a simple, well-known positivity-preserving scheme (SDE-03/04); it is not
a claim of being the most accurate one available (e.g. Andersen's QE scheme
is more accurate at large time steps) -- see the Feller-ratio diagnostic
below for when its bias is likely to matter.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from prometheus.numerics import require_finite


@dataclass(frozen=True, slots=True)
class HestonParams:
    mu: float
    kappa: float
    theta: float
    xi: float
    rho: float
    v0: float

    def __post_init__(self) -> None:
        require_finite(
            mu=self.mu, kappa=self.kappa, theta=self.theta, xi=self.xi, rho=self.rho, v0=self.v0
        )
        if self.kappa <= 0:
            raise ValueError("kappa must be positive")
        if self.theta <= 0:
            raise ValueError("theta must be positive")
        if self.xi <= 0:
            raise ValueError("xi must be positive")
        if not -1.0 <= self.rho <= 1.0:
            raise ValueError("rho must be in [-1, 1]")
        if self.v0 < 0:
            raise ValueError("v0 must be non-negative")

    def feller_ratio(self) -> float:
        """2*kappa*theta / xi^2. >= 1 means the *continuous-time* CIR
        variance process cannot reach zero (the Feller condition). A
        discretized scheme can still touch the zero floor even when this
        holds, but the lower this ratio, the larger the full-truncation
        scheme's discretization bias is expected to be (SDE-04)."""
        return 2 * self.kappa * self.theta / self.xi**2

    def exact_variance_moments(self, t: float) -> tuple[float, float]:
        """Exact (mean, variance) of v_t under the continuous-time CIR
        process -- the reference a discretized scheme's terminal variance
        distribution should be checked against (SDE-03, VAL-06)."""
        mean = self.theta + (self.v0 - self.theta) * np.exp(-self.kappa * t)
        variance = (
            (self.v0 * self.xi**2 * np.exp(-self.kappa * t) / self.kappa)
            * (1 - np.exp(-self.kappa * t))
            + (self.theta * self.xi**2 / (2 * self.kappa))
            * (1 - np.exp(-self.kappa * t)) ** 2
        )
        return float(mean), float(variance)


def simulate_heston_paths(
    s0: float,
    params: HestonParams,
    maturity: float,
    n_steps: int,
    n_paths: int,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (price_paths, variance_paths), each of shape
    (n_paths, n_steps + 1). Variance is guaranteed non-negative at every
    stored point by construction (the full-truncation floor below)."""
    if s0 <= 0:
        raise ValueError("s0 must be positive")
    if maturity <= 0:
        raise ValueError("maturity must be positive")
    if n_steps < 1 or n_paths < 1:
        raise ValueError("n_steps and n_paths must each be >= 1")

    dt = maturity / n_steps
    sqrt_dt = np.sqrt(dt)

    s = np.empty((n_paths, n_steps + 1))
    v = np.empty((n_paths, n_steps + 1))
    s[:, 0] = s0
    v[:, 0] = params.v0

    z1 = rng.standard_normal((n_paths, n_steps))
    z2 = rng.standard_normal((n_paths, n_steps))
    dw_s = z1 * sqrt_dt
    dw_v = (params.rho * z1 + np.sqrt(1 - params.rho**2) * z2) * sqrt_dt

    log_s = np.full(n_paths, np.log(s0))
    v_current = v[:, 0].copy()
    for t in range(n_steps):
        v_pos = np.maximum(v_current, 0.0)
        sqrt_v_pos = np.sqrt(v_pos)

        log_s = log_s + (params.mu - 0.5 * v_pos) * dt + sqrt_v_pos * dw_s[:, t]
        v_next = (
            v_current
            + params.kappa * (params.theta - v_pos) * dt
            + params.xi * sqrt_v_pos * dw_v[:, t]
        )
        v_current = np.maximum(v_next, 0.0)

        s[:, t + 1] = np.exp(log_s)
        v[:, t + 1] = v_current

    return s, v
