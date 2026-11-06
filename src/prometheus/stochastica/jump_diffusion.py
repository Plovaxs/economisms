"""Merton (1976) jump-diffusion (SDE-08: "jump or fat-tail stress scenario
model, with parameterization and jump timing fully disclosed").

  dS/S = (mu - lambda*k) dt + sigma dW_t + d(sum of jumps)

Jumps arrive as a compound Poisson process with intensity `jump_intensity`
(lambda); each jump multiplies the price by (1 + Y), with
ln(1 + Y) ~ Normal(jump_mean, jump_std^2) iid. `k = E[Y] = exp(jump_mean +
0.5*jump_std^2) - 1` is the jump compensator: subtracting `lambda*k` from
the drift keeps S a (risk-neutral, if mu = r) martingale despite the
jumps' own nonzero expected log-return contribution -- the same role
`-0.5*sigma^2` already plays for the pure-diffusion part.

Terminal-time simulation here is EXACT, not an Euler discretization:
given the number of jumps N ~ Poisson(lambda*T) over the whole horizon,
the sum of N iid Normal(jump_mean, jump_std^2) jump log-sizes is itself
exactly Normal(N*jump_mean, N*jump_std^2) (closed under convolution), so
one Poisson draw plus one Normal draw per path reproduces the exact
terminal jump contribution with no time-stepping error at all. A
multi-step path (for payoffs that need the full trajectory, not just
S_T) still has to discretize the diffusion part; jumps are allocated to
steps the same exact way, per step, using the step's own sub-interval.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from prometheus.numerics import require_finite


@dataclass(frozen=True, slots=True)
class MertonJumpParams:
    mu: float
    sigma: float
    jump_intensity: float
    jump_mean: float
    jump_std: float

    def __post_init__(self) -> None:
        require_finite(
            mu=self.mu,
            sigma=self.sigma,
            jump_intensity=self.jump_intensity,
            jump_mean=self.jump_mean,
            jump_std=self.jump_std,
        )
        if self.sigma <= 0:
            raise ValueError("sigma must be positive")
        if self.jump_intensity < 0:
            raise ValueError("jump_intensity must be non-negative")
        if self.jump_std < 0:
            raise ValueError("jump_std must be non-negative")

    def jump_compensator(self) -> float:
        """k = E[Y] = E[(1+Y) - 1], where ln(1+Y) ~ Normal(jump_mean,
        jump_std^2): the expected PROPORTIONAL price change from one
        jump."""
        return math.exp(self.jump_mean + 0.5 * self.jump_std**2) - 1.0


def simulate_jump_diffusion_paths(
    s0: float,
    params: MertonJumpParams,
    maturity: float,
    n_steps: int,
    n_paths: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Return price paths, shape (n_paths, n_steps + 1). Each step's jump
    count is drawn from Poisson(jump_intensity * dt) and that step's total
    jump log-return from the matching Normal(n*jump_mean, n*jump_std^2) --
    exact for that step's sub-interval, for the same reason the terminal-
    only case is exact."""
    if s0 <= 0:
        raise ValueError("s0 must be positive")
    if maturity <= 0:
        raise ValueError("maturity must be positive")
    if n_steps < 1 or n_paths < 1:
        raise ValueError("n_steps and n_paths must each be >= 1")

    dt = maturity / n_steps
    k = params.jump_compensator()
    diffusion_drift = (params.mu - params.jump_intensity * k - 0.5 * params.sigma**2) * dt
    diffusion_scale = params.sigma * math.sqrt(dt)

    log_s = np.full(n_paths, math.log(s0))
    paths = np.empty((n_paths, n_steps + 1))
    paths[:, 0] = s0

    for t in range(n_steps):
        diffusion = diffusion_drift + diffusion_scale * rng.standard_normal(n_paths)

        jump_total = np.zeros(n_paths)
        if params.jump_intensity > 0:
            n_jumps = rng.poisson(params.jump_intensity * dt, size=n_paths)
            nonzero = n_jumps > 0
            if np.any(nonzero):
                n = n_jumps[nonzero]
                jump_total[nonzero] = rng.normal(
                    n * params.jump_mean, np.sqrt(n * params.jump_std**2)
                )

        log_s = log_s + diffusion + jump_total
        paths[:, t + 1] = np.exp(log_s)

    return paths
