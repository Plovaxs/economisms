"""PR-198: the RECESSIONNET "more data" study.

Hermetic helper tests on synthetic observations, plus ONE real run of the whole study
(four feature sets x five seeds, a few dozen seconds) whose qualitative findings are
asserted with generous margins -- the same "re-runnable finding, not a one-off script"
discipline as the other RESULTS_AND_LIMITATIONS findings.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from prometheus.econosim.pit import MacroObservation
from prometheus.orchestration.recessionnet_extended_study import (
    MODELS,
    build_feature_sets,
    common_first_row,
    main,
    month_ends,
    run_study,
    trim_observations,
)


def _obs(series: str, row: date, value: float = 1.0) -> MacroObservation:
    return MacroObservation(series_id=series, observation_at=row, published_at=row, value=value)


def test_month_ends_lists_every_month_end_inclusively() -> None:
    rows = month_ends(date(2020, 11, 30), date(2021, 2, 28))
    assert rows == [date(2020, 11, 30), date(2020, 12, 31), date(2021, 1, 31), date(2021, 2, 28)]


def test_trim_observations_keeps_only_wanted_series_inside_the_window() -> None:
    rows = month_ends(date(2020, 1, 31), date(2020, 4, 30))
    observations = [_obs(s, r) for s in ("A", "B", "C") for r in rows]
    kept = trim_observations(observations, ("A", "B"), date(2020, 2, 29), date(2020, 3, 31))
    assert {o.series_id for o in kept} == {"A", "B"}
    assert {o.observation_at for o in kept} == {date(2020, 2, 29), date(2020, 3, 31)}


def test_trim_observations_fails_loudly_when_a_series_has_a_gap() -> None:
    rows = month_ends(date(2020, 1, 31), date(2020, 4, 30))
    observations = [_obs("A", r) for r in rows] + [_obs("B", r) for r in rows if r.month != 3]
    with pytest.raises(ValueError, match="B has no value for 1 months, first 2020-03-31"):
        trim_observations(observations, ("A", "B"), rows[0], rows[-1])


def test_common_first_row_is_the_latest_series_start() -> None:
    observations = [
        _obs("A", date(1960, 1, 31)),
        _obs("B", date(1974, 2, 28)),
        _obs("B", date(1975, 2, 28)),
    ]
    assert common_first_row(observations, ("A", "B")) == date(1974, 2, 28)


@pytest.fixture(scope="module")
def study() -> dict:  # type: ignore[type-arg]
    return run_study(build_feature_sets(), seeds=[0, 1, 2, 3, 4], block_resamples=1000)


def test_the_four_feature_sets_have_the_designed_widths_windows_and_history(study) -> None:  # noqa: ANN001
    sets = study["feature_sets"]
    assert {k: len(v["series_ids"]) for k, v in sets.items()} == {
        "baseline_5": 5,
        "macro_5_short": 5,
        "macro_5_long": 5,
        "extended_11": 11,
    }
    assert sets["macro_5_long"]["first_row"] == "1968-02-29"
    for name in ("baseline_5", "macro_5_short", "extended_11"):
        assert sets[name]["first_row"] == "1981-12-31"
    # MORE HISTORY means more recession episodes (and positives) to learn from:
    assert (
        sets["macro_5_long"]["n_train_recession_episodes"]
        > sets["baseline_5"]["n_train_recession_episodes"]
    )
    assert sets["macro_5_long"]["n_train_positive"] > 4 * sets["baseline_5"]["n_train_positive"]


def test_every_feature_set_is_scored_on_exactly_the_same_test_months(study) -> None:  # noqa: ANN001
    sets = study["feature_sets"]
    assert {v["n_test"] for v in sets.values()} == {175}
    assert {v["n_test_positive"] for v in sets.values()} == {14}
    assert {v["n_validation"] for v in sets.values()} == {84}


def test_the_report_is_json_serialisable_and_complete(study) -> None:  # noqa: ANN001
    json.dumps(study)
    assert set(study["results"]) == set(study["feature_sets"])
    assert all(set(r) == set(MODELS) for r in study["results"].values())
    assert set(study["comparisons"]) == {"more_history", "more_features", "feature_swap_only"}
    allowed = {"lower_brier_first_is_better", "higher_brier_first_is_worse", "inconclusive"}
    for comparison in study["comparisons"].values():
        for result in comparison["models"].values():
            assert result["verdict"] in allowed
            assert result["ci_low"] <= result["ci_high"]
    assert len(study["caveats"]) == 3


def test_more_history_helps_the_logistic_regression_on_the_same_test_months(study) -> None:  # noqa: ANN001
    """The data lever that works: with the features held fixed, going from 3 to 6
    training recession episodes lowers the logistic regression's test Brier score by
    about 0.05 and raises its ROC-AUC by about 0.08 (5-seed means)."""
    short = study["results"]["macro_5_short"]["logistic_regression"]
    long = study["results"]["macro_5_long"]["logistic_regression"]
    assert long["brier_mean"] < short["brier_mean"] - 0.02
    assert long["auc_mean"] > short["auc_mean"] + 0.04
    delta = study["comparisons"]["more_history"]["models"]["logistic_regression"]
    assert delta["delta_brier_first_minus_second"] < -0.02


def test_more_features_does_not_improve_brier_and_hurts_the_matched_mlp(study) -> None:  # noqa: ANN001
    """The lever that does not: adding six features to the same short history leaves
    the learned models' Brier score no better (the matched MLP is worse, with an
    interval that excludes zero) even though some rankings (ROC-AUC) improve -- the
    same Brier-versus-AUC tension Finding 3 documents. Consistent with Finding 12."""
    baseline = study["results"]["baseline_5"]
    extended = study["results"]["extended_11"]
    assert (
        extended["classical_matched_mlp"]["brier_mean"]
        > baseline["classical_matched_mlp"]["brier_mean"]
    )
    for model in ("logistic_regression", "classical_matched_mlp", "hybrid_quantum"):
        assert extended[model]["brier_mean"] >= baseline[model]["brier_mean"] - 0.005
    assert (
        study["comparisons"]["more_features"]["models"]["base_rate"][
            "delta_brier_first_minus_second"
        ]
        == 0.0
    )


def test_no_learned_model_at_the_baseline_is_certified_better_than_the_base_rate_by_brier_alone(
    study,  # noqa: ANN001
) -> None:
    """A guard on over-reading: the logistic regression never beats the base rate's
    Brier score in any configuration (it ranks well but is over-confident)."""
    for name, results in study["results"].items():
        assert results["logistic_regression"]["brier_mean"] > results["base_rate"]["brier_mean"], (
            name
        )


def test_main_writes_the_report_for_a_tiny_configuration(tmp_path: Path) -> None:
    out = tmp_path / "report.json"
    code = main(
        [
            "--seeds",
            "1",
            "--max-epochs",
            "8",
            "--patience",
            "3",
            "--bootstrap-resamples",
            "50",
            "--output",
            str(out),
        ]
    )
    assert code == 0
    report = json.loads(out.read_text())
    assert report["config"]["seeds"] == [0] and report["config"]["max_epochs"] == 8


def test_main_rejects_a_non_positive_seed_count() -> None:
    with pytest.raises(SystemExit):
        main(["--seeds", "0"])
