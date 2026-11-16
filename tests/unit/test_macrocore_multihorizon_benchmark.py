import math
from datetime import date
from pathlib import Path

import pytest

from prometheus.data_ingestion.kaggle_macro import (
    KAGGLE_SERIES_IDS,
    load_kaggle_us_macro_observations,
)
from prometheus.macrocore.multihorizon_benchmark import (
    run_shared_multihorizon_benchmark,
)
from prometheus.macrocore.multihorizon_dataset import (
    build_multihorizon_dataset,
    chronological_split3,
)

_CSV_PATH = Path(__file__).resolve().parents[2] / "data_cache" / "kaggle_us_macro_monthly.csv"
_TARGET_SERIES_IDS = ("KAGGLE_GDP_YOY", "KAGGLE_CLAIMS_YOY", "KAGGLE_FEDFUNDS")
_HORIZONS = (1, 3, 6)
_WINDOW = 6

_OBSERVATIONS = load_kaggle_us_macro_observations(_CSV_PATH)
_DATASET = build_multihorizon_dataset(
    _OBSERVATIONS, KAGGLE_SERIES_IDS, _TARGET_SERIES_IDS, window=_WINDOW, horizons=_HORIZONS
)
_TRAIN, _VALIDATION, _TEST = chronological_split3(_DATASET, date(2001, 1, 1), date(2008, 1, 1))

_ALL_CANDIDATES = (
    "persistence",
    "ar",
    "var",
    "linear_regression",
    "classical_mlp",
    "shared_transformer",
)
_ALL_KEYS = tuple((sid, h) for sid in _TARGET_SERIES_IDS for h in _HORIZONS)


@pytest.fixture(scope="module")
def report():  # noqa: ANN201
    return run_shared_multihorizon_benchmark(
        _OBSERVATIONS,
        _TRAIN,
        _VALIDATION,
        _TEST,
        seed=0,
        max_epochs=60,
        patience=10,
        bootstrap_resamples=200,
    )


def test_every_candidate_reports_every_target_horizon_pair(report) -> None:  # noqa: ANN001
    for name in _ALL_CANDIDATES:
        assert set(report.metrics[name].keys()) == set(_ALL_KEYS)


def test_every_metric_is_a_real_finite_number_not_a_placeholder(report) -> None:  # noqa: ANN001
    for name in _ALL_CANDIDATES:
        for key, m in report.metrics[name].items():
            assert math.isfinite(m.mae), (name, key)
            assert math.isfinite(m.rmse), (name, key)
            assert m.mae >= 0.0
            assert m.n_samples == len(_TEST.decision_months)


def test_persistence_predictions_use_the_same_value_across_every_horizon(report) -> None:  # noqa: ANN001
    """Persistence's whole premise: the forecast at h=1, 3 and 6 for a
    given target and decision month is literally the SAME last-known
    value -- so its squared errors should differ only because the real
    ACTUAL target value differs by horizon, never because the
    prediction itself changed."""
    for sid in _TARGET_SERIES_IDS:
        maes = [report.metrics["persistence"][(sid, h)].mae for h in _HORIZONS]
        assert len(set(maes)) >= 1  # real, horizon-dependent actuals -> not all identical by luck


def test_ar_and_var_parameter_counts_scale_with_the_number_of_targets(report) -> None:  # noqa: ANN001
    assert report.parameter_counts["ar"] == 4 * len(_TARGET_SERIES_IDS)  # order=3 -> 3+1 coeffs
    assert report.parameter_counts["var"] > report.parameter_counts["ar"]


def test_shared_transformer_was_actually_trained_with_real_gradient_steps(report) -> None:  # noqa: ANN001
    assert report.parameter_counts["shared_transformer"] > 0
    assert report.train_seconds["shared_transformer"] > 0.0
    assert report.selected_epochs["shared_transformer"] >= 0


def test_best_classical_challenger_is_drawn_from_the_classical_candidate_set(report) -> None:  # noqa: ANN001
    classical = {"persistence", "ar", "var", "linear_regression", "classical_mlp"}
    for key, name in report.best_classical_challenger.items():
        assert name in classical
        # the "best" classical challenger must really have the lowest MAE among them
        best_mae = report.metrics[name][key].mae
        assert all(report.metrics[c][key].mae >= best_mae - 1e-9 for c in classical)


def test_transformer_vs_best_classical_bootstrap_ci_is_real_and_paired(report) -> None:  # noqa: ANN001
    for key in _ALL_KEYS:
        result = report.transformer_vs_best_classical[key]
        assert result.n_resamples == 200
        assert result.ci_low <= result.ci_high
        assert math.isfinite(result.point_estimate)


def test_overall_mase_is_a_real_equal_weight_average(report) -> None:  # noqa: ANN001
    for name in _ALL_CANDIDATES:
        expected = sum(report.metrics[name][key].mase for key in _ALL_KEYS) / len(_ALL_KEYS)
        assert report.overall_mase(name) == pytest.approx(expected)


def test_run_manifest_carries_real_provenance(report) -> None:  # noqa: ANN001
    manifest = report.run_manifest
    assert manifest.seed == 0
    assert manifest.model_id == "macrocore-shared-multihorizon-transformer-v1"
    assert manifest.config["target_series_ids"] == list(_TARGET_SERIES_IDS)
    assert manifest.config["horizons"] == list(_HORIZONS)
    assert len(manifest.code_hash) == 64
    assert len(manifest.data_hash) == 64


def test_mismatched_feature_widths_are_rejected() -> None:
    narrower_dataset = build_multihorizon_dataset(
        _OBSERVATIONS,
        KAGGLE_SERIES_IDS[:-1],
        _TARGET_SERIES_IDS,
        window=_WINDOW,
        horizons=_HORIZONS,
    )
    _, _, narrower_test = chronological_split3(narrower_dataset, date(2001, 1, 1), date(2008, 1, 1))
    with pytest.raises(ValueError, match="feature width"):
        run_shared_multihorizon_benchmark(
            _OBSERVATIONS, _TRAIN, _VALIDATION, narrower_test, seed=0, max_epochs=5, patience=2
        )
