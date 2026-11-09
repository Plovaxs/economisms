import calendar
import csv
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from prometheus.econosim.pit import MacroObservation
from prometheus.quantum.models import LogisticRegressionClassifier
from prometheus.recessionnet.dataset import build_recession_dataset, chronological_split
from prometheus.recessionnet.evaluation import (
    calibration_slope_intercept,
    evaluate_constant_probability,
    evaluate_model,
    reliability_diagram,
    roc_auc,
    run_recessionnet_benchmark,
)
from prometheus.recessionnet.labels import NBER_RECESSIONS
from prometheus.recessionnet.training import train_classifier

_FIXTURE_CSV = Path(__file__).resolve().parents[1] / "fixtures" / "ff3_monthly_real.csv"
_SERIES_IDS = ("FF3_Mkt-RF", "FF3_SMB", "FF3_HML", "FF3_RF")


def _load_real_ff3_observations() -> list[MacroObservation]:
    """Duplicated (not cross-imported) from `test_recessionnet_dataset.py`,
    matching this project's established convention of not importing
    across test modules (see e.g. `test_inference_metrics.py`'s own
    locally-duplicated HTTP helper)."""
    observations: list[MacroObservation] = []
    with _FIXTURE_CSV.open() as f:
        for row in csv.DictReader(f):
            year, month = int(row["date"][:4]), int(row["date"][4:6])
            observation_at = date(year, month, calendar.monthrange(year, month)[1])
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


def test_roc_auc_is_one_for_a_perfectly_separating_model() -> None:
    probs = np.array([0.9, 0.8, 0.2, 0.1])
    labels = np.array([1.0, 1.0, 0.0, 0.0])
    assert roc_auc(probs, labels) == pytest.approx(1.0)


def test_roc_auc_is_half_for_a_constant_predictor() -> None:
    probs = np.array([0.5, 0.5, 0.5, 0.5])
    labels = np.array([1.0, 0.0, 1.0, 0.0])
    assert roc_auc(probs, labels) == pytest.approx(0.5)


def test_roc_auc_is_zero_for_a_perfectly_anti_correlated_model() -> None:
    probs = np.array([0.1, 0.2, 0.8, 0.9])
    labels = np.array([1.0, 1.0, 0.0, 0.0])
    assert roc_auc(probs, labels) == pytest.approx(0.0)


def test_roc_auc_requires_both_classes_present() -> None:
    with pytest.raises(ValueError, match="both classes"):
        roc_auc(np.array([0.1, 0.9]), np.array([1.0, 1.0]))


def test_calibration_slope_intercept_recovers_a_well_calibrated_model() -> None:
    rng = np.random.default_rng(0)
    probs = rng.uniform(0.05, 0.95, size=5000)
    labels = (rng.uniform(size=5000) < probs).astype(float)
    slope, intercept = calibration_slope_intercept(probs, labels)
    assert slope == pytest.approx(1.0, abs=0.2)
    assert intercept == pytest.approx(0.0, abs=0.2)


def test_calibration_slope_intercept_detects_overconfidence() -> None:
    """A model whose stated probabilities are pushed toward 0/1 far
    more than its true accuracy warrants should show slope < 1."""
    rng = np.random.default_rng(1)
    true_rate = rng.uniform(0.3, 0.7, size=3000)
    overconfident = np.clip(0.5 + (true_rate - 0.5) * 3, 0.01, 0.99)
    labels = (rng.uniform(size=3000) < true_rate).astype(float)
    slope, _ = calibration_slope_intercept(overconfident, labels)
    assert slope < 1.0


def test_reliability_diagram_bins_cover_all_samples() -> None:
    probs = np.array([0.05, 0.15, 0.55, 0.95])
    labels = np.array([0.0, 1.0, 1.0, 1.0])
    bins = reliability_diagram(probs, labels, n_bins=10)
    assert sum(b.count for b in bins) == 4


def test_evaluate_constant_probability_matches_the_base_rate() -> None:
    labels = np.array([1.0, 0.0, 1.0, 0.0, 0.0])
    metrics = evaluate_constant_probability(0.4, labels)
    assert metrics.brier_score == pytest.approx(np.mean((0.4 - labels) ** 2))
    assert metrics.roc_auc == pytest.approx(0.5)
    assert metrics.n_samples == 5
    assert metrics.n_positive == 2


def test_evaluate_model_runs_a_real_trained_model_in_eval_mode() -> None:
    features = np.random.default_rng(0).normal(size=(20, 3))
    labels = (features[:, 0] > 0).astype(float)
    trained = train_classifier(
        lambda: LogisticRegressionClassifier(3), features, labels, seed=0, n_epochs=100
    )
    metrics = evaluate_model(trained.model, features, labels)
    assert 0.0 <= metrics.brier_score <= 1.0
    assert metrics.roc_auc is not None
    assert len(metrics.squared_errors) == 20


def test_evaluate_model_leaves_the_model_in_eval_mode_with_no_grad_leak() -> None:
    model = LogisticRegressionClassifier(3)
    x = np.random.default_rng(0).normal(size=(5, 3))
    y = np.zeros(5)
    evaluate_model(model, x, y)
    assert model.training is False
    for p in model.parameters():
        assert p.grad is None


def test_run_recessionnet_benchmark_end_to_end_on_real_data() -> None:
    """The full FP-06 demonstration: real Kenneth French factors, real
    NBER labels, a strict chronological split, four competing
    architectures (base rate, logistic regression, classical-matched
    MLP, hybrid quantum), and an honest paired-bootstrap comparison of
    the quantum model against whichever classical model actually won
    on this test set."""
    dataset = build_recession_dataset(
        _REAL_OBSERVATIONS, _SERIES_IDS, NBER_RECESSIONS, window=6, horizon=6
    )
    train, test = chronological_split(dataset, date(2000, 1, 1))

    report = run_recessionnet_benchmark(train, test, seed=0, n_epochs=150, bootstrap_resamples=200)

    assert set(report.metrics) == {
        "base_rate",
        "logistic_regression",
        "classical_matched_mlp",
        "hybrid_quantum",
    }
    for metrics in report.metrics.values():
        assert metrics.n_samples == len(test.labels)
        assert 0.0 <= metrics.brier_score <= 1.0

    assert report.best_classical_challenger in {
        "base_rate",
        "logistic_regression",
        "classical_matched_mlp",
    }
    assert report.quantum_vs_best_classical.n_resamples == 200
    assert report.run_manifest.model_id == "recessionnet-hybrid-quantum-v1"
    assert report.run_manifest.data_hash is not None
    assert report.run_manifest.code_hash is not None
    assert report.parameter_counts["hybrid_quantum"] > 0
    assert report.parameter_counts["logistic_regression"] == train.features.shape[1] + 1


def test_run_recessionnet_benchmark_rejects_mismatched_feature_widths() -> None:
    narrow = build_recession_dataset(
        _REAL_OBSERVATIONS, _SERIES_IDS, NBER_RECESSIONS, window=3, horizon=3
    )
    wide = build_recession_dataset(
        _REAL_OBSERVATIONS, _SERIES_IDS, NBER_RECESSIONS, window=4, horizon=3
    )
    train, _ = chronological_split(narrow, date(2000, 1, 1))
    _, test = chronological_split(wide, date(2000, 1, 1))
    with pytest.raises(ValueError, match="feature width"):
        run_recessionnet_benchmark(train, test, seed=0, n_epochs=5)
