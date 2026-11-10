from __future__ import annotations

import pytest

from prometheus.core.money import Money
from prometheus.marl.baselines import FixedConsumptionRule, FixedWageRule
from prometheus.marl.env import run_rollout


def test_rollout_rejects_non_positive_n_steps() -> None:
    with pytest.raises(ValueError, match="n_steps"):
        run_rollout(
            household_policy=FixedConsumptionRule(0.5),
            firm_policy=FixedWageRule(0.5),
            n_steps=0,
            firm_opening_capital=Money(1000, "USD"),
        )


def test_household_never_ends_with_negative_cash_or_net_worth() -> None:
    """The real `econosim.agents`/`core.ledger` feasibility guarantee
    (VAL-08) applies here automatically, since every action is posted
    through the real `Household.consume`/`Firm.pay_wages` -- this is a
    sanity confirmation at the rollout level, not a re-derivation of
    that guarantee."""
    result = run_rollout(
        household_policy=FixedConsumptionRule(1.0),
        firm_policy=FixedWageRule(1.0),
        n_steps=10,
        firm_opening_capital=Money(500_000, "USD"),
    )
    assert result.final_household_net_worth_minor >= 0
    assert result.final_firm_net_worth_minor >= 0


def test_the_reward_design_has_a_genuine_interior_optimum_not_a_degenerate_one() -> None:
    """Locks in the real finding documented in `env.py`'s own docstring
    and `negative_results.NEGATIVE_RESULT_LOG`'s 'mar-reward-degenerate
    -optimum' entry: utility as a function of a FIXED consumption
    fraction must NOT be monotonically increasing all the way to
    fraction=1.0 -- it must peak somewhere strictly inside (0, 1), with
    fraction=1.0 scoring measurably worse than the peak. If this test
    ever fails, the bequest-value term has been broken or removed and
    the degenerate always-spend-everything exploit this module's own
    history already found once is back."""
    capital = Money(100_000, "USD")
    fractions = [0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 1.0]
    utilities = [
        run_rollout(
            household_policy=FixedConsumptionRule(f),
            firm_policy=FixedWageRule(0.5),
            n_steps=6,
            firm_opening_capital=capital,
        ).total_household_utility()
        for f in fractions
    ]
    peak_utility = max(utilities)
    full_consumption_utility = utilities[fractions.index(1.0)]
    assert full_consumption_utility < peak_utility - 1.0  # measurably worse, not noise
    peak_fraction = fractions[utilities.index(peak_utility)]
    assert 0.5 <= peak_fraction <= 0.9  # strictly interior, not at either boundary


def test_bequest_weight_zero_reproduces_the_original_degenerate_optimum() -> None:
    """The converse confirmation: with `bequest_weight=0`, the ORIGINAL
    (buggy) degenerate behavior this package's history found is
    reproduced exactly -- full consumption every step IS then the
    maximum, proving the bequest term is what changed the landscape,
    not some other, unrelated difference."""
    capital = Money(100_000, "USD")
    fractions = [0.5, 0.7, 0.9, 1.0]
    utilities = [
        run_rollout(
            household_policy=FixedConsumptionRule(f),
            firm_policy=FixedWageRule(0.5),
            n_steps=6,
            firm_opening_capital=capital,
            bequest_weight=0.0,
        ).total_household_utility()
        for f in fractions
    ]
    assert utilities[-1] == max(utilities)  # fraction=1.0 is the maximum again
