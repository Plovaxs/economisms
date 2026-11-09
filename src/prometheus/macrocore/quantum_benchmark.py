"""Q-MACRO: a hybrid quantum regressor vs. classical challengers for
h-months-ahead Mkt-RF (market excess return) regression, on real
Kenneth French factor data (DAT-05) -- the user-supplied quantum
blueprint's second P0 engine, and ECONOSIM-X/PROMETHEUS-X addendum
FP-05's own minimal "matched regression benchmark" deliverable (see
`macrocore.regression_dataset`'s module docstring for exactly what is
and is not claimed against FP-05's fuller GDP/rate/unemployment scope).

Five candidate predictors, matching the blueprint's own Q-MACRO
baseline set (section 4.1) as closely as this repository's real data
allows:

- `persistence`: the naive forecast (next value = the target series'
  own most recently realized value) -- `RecessionDataset`'s analogue
  has no continuous "most recent value" concept; this task does.
- `ar`: AR(p) (`macrocore.baselines.fit_autoregression`, already
  evidenced for FP-04), genuinely REFIT at every test decision month
  using only real history available as of that month -- the one
  candidate here using a true rolling-origin protocol, since
  refitting a p-coefficient OLS at every origin is cheap. The neural
  candidates below are each trained ONCE and evaluated pointwise
  across the whole test set -- refitting a neural network from
  scratch at every rolling origin would be prohibitively expensive;
  this asymmetry is real and disclosed, not hidden.
- `linear_regression` / `classical_matched_mlp` / `hybrid_quantum`:
  `quantum.models.LinearRegressionModel` / `ClassicalMatchedRegressor`
  / `HybridQuantumRegressor`, trained with
  `recessionnet.training.train_classifier_with_early_stopping`
  (`loss_fn=nn.MSELoss()`, `output_transform` = identity) -- directly
  reusing RECESSIONNET's PR-142 methodology correction from the start,
  rather than repeating its original fixed-epoch-budget mistake.

MASE (Hyndman & Koehler 2006) is computed against the IN-SAMPLE
(training-set-only) mean absolute one-step change in the target
series -- never derived from test data, so it cannot leak test
information into its own normalization. PR-AUC has no regression
analogue; CRPS/other probabilistic scoring is not attempted (every
model here is a point forecaster, consistent with the blueprint's own
"MAE, RMSE, MASE and probabilistic metrics IF output distribution is
modeled" -- none is).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np
import torch
from torch import nn

from prometheus.experiments.bootstrap import BootstrapResult, paired_bootstrap_difference
from prometheus.experiments.manifest import (
    RunManifest,
    compute_result_hash,
    new_run_id,
    now_iso,
    runtime_provenance,
)
from prometheus.macrocore.baselines import fit_autoregression
from prometheus.macrocore.regression_dataset import FIXED_FEATURE_SCALE, MacroRegressionDataset
from prometheus.quantum.models import (
    ClassicalMatchedRegressor,
    HybridQuantumRegressor,
    LinearRegressionModel,
)
from prometheus.recessionnet.training import train_classifier_with_early_stopping


@dataclass(frozen=True, slots=True)
class RegressionMetrics:
    n_samples: int
    mae: float
    rmse: float
    mase: float
    squared_errors: tuple[float, ...]


def _in_sample_naive_mae(train_targets: np.ndarray) -> float:
    """The MASE denominator: train-only, one-step (consecutive-month)
    naive forecast error. Valid directly on `targets` here because
    consecutive samples' target_months are exactly one calendar month
    apart (decision_months increment monthly by construction), so
    `targets` IS a contiguous slice of the real monthly series."""
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


def evaluate_persistence(test: MacroRegressionDataset, naive_mae: float) -> RegressionMetrics:
    return _metrics_from_predictions(test.most_recent_target_values, test.targets, naive_mae)


def evaluate_ar(
    test: MacroRegressionDataset,
    target_history_months: Sequence[date],
    target_history_values: Sequence[float],
    order: int,
    naive_mae: float,
) -> RegressionMetrics:
    month_index = {month: i for i, month in enumerate(target_history_months)}
    scaled_history = np.asarray(target_history_values, dtype=float) / FIXED_FEATURE_SCALE
    predictions = np.zeros(len(test.decision_months))
    for i, decision_month in enumerate(test.decision_months):
        history = scaled_history[: month_index[decision_month] + 1]
        fitted = fit_autoregression(history, order)
        predictions[i] = fitted.forecast([test.horizon])[0].mean
    return _metrics_from_predictions(predictions, test.targets, naive_mae)


def _predict(model: nn.Module, features: np.ndarray) -> np.ndarray:
    model.eval()
    with torch.no_grad():
        output: np.ndarray = model(torch.tensor(features, dtype=torch.float32)).numpy()
    return output


@dataclass(frozen=True, slots=True)
class QMacroBenchmarkReport:
    seed: int
    metrics: dict[str, RegressionMetrics]
    parameter_counts: dict[str, int]
    train_seconds: dict[str, float]
    selected_epochs: dict[str, int]
    best_classical_challenger: str
    quantum_vs_best_classical: BootstrapResult
    """CI for mean(quantum squared error) - mean(best-classical squared
    error) over the paired test set. `excludes_zero()` and a NEGATIVE
    point estimate together are the only honest basis for claiming the
    quantum model improved on its best classical challenger."""
    run_manifest: RunManifest


_CLASSICAL_CANDIDATE_NAMES = ("persistence", "ar", "linear_regression", "classical_matched_mlp")


def run_qmacro_benchmark(
    train_proper: MacroRegressionDataset,
    validation: MacroRegressionDataset,
    test: MacroRegressionDataset,
    target_history_months: Sequence[date],
    target_history_values: Sequence[float],
    *,
    seed: int,
    ar_order: int = 3,
    max_epochs: int = 500,
    patience: int = 20,
    bootstrap_resamples: int = 2000,
) -> QMacroBenchmarkReport:
    if train_proper.features.shape[1] != test.features.shape[1]:
        raise ValueError("train_proper and test datasets must share the same feature width")
    if validation.features.shape[1] != test.features.shape[1]:
        raise ValueError("validation and test datasets must share the same feature width")

    naive_mae = _in_sample_naive_mae(train_proper.targets)

    metrics: dict[str, RegressionMetrics] = {}
    parameter_counts: dict[str, int] = {"persistence": 0, "ar": ar_order + 1}
    train_seconds: dict[str, float] = {"persistence": 0.0, "ar": 0.0}
    selected_epochs: dict[str, int] = {}

    metrics["persistence"] = evaluate_persistence(test, naive_mae)
    metrics["ar"] = evaluate_ar(
        test, target_history_months, target_history_values, ar_order, naive_mae
    )

    input_dim = train_proper.features.shape[1]
    model_factories: dict[str, Callable[[], nn.Module]] = {
        "linear_regression": lambda: LinearRegressionModel(input_dim),
        "classical_matched_mlp": lambda: ClassicalMatchedRegressor(input_dim),
        "hybrid_quantum": lambda: HybridQuantumRegressor(input_dim),
    }
    for name, factory in model_factories.items():
        trained = train_classifier_with_early_stopping(
            factory,
            train_proper.features,
            train_proper.targets,
            validation.features,
            validation.targets,
            seed=seed,
            max_epochs=max_epochs,
            patience=patience,
            loss_fn=nn.MSELoss(),
            output_transform=lambda t: t,
        )
        predictions = _predict(trained.model, test.features)
        metrics[name] = _metrics_from_predictions(predictions, test.targets, naive_mae)
        parameter_counts[name] = trained.n_parameters
        train_seconds[name] = trained.train_seconds
        selected_epochs[name] = trained.selected_epoch

    best_classical_challenger = min(
        _CLASSICAL_CANDIDATE_NAMES, key=lambda name: metrics[name].mae
    )

    rng = np.random.default_rng(seed)
    bootstrap = paired_bootstrap_difference(
        lambda arr: float(np.mean(arr)),
        np.array(metrics["hybrid_quantum"].squared_errors),
        np.array(metrics[best_classical_challenger].squared_errors),
        rng,
        n_resamples=bootstrap_resamples,
    )

    data_hash = compute_result_hash(
        {
            "train_features": train_proper.features.tolist(),
            "train_targets": train_proper.targets.tolist(),
            "validation_features": validation.features.tolist(),
            "validation_targets": validation.targets.tolist(),
            "test_features": test.features.tolist(),
            "test_targets": test.targets.tolist(),
        }
    )
    result_hash = compute_result_hash({name: m.mae for name, m in metrics.items()})
    manifest = RunManifest(
        run_id=new_run_id("qmacro"),
        created_at=now_iso(),
        seed=seed,
        config={
            "ar_order": ar_order,
            "max_epochs": max_epochs,
            "patience": patience,
            "selected_epochs": selected_epochs,
            "window": train_proper.window,
            "horizon": train_proper.horizon,
            "series_ids": list(train_proper.series_ids),
            "target_series_id": train_proper.target_series_id,
        },
        result_hash=result_hash,
        code_hash=runtime_provenance()["source_sha256"],
        data_hash=data_hash,
        model_id="qmacro-hybrid-quantum-v1",
    )

    return QMacroBenchmarkReport(
        seed=seed,
        metrics=metrics,
        parameter_counts=parameter_counts,
        train_seconds=train_seconds,
        selected_epochs=selected_epochs,
        best_classical_challenger=best_classical_challenger,
        quantum_vs_best_classical=bootstrap,
        run_manifest=manifest,
    )
