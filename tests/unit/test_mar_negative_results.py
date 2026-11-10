"""Confirms `negative_results.NEGATIVE_RESULT_LOG`'s two entries each
still reproduce the exact triggering configuration and failure mode
they document -- if either of these starts failing, the log itself is
stale and must be corrected to match current reality (see that
module's own docstring)."""

from __future__ import annotations

from prometheus.core.money import Money
from prometheus.marl.baselines import FixedWageRule
from prometheus.marl.env import run_rollout
from prometheus.marl.negative_results import NEGATIVE_RESULT_LOG
from prometheus.marl.training import deterministic_household_policy, train_joint_ppo

_CAPITAL = Money(100_000, "USD")


def test_the_log_has_exactly_the_two_documented_real_findings() -> None:
    ids = {entry.finding_id for entry in NEGATIVE_RESULT_LOG}
    assert ids == {"mar-reward-degenerate-optimum", "mar-ppo-learning-rate-collapse"}
    for entry in NEGATIVE_RESULT_LOG:
        assert entry.triggering_configuration
        assert entry.observed_failure
        assert entry.detection_method
        assert entry.resolution


def test_reward_degenerate_optimum_finding_is_reproduced_by_bequest_weight_zero() -> None:
    from prometheus.marl.baselines import FixedConsumptionRule

    utilities = [
        run_rollout(
            household_policy=FixedConsumptionRule(f), firm_policy=FixedWageRule(0.5),
            n_steps=6, firm_opening_capital=_CAPITAL, bequest_weight=0.0,
        ).total_household_utility()
        for f in (0.5, 0.7, 0.9, 1.0)
    ]
    assert utilities[-1] == max(utilities)  # fraction=1.0 wins again, the documented failure


def test_ppo_learning_rate_collapse_finding_is_reproduced_at_the_documented_configuration() -> None:
    trained = train_joint_ppo(
        seed=0, n_epochs=25, episodes_per_epoch=8, n_steps=6,
        firm_opening_capital=_CAPITAL, train_household=True, train_firm=False,
        firm_fixed_rule=FixedWageRule(0.5), learning_rate=5.0,
    )
    assert trained.household_net is not None
    policy = deterministic_household_policy(trained.household_net, n_steps=6)
    from prometheus.marl.spaces import HouseholdObservation

    fractions = {
        policy(
            HouseholdObservation(cash_balance_minor=cash, net_worth_minor=cash, step=step)
        ).consumption_fraction
        for cash in (10_000, 50_000, 90_000)
        for step in (0, 3, 5)
    }
    # The documented collapse: the policy becomes unresponsive to its
    # own input, proposing (numerically) the same fraction everywhere.
    assert max(fractions) - min(fractions) < 1e-3
