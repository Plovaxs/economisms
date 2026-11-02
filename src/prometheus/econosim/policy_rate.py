"""A minimal central-bank policy-rate process (ECO-05): a discrete,
mean-reverting (Euler-discretized Ornstein-Uhlenbeck) baseline perturbed by
deterministic "policy_rate"-kind shocks from econosim.shocks. This is a
rule-based reaction function with explicit, testable coefficients -- not a
learned policy. Section 04 is explicit that "constrained learning" for the
central bank comes only after a rules-based baseline passes conservation
and stylized-fact tests, which this repository has not attempted yet.
"""

from __future__ import annotations

from dataclasses import dataclass

from prometheus.econosim.shocks import Shock


@dataclass(frozen=True, slots=True)
class PolicyRateRule:
    neutral_rate: float
    mean_reversion_speed: float
    dt: float

    def __post_init__(self) -> None:
        if self.mean_reversion_speed < 0:
            raise ValueError("mean_reversion_speed must be non-negative")
        if self.dt <= 0:
            raise ValueError("dt must be positive")

    def step(self, current_rate: float, shocks: list[Shock]) -> float:
        """Advance the policy rate by one macro step: mean-revert toward
        neutral_rate, then add the sum of any 'policy_rate'-kind shocks for
        this step. Causal by construction -- uses only `current_rate` (set
        at the prior step) and `shocks` already drawn for *this* step."""
        reverted = current_rate + self.mean_reversion_speed * (
            self.neutral_rate - current_rate
        ) * self.dt
        policy_shock_total = sum(s.magnitude for s in shocks if s.kind == "policy_rate")
        return reverted + policy_shock_total


def simulate_policy_rate_path(
    rule: PolicyRateRule,
    initial_rate: float,
    shock_schedule: list[list[Shock]],
) -> list[float]:
    """Deterministic given `shock_schedule` (itself deterministic if drawn
    from a seeded shocks.ShockGenerator). Returns
    [initial_rate, rate_after_step_1, rate_after_step_2, ...], of length
    len(shock_schedule) + 1."""
    rates = [initial_rate]
    current = initial_rate
    for shocks in shock_schedule:
        current = rule.step(current, shocks)
        rates.append(current)
    return rates
