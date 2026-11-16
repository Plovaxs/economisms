"""Held-out comparison between a trained PPO policy and the Taylor-rule
baseline, both driven through the exact same `environment.simulate`
driver -- so neither side is evaluated under a different reward, horizon,
or shock-generation scheme than the other. Per this project's own H5
framing, a null or negative result (the Taylor rule winning) is a valid,
reportable outcome, not something to retrain away.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from prometheus.policylab.environment import (
    PolicyLabEnvConfig,
    PolicyLabEnvironment,
    PolicyLabState,
    simulate,
)


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    per_seed_mean_reward: tuple[float, ...]
    per_seed_applied_rates: tuple[tuple[float, ...], ...]

    @property
    def mean_reward(self) -> float:
        return sum(self.per_seed_mean_reward) / len(self.per_seed_mean_reward)


def evaluate_policy(
    policy: Callable[[PolicyLabState], float],
    env_config: PolicyLabEnvConfig,
    lambda_rate: float,
    seeds: tuple[int, ...],
) -> EvaluationResult:
    if len(seeds) == 0:
        raise ValueError("seeds must be non-empty")
    per_seed_mean_reward: list[float] = []
    per_seed_applied_rates: list[tuple[float, ...]] = []
    for seed in seeds:
        env = PolicyLabEnvironment(env_config, lambda_rate=lambda_rate)
        result = simulate(env, seed, policy)
        per_seed_mean_reward.append(result.mean_reward)
        per_seed_applied_rates.append(tuple(s.rate for s in result.states[1:]))
    return EvaluationResult(
        per_seed_mean_reward=tuple(per_seed_mean_reward),
        per_seed_applied_rates=tuple(per_seed_applied_rates),
    )
