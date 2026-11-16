"""A reduced-form macro environment the policy rate acts on: the textbook
three-equation New Keynesian structure (IS curve + Phillips curve), the
blueprint's own "simplified... synthetic economy" scope for this subsystem.
Deterministic given a seed -- all randomness comes from one
`numpy.random.default_rng(seed)` stream per episode, not from
`econosim.shocks` (that module's `Shock`/`ShockGenerator` are tagged for a
ledger-backed `Economy`'s accounting transactions; this environment has no
ledger, so a plain seeded Gaussian shock is the honest, undercoupled choice).

Causal by construction: the rate chosen at step t only affects
`output_gap`/`inflation` at step t+1 (through the IS/Phillips updates
below), never the state at t it was chosen from -- no same-step use of an
outcome that has not occurred yet, the same timing discipline
`econosim.policy_rate.PolicyRateRule.step` already follows.

    output_gap[t+1] = rho_y * output_gap[t] - is_sensitivity * (rate[t] - neutral_rate) + eps_y
    inflation[t+1]  = inflation_target + rho_pi * (inflation[t] - inflation_target)
                      + phillips_slope * output_gap[t] + eps_pi

The chosen rate is constrained BY CONSTRUCTION inside `step()` -- clamped to
`[0, rate_max]` and to within `max_rate_change` of the previous step's
*applied* rate -- regardless of what a caller (a Taylor rule or an
untrained policy network) proposes. This is the same "squash/clamp inside
the primitive, not trust the caller" discipline `hedging.rl_agent` already
applies to its sigmoid-bounded hedge ratio.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from prometheus.policylab.reward import policy_reward


@dataclass(frozen=True, slots=True)
class PolicyLabEnvConfig:
    inflation_target: float = 0.02
    neutral_rate: float = 0.03
    rho_pi: float = 0.6
    rho_y: float = 0.5
    phillips_slope: float = 0.3
    is_sensitivity: float = 0.5
    sigma_pi: float = 0.004
    sigma_y: float = 0.01
    rate_max: float = 0.10
    max_rate_change: float = 0.02
    n_steps: int = 24

    def __post_init__(self) -> None:
        if self.rate_max <= 0:
            raise ValueError("rate_max must be positive")
        if self.max_rate_change <= 0:
            raise ValueError("max_rate_change must be positive")
        if self.neutral_rate < 0 or self.neutral_rate > self.rate_max:
            raise ValueError("neutral_rate must lie within [0, rate_max]")
        if self.sigma_pi < 0 or self.sigma_y < 0:
            raise ValueError("shock standard deviations must be non-negative")
        if self.n_steps < 1:
            raise ValueError("n_steps must be a positive integer")


@dataclass(frozen=True, slots=True)
class PolicyLabState:
    inflation: float
    output_gap: float
    rate: float
    step: int


class PolicyLabEnvironment:
    """One episode's worth of mutable rollout state. `reset(seed)` must be
    called before the first `step(...)`; each `reset` starts a fresh,
    independent shock stream."""

    def __init__(self, config: PolicyLabEnvConfig, lambda_rate: float = 1.0) -> None:
        if lambda_rate < 0:
            raise ValueError("lambda_rate must be non-negative")
        self.config = config
        self.lambda_rate = lambda_rate
        self._rng: np.random.Generator | None = None
        self._state: PolicyLabState | None = None
        self._prev_rate: float | None = None

    def reset(self, seed: int) -> PolicyLabState:
        self._rng = np.random.default_rng(seed)
        state = PolicyLabState(
            inflation=self.config.inflation_target,
            output_gap=0.0,
            rate=self.config.neutral_rate,
            step=0,
        )
        self._state = state
        self._prev_rate = self.config.neutral_rate
        return state

    def step(self, proposed_rate: float) -> tuple[PolicyLabState, float, bool]:
        if self._state is None or self._rng is None or self._prev_rate is None:
            raise RuntimeError("call reset(seed) before step(...)")
        cfg = self.config
        state = self._state

        lo = max(0.0, self._prev_rate - cfg.max_rate_change)
        hi = min(cfg.rate_max, self._prev_rate + cfg.max_rate_change)
        rate = min(max(proposed_rate, lo), hi)
        rate = min(max(rate, 0.0), cfg.rate_max)

        inflation_gap = state.inflation - cfg.inflation_target
        output_gap = state.output_gap
        reward = policy_reward(inflation_gap, output_gap, rate, self._prev_rate, self.lambda_rate)

        eps_pi = float(self._rng.normal(0.0, cfg.sigma_pi))
        eps_y = float(self._rng.normal(0.0, cfg.sigma_y))
        next_output_gap = (
            cfg.rho_y * output_gap - cfg.is_sensitivity * (rate - cfg.neutral_rate) + eps_y
        )
        next_inflation = (
            cfg.inflation_target
            + cfg.rho_pi * inflation_gap
            + cfg.phillips_slope * output_gap
            + eps_pi
        )
        next_step = state.step + 1
        next_state = PolicyLabState(
            inflation=next_inflation, output_gap=next_output_gap, rate=rate, step=next_step
        )
        self._state = next_state
        self._prev_rate = rate
        done = next_step >= cfg.n_steps
        return next_state, reward, done


@dataclass(frozen=True, slots=True)
class SimulationResult:
    states: tuple[PolicyLabState, ...]
    rewards: tuple[float, ...]

    @property
    def mean_reward(self) -> float:
        return sum(self.rewards) / len(self.rewards)

    @property
    def mean_squared_inflation_gap(self) -> float:
        target = self.states[0].inflation  # reset() always starts at inflation_target
        gaps = [s.inflation - target for s in self.states[1:]]
        return sum(g**2 for g in gaps) / len(gaps)

    @property
    def mean_squared_output_gap(self) -> float:
        gaps = [s.output_gap for s in self.states[1:]]
        return sum(g**2 for g in gaps) / len(gaps)


def simulate(
    env: PolicyLabEnvironment, seed: int, policy: Callable[[PolicyLabState], float]
) -> SimulationResult:
    """Drive `env` for one full episode under `policy` (a plain
    `state -> proposed_rate` callable -- the same signature a Taylor-rule
    baseline and a deterministic-evaluation PPO policy both satisfy)."""
    state = env.reset(seed)
    states = [state]
    rewards: list[float] = []
    done = False
    while not done:
        proposed_rate = policy(state)
        state, reward, done = env.step(proposed_rate)
        states.append(state)
        rewards.append(reward)
    return SimulationResult(states=tuple(states), rewards=tuple(rewards))
