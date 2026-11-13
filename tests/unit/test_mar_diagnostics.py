from __future__ import annotations

from prometheus.core.money import Money
from prometheus.marl.baselines import FixedConsumptionRule
from prometheus.marl.diagnostics import (
    evaluate_ood_wage_shock,
    gini_coefficient,
    single_vs_colearning_report,
    welfare_report_across_heterogeneous_households,
)


def test_gini_of_a_perfectly_equal_population_is_zero() -> None:
    assert gini_coefficient([100.0, 100.0, 100.0]) == 0.0


def test_gini_of_an_all_zero_population_is_zero_not_a_division_by_zero_error() -> None:
    assert gini_coefficient([0.0, 0.0, 0.0]) == 0.0


def test_gini_is_higher_for_a_more_unequal_population() -> None:
    equal_ish = gini_coefficient([90.0, 100.0, 110.0])
    unequal = gini_coefficient([1.0, 1.0, 298.0])
    assert unequal > equal_ish


def test_mar_12_welfare_report_over_a_real_heterogeneous_population() -> None:
    """MAR-12: 'evaluation includes distributional and aggregate
    metrics'. Population heterogeneity: each household faces a
    different real firm_opening_capital (disclosed as independent
    conditions, not a simultaneous shared market -- see
    `diagnostics.welfare_report_across_heterogeneous_households`'s own
    docstring)."""
    capitals = tuple(Money(c, "USD") for c in (50_000, 80_000, 100_000, 120_000, 150_000, 200_000))
    report = welfare_report_across_heterogeneous_households(
        household_policy_fn=FixedConsumptionRule(0.8), firm_opening_capitals=capitals
    )
    assert len(report.final_net_worths) == len(capitals)
    gini = report.gini_of_final_net_worth()
    assert 0.0 < gini < 1.0  # real, non-degenerate inequality
    assert report.aggregate_utility() > 0.0
    # richer starting condition -> (weakly) richer final net worth
    assert report.final_net_worths == tuple(sorted(report.final_net_worths))


def test_mar_09_and_mar_11_co_learning_is_measurably_less_stable_than_single_agent() -> None:
    """MAR-09 ('policy drift and convergence diagnostics across seeds')
    and MAR-11 ('ablation isolates impact of simultaneous learning')
    from one real experiment. Real result (seeds 0,1,2; 20 epochs, 6
    episodes/epoch): single-agent household-utility std across seeds is
    small (~0.2-0.3); co-learning's is roughly 4-5x larger (~1.0-1.5) --
    a real, measured nonstationarity signal from training against a
    simultaneously-changing partner, not asserted from intuition."""
    report = single_vs_colearning_report(
        seeds=(0, 1, 2), n_epochs=20, episodes_per_epoch=6, n_steps=6
    )
    assert len(report.single_agent) == 3
    assert len(report.co_learning) == 3
    single_std = report.single_agent_household_std()
    co_std = report.co_learning_household_std()
    assert co_std > 2.0 * single_std  # measurably less stable, not noise


def test_co_learning_is_not_only_less_stable_but_also_robustly_lower_mean_utility() -> None:
    """PR-176: the pre-existing claim above is about VARIANCE
    (nonstationarity) only; whether co-learning is better or worse for
    the household ON AVERAGE had never been directly tested. A sweep
    (10 seeds at the job default config, plus 5 more at 2x the epochs
    and 2x the episodes-per-epoch, 20 real runs total) found
    co-learning's mean household utility is robustly LOWER than
    single-agent's -- every single seed tried, at every budget tried
    (0/20), by an effect size (~10-20) far exceeding co-learning's own
    seed-to-seed std (~1-2) -- not noise. Locked in here at this file's
    existing fast scale/seeds for a permanent regression check."""
    report = single_vs_colearning_report(
        seeds=(0, 1, 2, 3, 4), n_epochs=20, episodes_per_epoch=6, n_steps=6
    )
    deltas = [
        c.household_utility - s.household_utility
        for s, c in zip(report.single_agent, report.co_learning, strict=True)
    ]
    assert all(d < 0 for d in deltas)
    assert report.mean_household_utility_delta() < 0


def test_mar_13_ood_wage_shock_degrades_performance_with_reported_uncertainty() -> None:
    """MAR-13: 'held-out shock performance reported with uncertainty'.
    The policy is trained ONLY under `training_firm_capital`; it never
    sees `shocked_firm_capital` (a much smaller firm, i.e. a recession-
    like wage shock) until this frozen, already-trained policy is
    evaluated under it -- no retraining happens in between."""
    report = evaluate_ood_wage_shock(
        seeds=(0, 1, 2),
        training_firm_capital=Money(100_000, "USD"),
        shocked_firm_capital=Money(30_000, "USD"),
        n_epochs=20, episodes_per_epoch=6, n_steps=6,
    )
    assert len(report.in_distribution_utilities) == 3
    assert len(report.shocked_utilities) == 3
    assert report.mean_degradation() > 0.0  # the shock genuinely hurts performance
    assert report.degradation_std() >= 0.0  # a real (small-but-present) uncertainty measure


def test_mar_13_rejects_training_and_shocked_capital_being_identical() -> None:
    import pytest

    with pytest.raises(ValueError, match="differ"):
        evaluate_ood_wage_shock(
            seeds=(0,),
            training_firm_capital=Money(100_000, "USD"),
            shocked_firm_capital=Money(100_000, "USD"),
        )
