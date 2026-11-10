from __future__ import annotations

from prometheus.core.money import Money
from prometheus.marl.baselines import FixedConsumptionRule, FixedWageRule
from prometheus.marl.env import run_rollout


def test_a_fixed_rule_rollout_is_bit_identical_across_two_independent_runs() -> None:
    def _run() -> tuple[float, float, int, int]:
        result = run_rollout(
            household_policy=FixedConsumptionRule(0.8),
            firm_policy=FixedWageRule(0.5),
            n_steps=6,
            firm_opening_capital=Money(100_000, "USD"),
        )
        return (
            result.total_household_utility(),
            result.total_firm_profit(),
            result.final_household_net_worth_minor,
            result.final_firm_net_worth_minor,
        )

    first = _run()
    second = _run()
    assert first == second


def test_fixed_consumption_rule_always_proposes_its_configured_fraction() -> None:
    from prometheus.marl.spaces import HouseholdObservation

    rule = FixedConsumptionRule(0.42)
    for step in range(5):
        obs = HouseholdObservation(cash_balance_minor=1000, net_worth_minor=1000, step=step)
        assert rule(obs).consumption_fraction == 0.42


def test_fixed_wage_rule_always_proposes_its_configured_fraction() -> None:
    from prometheus.marl.spaces import FirmObservation

    rule = FixedWageRule(0.33)
    for step in range(5):
        obs = FirmObservation(cash_balance_minor=1000, net_worth_minor=1000, step=step)
        assert rule(obs).wage_fraction == 0.33
