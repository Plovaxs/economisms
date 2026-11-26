"""E1: the hedging policy against the static baseline, scored on held-out paths.

Training is real (the runner's own `run_rl_hedge`) but kept tiny here; what is pinned is the part
this module adds: that the held-out paths are independent of the training ones and shared by both
hedges, that the static baseline is computed exactly as the runner computes it, and that the
endpoint's arithmetic and sign are right. The reserved seeds are guarded in the freeze tests. The
reproduction of Finding 8 on its eight seeds takes minutes and is run by
`python -m prometheus.confirmatory reproduce`.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from prometheus.confirmatory.__main__ import reproduce_e1
from prometheus.confirmatory.e1_hedging import (
    MARGIN,
    SeedResult,
    analyse,
    evaluate_seed,
    evaluation_paths,
    simulate_paths,
    static_hedge_loss,
    tail_cvar,
)
from prometheus.confirmatory.intervals import t_interval
from prometheus.orchestration.rl_hedge_run import RlHedgeRunConfig, run_rl_hedge

_SMALL = {"n_epochs": 3, "n_paths": 300, "n_eval_paths": 800}


def _result(seed: int, ratio: float, in_sample: float = 1.1) -> SeedResult:
    return SeedResult(
        seed=seed,
        n_epochs=400,
        static_cvar=8.0,
        policy_cvar=8.0 * ratio,
        ratio=ratio,
        in_sample_ratio=in_sample,
    )


def test_the_tail_cvar_is_the_runners_formula() -> None:
    losses = np.arange(100.0)
    assert tail_cvar(losses, 0.95) == pytest.approx(np.mean(np.arange(95.0, 100.0)))
    assert tail_cvar(np.array([3.0, 1.0, 2.0]), 0.999) == 3.0  # no tail left: the worst loss
    assert tail_cvar(np.array([5.0, 1.0]), 0.5) == 5.0


def test_the_static_baseline_is_computed_exactly_as_the_runner_computes_it() -> None:
    config = RlHedgeRunConfig(seed=4, n_epochs=2, n_paths=300)
    run = run_rl_hedge(config)
    training_paths = simulate_paths(config, config.n_paths, np.random.default_rng(config.seed))
    mine = tail_cvar(static_hedge_loss(config, training_paths), config.cvar_alpha)
    assert mine == run.static_baseline_cvar


def test_the_held_out_paths_are_not_the_training_paths_and_are_reproducible() -> None:
    config = RlHedgeRunConfig(seed=4, n_paths=300)
    training = simulate_paths(config, config.n_paths, np.random.default_rng(config.seed))
    held_out = evaluation_paths(config, 300)
    assert held_out.shape == training.shape
    assert not np.allclose(held_out[:, 1:], training[:, 1:])
    np.testing.assert_array_equal(held_out, evaluation_paths(config, 300))
    other_seed = evaluation_paths(RlHedgeRunConfig(seed=5, n_paths=300), 300)
    assert not np.allclose(held_out[:, 1:], other_seed[:, 1:])


def test_a_seed_is_scored_on_held_out_paths_and_is_deterministic() -> None:
    first = evaluate_seed(2, **_SMALL)
    again = evaluate_seed(2, **_SMALL)
    assert first == again
    assert first.n_epochs == 3
    assert first.ratio == pytest.approx(first.policy_cvar / first.static_cvar)
    assert all(
        math.isfinite(x) for x in (first.static_cvar, first.policy_cvar, first.in_sample_ratio)
    )
    assert first.static_cvar > 0.0
    other = evaluate_seed(3, **_SMALL)
    assert other.ratio != first.ratio


def test_theta_is_minus_the_mean_log_ratio_so_positive_favours_the_policy() -> None:
    ratios = [1.10, 1.12, 1.08, 1.11, 1.09, 1.10, 1.13]
    report = analyse([_result(i, r) for i, r in enumerate(ratios)], confidence=0.98)
    expected = t_interval(-np.log(ratios), 0.98)
    assert report["interval"]["estimate"] == pytest.approx(expected.estimate)
    assert report["interval"]["estimate"] < 0.0
    assert report["outcome"] == "worse"
    assert report["n_seeds"] == 7 and report["n_seeds_policy_better"] == 0
    assert report["median_ratio"] == pytest.approx(1.10)
    assert report["margin"] == MARGIN == pytest.approx(math.log(1.05))


def test_the_three_outcomes_a_set_of_ratios_can_produce() -> None:
    better = analyse(
        [_result(i, r) for i, r in enumerate([0.80, 0.82, 0.79, 0.81, 0.80])], confidence=0.98
    )
    assert better["outcome"] == "better" and better["n_seeds_policy_better"] == 5
    level = analyse(
        [_result(i, r) for i, r in enumerate([0.99, 1.01, 1.0, 1.005, 0.995])], confidence=0.98
    )
    assert level["outcome"] == "equivalent"  # the whole interval sits inside +/- ln(1.05)
    noisy = analyse(
        [_result(i, r) for i, r in enumerate([0.7, 1.4, 0.9, 1.3, 1.0])], confidence=0.98
    )
    assert noisy["outcome"] == "inconclusive"


def test_the_in_sample_statistic_of_finding_8_is_kept_beside_the_new_one() -> None:
    results = [_result(0, 1.05, in_sample=1.04), _result(1, 1.06, in_sample=1.41)]
    report = analyse(results, confidence=0.9)
    assert report["in_sample_ratio_min"] == 1.04 and report["in_sample_ratio_max"] == 1.41
    assert report["n_seeds_policy_better_in_sample"] == 0
    assert [row["seed"] for row in report["per_seed"]] == [0, 1]


def test_the_endpoint_refuses_what_it_cannot_compute() -> None:
    with pytest.raises(ValueError, match="at least two seeds"):
        analyse([_result(0, 1.1)], confidence=0.98)
    with pytest.raises(ValueError, match="non-positive"):
        analyse([_result(0, 1.1), _result(1, -0.2)], confidence=0.98)
    with pytest.raises(ValueError, match="non-positive"):
        analyse([_result(0, 1.1), _result(1, float("nan"))], confidence=0.98)


def test_a_reduced_reproduction_reports_without_claiming_a_comparison() -> None:
    report = reproduce_e1(seeds=(0,), epochs=(2,))
    assert "checks" not in report  # one seed and two epochs are not Finding 8's setting
    assert set(report["in_sample_ratio_by_epochs"]) == {"2"}
    assert len(report["held_out_ratio_by_epochs"]["2"]) == 1


class _Stop(Exception):
    pass


def test_the_frozen_recipe_is_the_delta_rebalance_one_and_the_legacy_recipe_stays_reproducible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from prometheus.confirmatory import e1_hedging

    trained: list[tuple[RlHedgeRunConfig, dict[str, object]]] = []
    legacy_runs: list[RlHedgeRunConfig] = []

    def capture_train(config: RlHedgeRunConfig, **kwargs: object) -> None:
        trained.append((config, kwargs))
        raise _Stop

    def capture_run(config: RlHedgeRunConfig) -> None:
        legacy_runs.append(config)
        raise _Stop

    monkeypatch.setattr(e1_hedging, "train_policy", capture_train)
    monkeypatch.setattr(e1_hedging, "run_rl_hedge", capture_run)
    with pytest.raises(_Stop):
        e1_hedging.evaluate_seed(5)
    with pytest.raises(_Stop):
        e1_hedging.evaluate_seed(5, **e1_hedging.LEGACY_KWARGS)
    [(frozen_config, frozen_kwargs)] = trained
    [legacy] = legacy_runs
    assert (frozen_config.learning_rate, frozen_config.n_epochs) == (0.003, 400)
    assert frozen_kwargs == {
        "hidden_size": 16,
        "initial_log_std": -1.0,
        "structure": "delta_rebalance",
    }
    assert legacy == RlHedgeRunConfig(seed=5)  # the runner's own defaults are the legacy recipe
    assert e1_hedging.LEGACY_KWARGS["structure"] == "plain"


def test_the_tuning_study_and_the_frozen_pipeline_compute_the_same_number() -> None:
    """The structured recipe the study selected is scored by E1's own code, to the last digit."""
    from prometheus.confirmatory import e1_hedging
    from prometheus.orchestration import hedging_tuning_study as study

    recipe = study.Recipe(0.003, 4, 16, -1.0, "delta_rebalance")
    theta = study.evaluate_recipe(5000, recipe, n_eval_paths=400)
    result = e1_hedging.evaluate_seed(
        5000,
        n_epochs=4,
        learning_rate=0.003,
        structure="delta_rebalance",
        initial_log_std=-1.0,
        n_eval_paths=400,
    )
    assert theta == pytest.approx(-math.log(result.ratio), rel=1e-12, abs=1e-12)


def test_the_frozen_recipe_is_pinned_so_a_change_after_the_freeze_is_noticed() -> None:
    """The recorded recipe hash: editing a frozen field changes it, and this test with it."""
    from prometheus.confirmatory import e1_hedging

    recipe = e1_hedging.frozen_recipe()
    assert "seed" not in recipe
    assert recipe["policy_structure"] == "delta_rebalance"
    assert (recipe["learning_rate"], recipe["n_epochs"]) == (0.003, 400)
    assert (recipe["hidden_size"], recipe["initial_log_std"]) == (16, -1.0)
    assert e1_hedging.frozen_recipe_hash() == (
        "13656c91316c85e1f1c2679705ffbb3638f2a6eb5021fb0960e2f7e59f9c5514"
    )
