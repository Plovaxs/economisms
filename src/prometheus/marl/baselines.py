"""MAR-01: "Implement deterministic fixed-rule policy baselines --
Baseline reward and economy trajectories independently reproducible."

Every policy here is a pure function of its observation (no internal
state, no randomness) -- "independently reproducible" is then not an
extra property to test, it is automatic: the same `env.run_rollout`
call with the same fixed-rule policies produces bit-identical
`RolloutResult`s on any run, on any machine, confirmed directly by
`test_mar_baselines.py::test_a_fixed_rule_rollout_is_bit_identical_across_two_independent_runs`.
"""

from __future__ import annotations

from dataclasses import dataclass

from prometheus.marl.spaces import (
    FirmAction,
    FirmObservation,
    HouseholdAction,
    HouseholdObservation,
)


@dataclass(frozen=True, slots=True)
class FixedConsumptionRule:
    """Household baseline: always consume a fixed share of current cash."""

    fraction: float = 0.8

    def __call__(self, observation: HouseholdObservation) -> HouseholdAction:
        return HouseholdAction(consumption_fraction=self.fraction)


@dataclass(frozen=True, slots=True)
class FixedWageRule:
    """Firm baseline: always pay a fixed share of current cash as wages."""

    fraction: float = 0.5

    def __call__(self, observation: FirmObservation) -> FirmAction:
        return FirmAction(wage_fraction=self.fraction)
