from __future__ import annotations

from prometheus.core.money import Money
from prometheus.marl.baselines import FixedConsumptionRule, FixedWageRule
from prometheus.marl.env import run_rollout
from prometheus.marl.training import (
    JointTrainingResult,
    deterministic_firm_policy,
    deterministic_household_policy,
    n_parameters,
    train_joint_ppo,
)

_CAPITAL = Money(100_000, "USD")


def test_training_with_the_same_seed_reproduces_identical_epoch_losses() -> None:
    """MAR-08: 'training manifest reproduces learning-curve statistics'."""

    def _train() -> JointTrainingResult:
        return train_joint_ppo(
            seed=7, n_epochs=10, episodes_per_epoch=6, n_steps=6,
            firm_opening_capital=_CAPITAL, train_household=True, train_firm=False,
            firm_fixed_rule=FixedWageRule(0.5),
        )

    first = _train()
    second = _train()
    assert [e.loss for e in first.household_epoch_log] == [
        e.loss for e in second.household_epoch_log
    ]


def test_a_different_seed_produces_a_different_learning_curve() -> None:
    def _train(seed: int) -> JointTrainingResult:
        return train_joint_ppo(
            seed=seed, n_epochs=10, episodes_per_epoch=6, n_steps=6,
            firm_opening_capital=_CAPITAL, train_household=True, train_firm=False,
            firm_fixed_rule=FixedWageRule(0.5),
        )

    a, b = _train(0), _train(1)
    assert [e.loss for e in a.household_epoch_log] != [e.loss for e in b.household_epoch_log]


def test_trained_household_net_has_a_real_nonzero_parameter_count() -> None:
    result = train_joint_ppo(
        seed=0, n_epochs=5, episodes_per_epoch=4, n_steps=4,
        firm_opening_capital=_CAPITAL, train_household=True, train_firm=False,
        firm_fixed_rule=FixedWageRule(0.5),
    )
    assert result.household_net is not None
    assert n_parameters(result.household_net) > 0


def test_mar_04_household_policy_learning_beats_every_tested_fixed_baseline() -> None:
    """MAR-04: 'improvement checked against rule-based counterfactuals'.
    Real numbers (seed=0, 60 epochs, 16 episodes/epoch): learned policy
    scores ~42.07; the best fixed-fraction baseline tried (0.8) scores
    ~41.20. The learned policy also discovers a genuinely different,
    TIME-VARYING strategy (near-full consumption on non-terminal steps,
    conservative only on the bequest-weighted final step) that no
    constant fraction can represent."""
    trained = train_joint_ppo(
        seed=0, n_epochs=60, episodes_per_epoch=16, n_steps=6,
        firm_opening_capital=_CAPITAL, train_household=True, train_firm=False,
        firm_fixed_rule=FixedWageRule(0.5),
    )
    assert trained.household_net is not None
    learned_policy = deterministic_household_policy(trained.household_net, n_steps=6)
    learned_result = run_rollout(
        household_policy=learned_policy, firm_policy=FixedWageRule(0.5), n_steps=6,
        firm_opening_capital=_CAPITAL,
    )
    learned_utility = learned_result.total_household_utility()

    baseline_utilities = [
        run_rollout(
            household_policy=FixedConsumptionRule(f), firm_policy=FixedWageRule(0.5),
            n_steps=6, firm_opening_capital=_CAPITAL,
        ).total_household_utility()
        for f in (0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 1.0)
    ]
    assert learned_utility > max(baseline_utilities)

    # The learned policy is NOT a constant fraction: it must differ
    # meaningfully between a non-terminal and the final (bequest) step.
    from prometheus.marl.spaces import HouseholdObservation

    early = learned_policy(
        HouseholdObservation(cash_balance_minor=50_000, net_worth_minor=50_000, step=0)
    ).consumption_fraction
    final = learned_policy(
        HouseholdObservation(cash_balance_minor=50_000, net_worth_minor=50_000, step=5)
    ).consumption_fraction
    assert early - final > 0.2


def test_mar_05_firm_policy_learning_beats_every_tested_fixed_wage_baseline() -> None:
    """MAR-05: 'improvement checked against rule-based counterfactuals',
    and 'no negative output or investment outside the feasible domain'
    -- every wage paid is `feasibility`-projected, so it is structurally
    bounded by the firm's own real cash balance (confirmed directly by
    `test_mar_action_feasibility.py`). Real numbers (seed=0, 40 epochs):
    learned firm policy scores ~-8.16 profit; the best fixed-wage
    baseline tried (fraction=0.1) scores ~-24.39 -- see `training.py`'s
    own docstring for why this reward structure's real optimum IS low
    wage payment, not an interior trade-off."""
    trained = train_joint_ppo(
        seed=0, n_epochs=40, episodes_per_epoch=12, n_steps=6,
        firm_opening_capital=_CAPITAL, train_household=False, train_firm=True,
        household_fixed_rule=FixedConsumptionRule(0.8),
    )
    assert trained.firm_net is not None
    learned_policy = deterministic_firm_policy(trained.firm_net, n_steps=6)
    learned_result = run_rollout(
        household_policy=FixedConsumptionRule(0.8), firm_policy=learned_policy, n_steps=6,
        firm_opening_capital=_CAPITAL,
    )
    learned_profit = learned_result.total_firm_profit()

    baseline_profits = [
        run_rollout(
            household_policy=FixedConsumptionRule(0.8), firm_policy=FixedWageRule(wf),
            n_steps=6, firm_opening_capital=_CAPITAL,
        ).total_firm_profit()
        for wf in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)
    ]
    assert learned_profit > max(baseline_profits)

    # Confirms the disclosed finding directly: the learned wage fraction
    # is low (converged toward the structural optimum of this reward).
    from prometheus.marl.spaces import FirmObservation

    fraction = learned_policy(
        FirmObservation(cash_balance_minor=50_000, net_worth_minor=50_000, step=0)
    ).wage_fraction
    assert fraction < 0.15
