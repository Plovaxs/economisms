"""PR-219: the neural SDE recipe tuning study.

Unit tests of the parts, plus the committed study output checked for the properties the selection
rule promises (not for a particular winner).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from prometheus.confirmatory.e4_shocks import EVENTS, _examples
from prometheus.orchestration import neural_sde_tuning_study as study
from prometheus.orchestration.neural_sde_run import DEFAULT_CSV_PATH

COMMITTED = Path(__file__).resolve().parents[2] / "docs" / "numerics" / "neural_sde_tuning.json"


@pytest.fixture(scope="module")
def parts() -> study.Parts:
    return study.split_before_the_first_shock(_examples(DEFAULT_CSV_PATH))


def test_the_grid_has_thirty_six_distinct_recipes_and_the_current_one_comes_first() -> None:
    grid = study.recipe_grid()
    assert len(grid) == len(set(grid)) == 36
    assert grid[0] == study.DEFAULT == study.Recipe(0.01, 16, 300, 20)


def test_no_part_reaches_the_earliest_shock_window(parts: study.Parts) -> None:
    first_shock = min(e.start for e in EVENTS)
    for part in (parts.train, parts.early_stopping, parts.selection, parts.check):
        assert part
        assert all(e.decision_time < first_shock for e in part)


def test_the_parts_are_chronological_and_do_not_overlap(parts: study.Parts) -> None:
    ordered = [parts.train, parts.early_stopping, parts.selection, parts.check]
    bounds = [(min(e.decision_time for e in p), max(e.decision_time for e in p)) for p in ordered]
    for (_, end), (start, _) in zip(bounds, bounds[1:], strict=False):
        assert end < start


def test_the_reserved_e4_seeds_are_refused() -> None:
    with pytest.raises(ValueError, match="reserved"):
        study.refuse_reserved([20_000])
    assert not set(study.SELECTION_SEEDS) & set(study.CHECK_SEEDS)
    study.refuse_reserved([*study.SELECTION_SEEDS, *study.CHECK_SEEDS])


def test_overlapping_selection_and_check_seeds_are_refused() -> None:
    with pytest.raises(ValueError, match="disjoint"):
        study.run_study(selection_seeds=[1, 2], check_seeds=[2, 3], grid=[study.DEFAULT])


def test_selection_takes_the_lowest_score_and_breaks_ties_toward_the_earlier() -> None:
    a, b, c = (
        study.Recipe(0.01, 16, 300, 20),
        study.Recipe(0.03, 16, 300, 20),
        study.Recipe(0.003, 16, 300, 20),
    )
    assert study.select({a: 3.0, b: 2.0, c: 2.0}, [a, b, c]) == b
    assert study.select({a: 2.0, b: 2.0, c: 3.0}, [a, b, c]) == a


@pytest.mark.parametrize(
    ("low", "high", "expected"),
    [(-0.5, -0.1, "SUPPORTED"), (0.1, 0.5, "CONTRADICTED"), (-0.1, 0.1, "INCONCLUSIVE")],
)
def test_a_lower_log_score_is_better(low: float, high: float, expected: str) -> None:
    assert study.verdict_below_zero(low, high) == expected


def test_monthly_scores_are_deterministic_in_the_seed_and_one_per_month(
    parts: study.Parts,
) -> None:
    recipe = study.Recipe(0.01, 8, 5, 3)
    first, gbm = study.monthly_scores(parts, recipe, 100, parts.check)
    again, _ = study.monthly_scores(parts, recipe, 100, parts.check)
    other, _ = study.monthly_scores(parts, recipe, 101, parts.check)
    assert first.shape == gbm.shape == (len(parts.check),)
    np.testing.assert_array_equal(first, again)
    assert not np.array_equal(first, other)


def test_a_tiny_end_to_end_run_reports_both_questions() -> None:
    grid = [study.Recipe(0.01, 8, 5, 3), study.Recipe(0.03, 8, 5, 3)]
    report = study.run_study(
        selection_seeds=[100], check_seeds=[200, 201], grid=grid, block_resamples=50
    )
    assert set(report["comparisons"]) == {"N-A_selected_vs_default", "N-B_selected_vs_constant_gbm"}
    scores = [g["mean_selection_log_score"] for g in report["grid"]]
    assert scores == sorted(scores)
    assert report["grid"][0]["recipe"] == report["config"]["selected_name"]


@pytest.mark.skipif(not COMMITTED.exists(), reason="committed study output is absent")
def test_the_committed_report_is_internally_consistent() -> None:
    report = json.loads(COMMITTED.read_text())
    scores = [g["mean_selection_log_score"] for g in report["grid"]]
    assert len(scores) == 36 and scores == sorted(scores)
    assert report["config"]["last_decision_time_used"] < min(e.start for e in EVENTS).isoformat()
    for row in report["comparisons"].values():
        assert row["ci_low"] <= row["score_difference_first_minus_second"] <= row["ci_high"]
