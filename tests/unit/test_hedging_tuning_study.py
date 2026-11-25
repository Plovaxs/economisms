"""PR-218: the deep-hedging recipe tuning study.

Unit tests of the parts on tiny problems, plus the committed study output checked for the
properties the selection rule promises (not for a particular winner).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from prometheus.confirmatory.e1_hedging import evaluate_seed
from prometheus.hedging.rl_agent import HedgeRLPolicyNet
from prometheus.orchestration import hedging_tuning_study as study

COMMITTED = Path(__file__).resolve().parents[2] / "docs" / "numerics" / "hedging_tuning.json"


def test_the_grid_has_thirty_six_distinct_recipes_and_the_default_comes_first() -> None:
    grid = study.recipe_grid()
    assert len(grid) == len(set(grid)) == 36
    assert grid[0] == study.DEFAULT == study.Recipe(0.01, 400, 16, 0.0)


def test_the_default_recipe_is_the_runner_default() -> None:
    from prometheus.orchestration.rl_hedge_run import RlHedgeRunConfig

    config = RlHedgeRunConfig()
    assert (config.learning_rate, config.n_epochs) == (study.DEFAULT.learning_rate, 400)
    assert HedgeRLPolicyNet().mu_head.in_features == study.DEFAULT.hidden_size
    assert float(HedgeRLPolicyNet().log_std) == study.DEFAULT.initial_log_std


def test_width_and_initial_exploration_reach_the_network() -> None:
    net = HedgeRLPolicyNet(hidden_size=64, initial_log_std=-1.0)
    assert net.mu_head.in_features == 64
    assert float(net.log_std) == -1.0


@pytest.mark.parametrize("seed", [10000, 10049, 20000, 20009])
def test_reserved_confirmatory_seeds_are_refused(seed: int) -> None:
    with pytest.raises(ValueError, match="reserved"):
        study.refuse_reserved([seed])
    with pytest.raises(ValueError, match="reserved"):
        study.evaluate_recipe(seed, study.DEFAULT)


def test_the_study_seeds_avoid_every_reserved_and_earlier_seed() -> None:
    seeds = {*study.SELECTION_SEEDS, *study.VALIDATION_SEEDS}
    assert not seeds & {s for block in study.RESERVED for s in block}
    assert not set(study.SELECTION_SEEDS) & set(study.VALIDATION_SEEDS)
    assert min(seeds) > 7  # Finding 8 used seeds 0-7


def test_overlapping_selection_and_validation_seeds_are_refused() -> None:
    with pytest.raises(ValueError, match="disjoint"):
        study.run_study(selection_seeds=[1, 2], validation_seeds=[2, 3], grid=[study.DEFAULT])


def test_the_default_recipe_reproduces_the_e1_endpoint_exactly() -> None:
    """The study's training and scoring are E1's: same ratio, to the last digit, on a short run."""
    short = study.Recipe(0.01, 6, 16, 0.0)
    theta = study.evaluate_recipe(1000, short, n_eval_paths=500)
    e1 = evaluate_seed(1000, n_epochs=6, learning_rate=0.01, n_eval_paths=500)
    assert theta == pytest.approx(-math.log(e1.ratio), rel=1e-12, abs=1e-12)


def test_selection_takes_the_highest_mean_and_breaks_ties_toward_the_earlier() -> None:
    a, b, c = (
        study.Recipe(0.01, 400, 16, 0.0),
        study.Recipe(0.03, 400, 16, 0.0),
        study.Recipe(0.003, 400, 16, 0.0),
    )
    assert study.select({a: 0.1, b: 0.3, c: 0.3}, [a, b, c]) == b
    assert study.select({a: 0.3, b: 0.3, c: 0.1}, [a, b, c]) == a


@pytest.mark.parametrize(
    ("low", "high", "expected"),
    [(0.01, 0.2, "SUPPORTED"), (-0.2, -0.01, "CONTRADICTED"), (-0.1, 0.1, "INCONCLUSIVE")],
)
def test_the_verdict_is_decided_by_which_side_of_zero_the_interval_lies(
    low: float, high: float, expected: str
) -> None:
    assert study.verdict_above_zero(low, high) == expected


def test_a_tiny_end_to_end_run_reports_both_questions() -> None:
    grid = [study.Recipe(0.01, 4, 8, 0.0), study.Recipe(0.03, 4, 8, -1.0)]
    report = study.run_study(
        selection_seeds=[1000, 1001],
        validation_seeds=[3000, 3001, 3002],
        grid=grid,
        workers=1,
        n_eval_paths=300,
        prior_winner=grid[1],
    )
    assert set(report["hypotheses"]) == {
        "H-A_selected_beats_default",
        "H-B_selected_beats_static_baseline",
        "H-C_selected_beats_round1_winner",
    }
    ranked = [g["mean_theta"] for g in report["grid"]]
    assert ranked == sorted(ranked, reverse=True)
    assert report["grid"][0]["recipe"] == report["config"]["selected_name"]
    for row in report["hypotheses"].values():
        assert row["verdict"] in {"SUPPORTED", "CONTRADICTED", "INCONCLUSIVE"}


@pytest.mark.skipif(not COMMITTED.exists(), reason="committed study output is absent")
def test_the_committed_report_is_internally_consistent() -> None:
    report = json.loads(COMMITTED.read_text())
    ranked = [g["mean_theta"] for g in report["grid"]]
    assert len(ranked) == 36 and ranked == sorted(ranked, reverse=True)
    assert report["grid"][0]["recipe"] == report["config"]["selected_name"] or (
        report["config"]["selected_name"] == study.DEFAULT.name
        and report["grid"][0]["mean_theta"] == report["grid"][1]["mean_theta"]
    )
    seeds = report["config"]["selection_seeds"] + report["config"]["validation_seeds"]
    assert not any(10000 <= s < 10050 or 20000 <= s < 20010 for s in seeds)
    interval = report["validation"]["paired_difference_interval"]
    assert interval["low"] <= interval["estimate"] <= interval["high"]
    expected = np.mean(
        np.array(report["validation"]["theta_selected"])
        - np.array(report["validation"]["theta_default"])
    )
    assert interval["estimate"] == pytest.approx(expected)


def test_round_two_extends_the_grid_toward_smaller_steps_and_longer_training() -> None:
    grid = study.round2_grid()
    assert len(grid) == len(set(grid)) == 12
    assert study.ROUND1_WINNER in grid
    assert min(r.learning_rate for r in grid) < study.ROUND1_WINNER.learning_rate
    assert max(r.n_epochs for r in grid) > study.ROUND1_WINNER.n_epochs
    new = set(study.ROUND2_VALIDATION_SEEDS)
    assert not new & set(study.VALIDATION_SEEDS) and not new & set(study.SELECTION_SEEDS)
    study.refuse_reserved(list(new))
