import numpy as np
import pytest

from prometheus.experiments.hedge_benchmark import PRIMARY_ENDPOINT, run_hedge_benchmark
from prometheus.hedging.deep_hedge import train_deep_hedge
from prometheus.stochastica.gbm import simulate_gbm_paths

STRIKE = 100.0
MATURITY = 1.0
RISK_FREE_RATE = 0.05
VOLATILITY = 0.2
SPOT = 100.0
MU = 0.08
N_STEPS = 20
COST_RATE = 0.005
PREMIUM = 10.0


@pytest.fixture(scope="module")
def trained_policy_result():
    dt = MATURITY / N_STEPS
    rng = np.random.default_rng(1)
    train_paths = simulate_gbm_paths(SPOT, MU, VOLATILITY, MATURITY, N_STEPS, 2_000, rng)
    return train_deep_hedge(
        train_paths,
        dt,
        STRIKE,
        MATURITY,
        "call",
        RISK_FREE_RATE,
        COST_RATE,
        PREMIUM,
        cvar_alpha=0.9,
        turnover_penalty=0.001,
        n_epochs=80,
        batch_size=256,
        learning_rate=0.01,
        seed=0,
    )


def _run(trained_policy_result, **overrides):
    config = dict(
        training_result=trained_policy_result,
        strike=STRIKE,
        maturity=MATURITY,
        option_type="call",
        risk_free_rate=RISK_FREE_RATE,
        volatility=VOLATILITY,
        cost_rate=COST_RATE,
        initial_premium=PREMIUM,
        n_steps=N_STEPS,
        n_paths_per_seed=1_000,
        test_seeds=[100, 200],
        cvar_alpha=0.9,
        n_bootstrap_resamples=500,
        bootstrap_confidence=0.95,
        spot=SPOT,
        mu=MU,
    )
    config.update(overrides)
    return run_hedge_benchmark(**config)


def test_report_has_one_result_per_seed(trained_policy_result) -> None:
    report = _run(trained_policy_result, test_seeds=[1, 2, 3])
    assert len(report.per_seed_results) == 3
    assert [r.test_seed for r in report.per_seed_results] == [1, 2, 3]


def test_primary_endpoint_is_fixed_and_documented(trained_policy_result) -> None:
    report = _run(trained_policy_result)
    assert report.primary_endpoint == PRIMARY_ENDPOINT


def test_limitations_are_non_empty_and_scope_the_claim(trained_policy_result) -> None:
    report = _run(trained_policy_result)
    assert len(report.limitations) > 0
    joined = " ".join(report.limitations)
    assert "economy" in joined and "market" in joined


def test_result_hash_is_reproducible_across_independent_runs(trained_policy_result) -> None:
    report_a = _run(trained_policy_result)
    report_b = _run(trained_policy_result)
    assert report_a.manifest.result_hash == report_b.manifest.result_hash
    # run_id/created_at are wall-clock-derived, not part of the claim:
    assert report_a.manifest.run_id != report_b.manifest.run_id


def test_result_hash_changes_with_a_different_seed_set(trained_policy_result) -> None:
    report_a = _run(trained_policy_result, test_seeds=[1, 2])
    report_b = _run(trained_policy_result, test_seeds=[3, 4])
    assert report_a.manifest.result_hash != report_b.manifest.result_hash


def test_bootstrap_cis_are_well_formed_for_every_seed(trained_policy_result) -> None:
    report = _run(trained_policy_result, test_seeds=[10, 20, 30])
    for seed_result in report.per_seed_results:
        bootstrap = seed_result.bootstrap
        assert bootstrap.ci_low <= bootstrap.ci_high
        assert bootstrap.confidence == 0.95
        assert bootstrap.n_resamples == 500


def test_all_seeds_exclude_zero_same_direction_matches_manual_check(trained_policy_result) -> None:
    report = _run(trained_policy_result, test_seeds=[1, 2, 3])
    manual = all(r.bootstrap.excludes_zero() for r in report.per_seed_results) and (
        len({np.sign(r.bootstrap.point_estimate) for r in report.per_seed_results}) == 1
    )
    assert report.all_seeds_exclude_zero_same_direction() == manual


def test_empty_seed_list_rejected(trained_policy_result) -> None:
    with pytest.raises(ValueError):
        _run(trained_policy_result, test_seeds=[])


def test_mean_point_estimate_matches_manual_average(trained_policy_result) -> None:
    report = _run(trained_policy_result, test_seeds=[5, 6, 7])
    manual_mean = float(np.mean([r.bootstrap.point_estimate for r in report.per_seed_results]))
    assert report.mean_point_estimate() == pytest.approx(manual_mean)


@pytest.mark.parametrize("seeds", [[100, 100], [True], [-1]])
def test_duplicate_or_invalid_evaluation_seeds_are_rejected(trained_policy_result, seeds) -> None:
    with pytest.raises(ValueError):
        _run(trained_policy_result, test_seeds=seeds)
