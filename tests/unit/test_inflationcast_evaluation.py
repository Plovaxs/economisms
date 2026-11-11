import numpy as np
import pytest

from prometheus.inflationcast.evaluation import (
    gaussian_interval_coverage_test,
    run_inflationcast_benchmark,
)

_N_SERIES = 3
_WINDOW = 4
_WIDTH = _WINDOW * _N_SERIES * 2


def _synthetic_arrays(
    n_train: int = 80, n_val: int = 20, n_test: int = 20, seed: int = 0
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    n = n_train + n_val + n_test
    features = rng.normal(size=(n, _WIDTH))
    true_weights = rng.normal(size=_WIDTH)
    targets = features @ true_weights + rng.normal(scale=0.01, size=n)
    return (
        features[:n_train], targets[:n_train],
        features[n_train : n_train + n_val], targets[n_train : n_train + n_val],
        features[n_train + n_val :], targets[n_train + n_val :],
    )


def test_gaussian_interval_coverage_test_accepts_a_well_calibrated_forecaster() -> None:
    rng = np.random.default_rng(0)
    n = 5000
    true_sigma = 2.0
    mean = rng.normal(size=n)
    actuals = mean + rng.normal(scale=true_sigma, size=n)
    log_var = np.full(n, np.log(true_sigma**2))
    result = gaussian_interval_coverage_test(mean, log_var, actuals, coverage=0.90)
    assert result.observed_coverage == pytest.approx(0.90, abs=0.03)
    assert result.p_value > 0.01


def test_gaussian_interval_coverage_test_rejects_an_overconfident_forecaster() -> None:
    """Predicted intervals far too narrow relative to the true noise
    must show low observed coverage and a tiny p-value -- the real
    failure mode this project's own INFLATIONCAST demo run exhibits."""
    rng = np.random.default_rng(0)
    n = 500
    mean = rng.normal(size=n)
    actuals = mean + rng.normal(scale=5.0, size=n)
    log_var = np.full(n, np.log(0.01))  # massively overconfident
    result = gaussian_interval_coverage_test(mean, log_var, actuals, coverage=0.90)
    assert result.observed_coverage < 0.5
    assert result.p_value < 0.01


def test_gaussian_interval_coverage_test_rejects_invalid_coverage() -> None:
    mean = np.zeros(5)
    with pytest.raises(ValueError, match="coverage"):
        gaussian_interval_coverage_test(mean, mean, mean, coverage=1.5)


def test_gaussian_interval_coverage_test_rejects_mismatched_shapes() -> None:
    with pytest.raises(ValueError, match="shape"):
        gaussian_interval_coverage_test(np.zeros(5), np.zeros(5), np.zeros(4), coverage=0.9)


def test_gaussian_interval_coverage_test_rejects_empty_input() -> None:
    empty = np.zeros(0)
    with pytest.raises(ValueError, match="non-empty"):
        gaussian_interval_coverage_test(empty, empty, empty, coverage=0.9)


def test_run_inflationcast_benchmark_produces_every_expected_candidate() -> None:
    x_train, y_train, x_val, y_val, x_test, y_test = _synthetic_arrays()
    report = run_inflationcast_benchmark(
        x_train, y_train, x_val, y_val, x_test, y_test,
        n_series=_N_SERIES, seed=0, max_epochs=30, patience=5, bootstrap_resamples=100,
    )
    assert set(report.metrics) == {
        "naive_persistence", "linear_regression", "classical_matched_mlp",
        "hybrid_quantum", "gru",
    }
    assert report.best_point_challenger in report.metrics
    assert report.gru_calibration.n_observations == len(y_test)
    assert report.gru_vs_best_classical.n_resamples == 100
    assert report.run_manifest.model_id == "inflationcast-gru-v1"
    assert report.test_targets == tuple(float(v) for v in y_test)
    assert set(report.predictions) == set(report.metrics)
    for preds in report.predictions.values():
        assert len(preds) == len(y_test)


def test_run_inflationcast_benchmark_is_deterministic_for_a_fixed_seed() -> None:
    x_train, y_train, x_val, y_val, x_test, y_test = _synthetic_arrays()
    kwargs = dict(
        train_features=x_train, train_targets=y_train,
        validation_features=x_val, validation_targets=y_val,
        test_features=x_test, test_targets=y_test,
        n_series=_N_SERIES, seed=0, max_epochs=20, patience=5, bootstrap_resamples=50,
    )
    first = run_inflationcast_benchmark(**kwargs)
    second = run_inflationcast_benchmark(**kwargs)
    assert first.metrics["gru"].mae == second.metrics["gru"].mae
    assert first.metrics["linear_regression"].mae == second.metrics["linear_regression"].mae


def test_run_inflationcast_benchmark_rejects_mismatched_feature_widths() -> None:
    x_train, y_train, x_val, y_val, x_test, y_test = _synthetic_arrays()
    with pytest.raises(ValueError, match="width"):
        run_inflationcast_benchmark(
            x_train, y_train, x_val, y_val, x_test[:, :-1], y_test,
            n_series=_N_SERIES, seed=0, max_epochs=5, patience=2,
        )
