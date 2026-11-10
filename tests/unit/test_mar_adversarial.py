"""MAR-10: "Define reward hacking and degenerate agent safeguards --
Adversarial tests attempt exploits in reward design."

Two real adversarial attempts, both against the ACTUAL `env.run_rollout`/
`training.train_joint_ppo` machinery, not a description of what an
exploit might look like:

1. A policy that always proposes a wildly infeasible raw action (far
   outside [0, 1]) -- does the real ledger ever accept an infeasible
   transaction? (It must not, by `feasibility.py`'s construction.)
2. A policy that greedily maximizes NAIVE per-step consumption (always
   spend everything) -- does it actually win under this package's real
   reward design? Before `env.py`'s bequest-value fix (see
   `negative_results.NEGATIVE_RESULT_LOG`), this exploit genuinely
   worked (fraction=1.0 WAS the true optimum). This test confirms it no
   longer does -- the real, measured outcome of fixing it, not an
   assumption that the fix worked.
"""

from __future__ import annotations

from prometheus.core.money import Money
from prometheus.marl.baselines import FixedWageRule
from prometheus.marl.env import run_rollout
from prometheus.marl.spaces import HouseholdAction, HouseholdObservation

_CAPITAL = Money(100_000, "USD")


def _always_overspend_policy(observation: HouseholdObservation) -> HouseholdAction:
    """An adversarial policy that always proposes 5000% of cash (50.0) --
    `HouseholdAction.__post_init__` clips it to 1.0 before it ever
    reaches `feasibility.project_fraction_to_amount`, so this exercises
    the FULL real action pipeline an attacker would actually have to go
    through, not just the projection function in isolation."""
    return HouseholdAction(consumption_fraction=50.0)


def test_an_adversarial_overspend_policy_never_produces_an_infeasible_transaction() -> None:
    result = run_rollout(
        household_policy=_always_overspend_policy,
        firm_policy=FixedWageRule(0.5),
        n_steps=10,
        firm_opening_capital=_CAPITAL,
    )
    # No exception was raised (the real test here), and balances stay sane.
    assert result.final_household_net_worth_minor >= 0
    assert result.final_firm_net_worth_minor >= 0


def _always_max_consume_policy(observation: HouseholdObservation) -> HouseholdAction:
    return HouseholdAction(consumption_fraction=1.0)


def test_the_naive_always_spend_everything_exploit_no_longer_wins() -> None:
    """The real, measured confirmation that `env.py`'s bequest-value fix
    closed the degenerate exploit this package's own development found:
    greedy full consumption must now score measurably WORSE than a
    sensible fixed-fraction policy, not better or equal."""
    greedy_utility = run_rollout(
        household_policy=_always_max_consume_policy,
        firm_policy=FixedWageRule(0.5),
        n_steps=6,
        firm_opening_capital=_CAPITAL,
    ).total_household_utility()

    from prometheus.marl.baselines import FixedConsumptionRule

    sensible_utility = run_rollout(
        household_policy=FixedConsumptionRule(0.8),
        firm_policy=FixedWageRule(0.5),
        n_steps=6,
        firm_opening_capital=_CAPITAL,
    ).total_household_utility()

    assert greedy_utility < sensible_utility - 0.5  # measurably worse, not a tie
