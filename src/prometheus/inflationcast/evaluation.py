"""The INFLATIONCAST benchmark: naive/linear/classical-MLP/hybrid-quantum
point forecasters vs. `InflationGRU`'s calibrated forecast, on the real,
point-in-time-safe mixed-frequency CPI nowcasting dataset (`data.py`).

Point accuracy (MAE/RMSE/MASE) is scored the same way Q-MACRO scores its
own identical four point-forecast candidates (`macrocore.quantum_
benchmark`'s `RegressionMetrics`, reused here, not reinvented); the
GRU's point accuracy is scored identically, from its mean output alone,
so it sits on the same leaderboard as the others.

`InflationGRU` is additionally scored on CALIBRATION
(`gaussian_interval_coverage_test`): a per-observation generalization of
`titan.risk_metrics.var_exception_coverage_test`'s exact two-sided
binomial test -- VaR's test fixes one threshold for every observation,
but here every observation has its own (mean, log_var), so the predicted
central interval's bounds vary row by row; what stays constant, and is
what the binomial test checks, is the NOMINAL coverage level. This is
the one genuine test of "uncertainty calibration" anywhere in this
project's three forecasting tasks, directly answering that half of the
research question for the one candidate actually designed to produce a
calibrated forecast."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import torch
from scipy import stats
from torch import nn

from prometheus.experiments.bootstrap import BootstrapResult, paired_bootstrap_difference
from prometheus.experiments.manifest import (
    RunManifest,
    compute_result_hash,
    new_run_id,
    now_iso,
    runtime_provenance,
)
from prometheus.inflationcast.models import (
    ClassicalMatchedRegressor,
    HybridQuantumRegressor,
    LinearRegressionModel,
    NaivePersistence,
    gaussian_nll,
)
from prometheus.inflationcast.training import (
    train_flattened_candidate_with_early_stopping,
    train_inflation_gru_with_early_stopping,
)


@dataclass(frozen=True, slots=True)
class RegressionMetrics:
    n_samples: int
    mae: float
    rmse: float
    mase: float
    squared_errors: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class CalibrationResult:
    n_observations: int
    nominal_coverage: float
    """The target central-interval coverage, e.g. 0.90 for a 90% interval."""
    observed_coverage: float
    """Fraction of true targets that actually fell inside their own
    predicted [mean - z*sigma, mean + z*sigma] interval."""
    p_value: float
    """Exact two-sided binomial test of observed vs. nominal coverage --
    a low p-value is evidence AGAINST calibration, not proof against it,
    the same diagnostic (not pass/fail) framing
    `var_exception_coverage_test` uses."""


def _in_sample_naive_mae(train_targets: np.ndarray) -> float:
    """The MASE denominator: train-only, one-step (consecutive-month)
    naive forecast error -- valid directly on `train_targets` because
    `inflationcast.data`'s examples are one real calendar month apart
    by construction, the same contiguity Q-MACRO's own MASE relies on."""
    if len(train_targets) < 2:
        raise ValueError("train_targets must have at least 2 values to compute a naive step error")
    return float(np.mean(np.abs(np.diff(train_targets))))


def _metrics_from_predictions(
    predictions: np.ndarray, actuals: np.ndarray, naive_mae: float
) -> RegressionMetrics:
    errors = predictions - actuals
    abs_errors = np.abs(errors)
    mae = float(np.mean(abs_errors))
    return RegressionMetrics(
        n_samples=len(actuals),
        mae=mae,
        rmse=float(np.sqrt(np.mean(errors**2))),
        mase=mae / naive_mae if naive_mae > 0 else float("inf"),
        squared_errors=tuple(float(v) for v in errors**2),
    )


def gaussian_interval_coverage_test(
    mean: np.ndarray, log_var: np.ndarray, actuals: np.ndarray, *, coverage: float
) -> CalibrationResult:
    """For every observation, builds the `coverage`-level central
    interval of N(mean, exp(log_var)) and checks whether `actuals` falls
    inside it; `stats.binomtest` then tests the observed hit rate against
    `coverage` itself -- the exact same exact-binomial machinery
    `var_exception_coverage_test` uses for a single fixed threshold,
    generalized here to a threshold that varies per observation."""
    if not 0.0 < coverage < 1.0:
        raise ValueError("coverage must be in (0, 1)")
    if mean.shape != log_var.shape or mean.shape != actuals.shape:
        raise ValueError("mean, log_var and actuals must all have the same shape")
    if mean.size == 0:
        raise ValueError("mean must be non-empty")
    sigma = np.exp(0.5 * log_var)
    z = float(stats.norm.ppf(0.5 + coverage / 2))
    lower, upper = mean - z * sigma, mean + z * sigma
    inside = (actuals >= lower) & (actuals <= upper)
    n = int(inside.size)
    n_inside = int(np.sum(inside))
    test_result = stats.binomtest(n_inside, n, coverage, alternative="two-sided")
    return CalibrationResult(
        n_observations=n,
        nominal_coverage=coverage,
        observed_coverage=n_inside / n,
        p_value=float(test_result.pvalue),
    )


def fit_variance_temperature(
    mean: np.ndarray, log_var: np.ndarray, actual: np.ndarray
) -> float:
    """The scalar variance-inflation factor `alpha` minimizing Gaussian
    NLL when `log_var` is replaced by `log_var + 2*log(alpha)` -- the
    standard post-hoc "temperature scaling" fix for a miscalibrated
    predictive variance (Guo et al. 2017's classification temperature,
    the regression/NLL analogue). A grid search, not gradient descent:
    this is one scalar, and a fixed log-spaced grid is both exact enough
    and trivially auditable. MUST be called on a validation split, never
    on the test split the returned `alpha` will later be applied to --
    callers are responsible for that separation; this function has no
    way to enforce it from the arrays alone."""
    if mean.shape != log_var.shape or mean.shape != actual.shape:
        raise ValueError("mean, log_var and actual must all have the same shape")
    if mean.size == 0:
        raise ValueError("mean must be non-empty")
    mean_t = torch.tensor(mean, dtype=torch.float32)
    actual_t = torch.tensor(actual, dtype=torch.float32)
    best_alpha, best_nll = 1.0, float("inf")
    for log_alpha in np.linspace(np.log(0.1), np.log(10.0), 41):
        scaled_log_var = torch.tensor(log_var + 2.0 * log_alpha, dtype=torch.float32)
        nll = float(gaussian_nll(mean_t, scaled_log_var, actual_t).item())
        if nll < best_nll:
            best_nll, best_alpha = nll, float(np.exp(log_alpha))
    return best_alpha


def _predict(model: nn.Module, features: np.ndarray) -> np.ndarray:
    model.eval()
    with torch.no_grad():
        output: np.ndarray = model(torch.tensor(features, dtype=torch.float32)).numpy()
    return output


@dataclass(frozen=True, slots=True)
class InflationcastBenchmarkReport:
    seed: int
    metrics: dict[str, RegressionMetrics]
    parameter_counts: dict[str, int]
    train_seconds: dict[str, float]
    selected_epochs: dict[str, int]
    best_point_challenger: str
    """The lowest-MAE candidate among naive/linear/classical_mlp/
    hybrid_quantum/gru, all scored on the same point metric."""
    test_targets: tuple[float, ...]
    predictions: dict[str, tuple[float, ...]]
    """Every candidate's real point predictions on the test set, aligned
    index-for-index with `test_targets` -- kept alongside the summary
    `metrics` so a caller (e.g. the dashboard's real-vs-predicted chart)
    can show the actual series without re-running training itself."""
    gru_calibration: CalibrationResult
    gru_calibration_temperature: float
    """The variance-inflation factor fit on the VALIDATION split alone
    (`fit_variance_temperature`) -- 1.0 means no adjustment was needed."""
    gru_calibration_after_temperature: CalibrationResult
    """The same calibration test on the TEST split, after applying
    `gru_calibration_temperature` to the GRU's predicted variance --
    the honest post-hoc-calibrated counterpart to `gru_calibration`,
    fit without ever looking at the test split itself."""
    gru_vs_best_classical: BootstrapResult
    """CI for mean(gru squared error) - mean(best-classical squared
    error) over the paired test set. `excludes_zero()` and a NEGATIVE
    point estimate together are the only honest basis for claiming the
    GRU improved on its best classical challenger."""
    run_manifest: RunManifest


_CLASSICAL_CANDIDATE_NAMES = ("naive_persistence", "linear_regression", "classical_matched_mlp")
_ALL_CANDIDATE_NAMES = (*_CLASSICAL_CANDIDATE_NAMES, "hybrid_quantum", "gru")


def run_inflationcast_benchmark(
    train_features: np.ndarray,
    train_targets: np.ndarray,
    validation_features: np.ndarray,
    validation_targets: np.ndarray,
    test_features: np.ndarray,
    test_targets: np.ndarray,
    *,
    n_series: int,
    seed: int,
    max_epochs: int = 500,
    patience: int = 20,
    bootstrap_resamples: int = 2000,
    calibration_coverage: float = 0.90,
) -> InflationcastBenchmarkReport:
    if train_features.shape[1] != test_features.shape[1]:
        raise ValueError("train and test feature sets must share the same width")
    if validation_features.shape[1] != test_features.shape[1]:
        raise ValueError("validation and test feature sets must share the same width")

    naive_mae = _in_sample_naive_mae(train_targets)
    input_dim = train_features.shape[1]

    metrics: dict[str, RegressionMetrics] = {}
    parameter_counts: dict[str, int] = {}
    train_seconds: dict[str, float] = {}
    selected_epochs: dict[str, int] = {}
    predictions: dict[str, tuple[float, ...]] = {}

    # The CURRENT target month's CPI slot is always the last (window, series)
    # block and always masked by construction (see `data.py`); the month
    # immediately before it is always genuinely available (its publication
    # lag has already passed by `decision_date`), and CPI_YOY is series
    # index 0 within every block -- so this fixed offset is the real,
    # per-example "most recently known CPI_YOY", not a borrowed constant.
    most_recent_known_cpi = test_features[:, input_dim - 4 * n_series]
    naive_predictions = np.array(
        [NaivePersistence.predict(v) for v in most_recent_known_cpi]
    )
    metrics["naive_persistence"] = _metrics_from_predictions(
        naive_predictions, test_targets, naive_mae
    )
    parameter_counts["naive_persistence"] = 0
    train_seconds["naive_persistence"] = 0.0
    predictions["naive_persistence"] = tuple(float(v) for v in naive_predictions)

    model_factories: dict[str, Callable[[], nn.Module]] = {
        "linear_regression": lambda: LinearRegressionModel(input_dim),
        "classical_matched_mlp": lambda: ClassicalMatchedRegressor(input_dim),
        "hybrid_quantum": lambda: HybridQuantumRegressor(input_dim),
    }
    for name, factory in model_factories.items():
        trained = train_flattened_candidate_with_early_stopping(
            factory,
            train_features,
            train_targets,
            validation_features,
            validation_targets,
            seed=seed,
            max_epochs=max_epochs,
            patience=patience,
        )
        candidate_predictions = _predict(trained.model, test_features)
        metrics[name] = _metrics_from_predictions(candidate_predictions, test_targets, naive_mae)
        parameter_counts[name] = trained.n_parameters
        train_seconds[name] = trained.train_seconds
        selected_epochs[name] = trained.selected_epoch
        predictions[name] = tuple(float(v) for v in candidate_predictions)

    gru_trained = train_inflation_gru_with_early_stopping(
        train_features,
        train_targets,
        validation_features,
        validation_targets,
        n_series=n_series,
        seed=seed,
        max_epochs=max_epochs,
        patience=patience,
    )
    window = input_dim // (2 * n_series)

    def reshape_for_gru(features: np.ndarray) -> torch.Tensor:
        return torch.tensor(
            features.reshape(features.shape[0], window, 2 * n_series), dtype=torch.float32
        )

    gru_trained.model.eval()
    with torch.no_grad():
        gru_mean_t, gru_log_var_t = gru_trained.model(reshape_for_gru(test_features))
        gru_val_mean_t, gru_val_log_var_t = gru_trained.model(reshape_for_gru(validation_features))
    gru_mean, gru_log_var = gru_mean_t.numpy(), gru_log_var_t.numpy()
    metrics["gru"] = _metrics_from_predictions(gru_mean, test_targets, naive_mae)
    parameter_counts["gru"] = gru_trained.n_parameters
    train_seconds["gru"] = gru_trained.train_seconds
    selected_epochs["gru"] = gru_trained.selected_epoch
    predictions["gru"] = tuple(float(v) for v in gru_mean)

    gru_calibration = gaussian_interval_coverage_test(
        gru_mean, gru_log_var, test_targets, coverage=calibration_coverage
    )
    gru_calibration_temperature = fit_variance_temperature(
        gru_val_mean_t.numpy(), gru_val_log_var_t.numpy(), validation_targets
    )
    gru_calibration_after_temperature = gaussian_interval_coverage_test(
        gru_mean,
        gru_log_var + 2.0 * np.log(gru_calibration_temperature),
        test_targets,
        coverage=calibration_coverage,
    )

    best_point_challenger = min(_ALL_CANDIDATE_NAMES, key=lambda name: metrics[name].mae)
    best_classical_challenger = min(
        _CLASSICAL_CANDIDATE_NAMES, key=lambda name: metrics[name].mae
    )

    rng = np.random.default_rng(seed)
    bootstrap = paired_bootstrap_difference(
        lambda arr: float(np.mean(arr)),
        np.array(metrics["gru"].squared_errors),
        np.array(metrics[best_classical_challenger].squared_errors),
        rng,
        n_resamples=bootstrap_resamples,
    )

    data_hash = compute_result_hash(
        {
            "train_features": train_features.tolist(),
            "train_targets": train_targets.tolist(),
            "validation_features": validation_features.tolist(),
            "validation_targets": validation_targets.tolist(),
            "test_features": test_features.tolist(),
            "test_targets": test_targets.tolist(),
        }
    )
    result_hash = compute_result_hash({name: m.mae for name, m in metrics.items()})
    manifest = RunManifest(
        run_id=new_run_id("inflationcast"),
        created_at=now_iso(),
        seed=seed,
        config={
            "n_series": n_series,
            "window": window,
            "max_epochs": max_epochs,
            "patience": patience,
            "selected_epochs": selected_epochs,
            "calibration_coverage": calibration_coverage,
        },
        result_hash=result_hash,
        code_hash=runtime_provenance()["source_sha256"],
        data_hash=data_hash,
        model_id="inflationcast-gru-v1",
    )

    return InflationcastBenchmarkReport(
        seed=seed,
        metrics=metrics,
        parameter_counts=parameter_counts,
        train_seconds=train_seconds,
        selected_epochs=selected_epochs,
        best_point_challenger=best_point_challenger,
        test_targets=tuple(float(v) for v in test_targets),
        predictions=predictions,
        gru_calibration=gru_calibration,
        gru_calibration_temperature=gru_calibration_temperature,
        gru_calibration_after_temperature=gru_calibration_after_temperature,
        gru_vs_best_classical=bootstrap,
        run_manifest=manifest,
    )
