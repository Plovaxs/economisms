"""A genuine Taylor-rule baseline -- a real reaction function responding to
inflation/output deviations, which this repository did NOT previously have.
`econosim.policy_rate.PolicyRateRule` (left unmodified by this package) only
mean-reverts toward a fixed neutral rate plus exogenous shocks; its own
module docstring is explicit that it is "a rule-based reaction function...
not a learned policy" in the sense of reacting to shocks, but it has no
inflation/output feedback term at all.

    proposed_rate = neutral_rate + phi_pi * (inflation - inflation_target) + phi_y * output_gap

`act()` clamps the proposal to `[0, rate_max]`; `PolicyLabEnvironment.step`
additionally enforces the per-step rate-of-change cap regardless of this
clamp, so the full constraint is always applied, independent of the
baseline's own clamping here.
"""

from __future__ import annotations

from dataclasses import dataclass

from prometheus.policylab.environment import PolicyLabState


@dataclass(frozen=True, slots=True)
class TaylorRuleBaseline:
    neutral_rate: float
    inflation_target: float
    rate_max: float
    phi_pi: float = 1.5
    phi_y: float = 0.5

    def __post_init__(self) -> None:
        if self.rate_max <= 0:
            raise ValueError("rate_max must be positive")
        if self.neutral_rate < 0 or self.neutral_rate > self.rate_max:
            raise ValueError("neutral_rate must lie within [0, rate_max]")

    def act(self, state: PolicyLabState) -> float:
        inflation_gap = state.inflation - self.inflation_target
        proposed = self.neutral_rate + self.phi_pi * inflation_gap + self.phi_y * state.output_gap
        return min(max(proposed, 0.0), self.rate_max)
