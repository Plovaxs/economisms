import calendar
import csv
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from prometheus.econosim.pit import MacroObservation
from prometheus.macrocore.quantum_benchmark import (
    RegressionMetrics,
    _in_sample_naive_mae,
    evaluate_ar,
    evaluate_persistence,
    run_qmacro_benchmark,
)
from prometheus.macrocore.regression_dataset import (
    build_macro_regression_dataset,
    chronological_split,
    extract_target_history,
)

_FIXTURE_CSV = Path(__file__).resolve().parents[1] / "fixtures" / "ff3_monthly_real.csv"
_FEATURE_SERIES_IDS = ("FF3_Mkt-RF", "FF3_SMB", "FF3_HML", "FF3_RF")
_TARGET_SERIES_ID = "FF3_Mkt-RF"


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _load_real_ff3_observations() -> list[MacroObservation]:
    observations: list[MacroObservation] = []
    with _FIXTURE_CSV.open() as f:
        for row in csv.DictReader(f):
            year, month = int(row["date"][:4]), int(row["date"][4:6])
            observation_at = _month_end(year, month)
            for factor in ("Mkt-RF", "SMB", "HML", "RF"):
                observations.append(
                    MacroObservation(
                        series_id=f"FF3_{factor}",
                        observation_at=observation_at,
                        published_at=observation_at,
                        value=float(row[factor]),
                    )
                )
    return observations


_REAL_OBSERVATIONS = _load_real_ff3_observations()


def _real_three_way_split():
    dataset = build_macro_regression_dataset(
        _REAL_OBSERVATIONS, _FEATURE_SERIES_IDS, _TARGET_SERIES_ID, window=6, horizon=6
    )
    train_full, test = chronological_split(dataset, date(2000, 1, 1))
    train_proper, validation = chronological_split(train_full, date(1988, 1, 1))
    return train_proper, validation, test


def test_in_sample_naive_mae_rejects_a_too_short_series() -> None:
    with pytest.raises(ValueError, match="at least 2 values"):
        _in_sample_naive_mae(np.array([1.0]))


def test_evaluate_persistence_matches_a_hand_computed_naive_baseline() -> None:
    train_proper, _, test = _real_three_way_split()
    naive_mae = float(abs(train_proper.targets[1:] - train_proper.targets[:-1]).mean())
    metrics = evaluate_persistence(test, naive_mae)
    assert isinstance(metrics, RegressionMetrics)
    assert metrics.n_samples == len(test.targets)
    assert metrics.mae == pytest.approx(
        abs(test.most_recent_target_values - test.targets).mean()
    )


def test_evaluate_ar_refits_at_every_real_test_decision_month() -> None:
    train_proper, _, test = _real_three_way_split()
    months, values = extract_target_history(_REAL_OBSERVATIONS, _TARGET_SERIES_ID)
    naive_mae = float(abs(train_proper.targets[1:] - train_proper.targets[:-1]).mean())
    metrics = evaluate_ar(test, months, values, order=3, naive_mae=naive_mae)
    assert metrics.n_samples == len(test.targets)
    assert metrics.mae > 0
    assert metrics.mase > 0


def test_run_qmacro_benchmark_end_to_end_on_real_data() -> None:
    """The real Q-MACRO demonstration: real Kenneth French factors
    predicting real h-months-ahead Mkt-RF, five candidates (naive
    persistence, AR(3) genuinely refit at every test month, linear
    regression, a parameter-matched classical MLP and a hybrid quantum
    regressor, the last three selected by early stopping on a 1988-
    1999 validation split -- PR-142's methodology applied from the
    start rather than repeating its original mistake).

    Real, reproducible seed=0 result: AR(3)/classical MLP/hybrid
    quantum all land within a tight band (MAE ~0.034, MASE ~0.62),
    all clearly beating the naive persistence baseline (MASE ~0.89),
    and the paired bootstrap CI for quantum-vs-best-classical
    includes zero -- no significant difference among the
    sophisticated candidates on this task."""
    train_proper, validation, test = _real_three_way_split()
    months, values = extract_target_history(_REAL_OBSERVATIONS, _TARGET_SERIES_ID)

    report = run_qmacro_benchmark(
        train_proper, validation, test, months, values,
        seed=0, ar_order=3, max_epochs=500, patience=20, bootstrap_resamples=200,
    )

    assert set(report.metrics) == {
        "persistence",
        "ar",
        "linear_regression",
        "classical_matched_mlp",
        "hybrid_quantum",
    }
    for metrics in report.metrics.values():
        assert metrics.n_samples == len(test.targets)
        assert metrics.mae > 0

    # Every sophisticated candidate clearly beats the naive baseline.
    for name in ("ar", "linear_regression", "classical_matched_mlp", "hybrid_quantum"):
        assert report.metrics[name].mase < report.metrics["persistence"].mase

    # The real, locked-in seed=0 numbers (deterministic given the seed).
    assert report.metrics["ar"].mae == pytest.approx(0.03412, abs=0.001)
    assert report.metrics["hybrid_quantum"].mae == pytest.approx(0.03411, abs=0.001)
    assert abs(report.metrics["hybrid_quantum"].mae - report.metrics["ar"].mae) < 0.002

    assert report.parameter_counts["ar"] == 4  # ar_order + 1
    assert report.parameter_counts["persistence"] == 0
    assert set(report.selected_epochs) == {
        "linear_regression",
        "classical_matched_mlp",
        "hybrid_quantum",
    }
    assert all(epoch < 500 for epoch in report.selected_epochs.values())

    assert report.run_manifest.model_id == "qmacro-hybrid-quantum-v1"
    assert report.run_manifest.data_hash is not None
    assert report.run_manifest.code_hash is not None


def test_run_qmacro_benchmark_is_reproducible_given_the_same_seed() -> None:
    train_proper, validation, test = _real_three_way_split()
    months, values = extract_target_history(_REAL_OBSERVATIONS, _TARGET_SERIES_ID)

    report_a = run_qmacro_benchmark(
        train_proper, validation, test, months, values,
        seed=2, ar_order=3, max_epochs=50, patience=10, bootstrap_resamples=50,
    )
    report_b = run_qmacro_benchmark(
        train_proper, validation, test, months, values,
        seed=2, ar_order=3, max_epochs=50, patience=10, bootstrap_resamples=50,
    )
    assert report_a.selected_epochs == report_b.selected_epochs
    assert report_a.metrics["hybrid_quantum"].mae == pytest.approx(
        report_b.metrics["hybrid_quantum"].mae
    )


def test_run_qmacro_benchmark_rejects_mismatched_train_widths() -> None:
    narrow = build_macro_regression_dataset(
        _REAL_OBSERVATIONS, _FEATURE_SERIES_IDS, _TARGET_SERIES_ID, window=3, horizon=3
    )
    wide = build_macro_regression_dataset(
        _REAL_OBSERVATIONS, _FEATURE_SERIES_IDS, _TARGET_SERIES_ID, window=4, horizon=3
    )
    train_proper, validation = chronological_split(narrow, date(1988, 1, 1))
    _, test = chronological_split(wide, date(2000, 1, 1))
    months, values = extract_target_history(_REAL_OBSERVATIONS, _TARGET_SERIES_ID)
    with pytest.raises(ValueError, match="train_proper and test"):
        run_qmacro_benchmark(
            train_proper, validation, test, months, values, seed=0, max_epochs=5, patience=2
        )


def test_run_qmacro_benchmark_rejects_mismatched_validation_widths() -> None:
    narrow = build_macro_regression_dataset(
        _REAL_OBSERVATIONS, _FEATURE_SERIES_IDS, _TARGET_SERIES_ID, window=3, horizon=3
    )
    wide = build_macro_regression_dataset(
        _REAL_OBSERVATIONS, _FEATURE_SERIES_IDS, _TARGET_SERIES_ID, window=4, horizon=3
    )
    train_proper, _ = chronological_split(narrow, date(1988, 1, 1))
    _, validation = chronological_split(wide, date(1988, 1, 1))
    _, test = chronological_split(narrow, date(2000, 1, 1))
    months, values = extract_target_history(_REAL_OBSERVATIONS, _TARGET_SERIES_ID)
    with pytest.raises(ValueError, match="validation and test"):
        run_qmacro_benchmark(
            train_proper, validation, test, months, values, seed=0, max_epochs=5, patience=2
        )
