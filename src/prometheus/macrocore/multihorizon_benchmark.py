"""FP-05's own benchmark: does a SHARED Transformer encoder forecasting
GDP, rates AND unemployment across multiple horizons jointly beat the
classical baselines FP-04/E01 already names (Persistence, "ARIMA"
i.e. AR(p) -- see `macrocore.baselines`'s module docstring for why a
full Box-Jenkins ARIMA was not attempted -- and VAR(p)), plus a
parameter-matched classical MLP and ordinary multivariate linear
regression?

Every classical candidate here reuses `macrocore.baselines.
fit_autoregression`/`fit_vector_autoregression` UNCHANGED, refit at
every real test decision month from only the real history available up
to that month (the same rolling-origin discipline
`quantum_benchmark.evaluate_ar` already established for the single-
target case, generalized here to three target series and a joint
VAR(p)). Every neural candidate reuses `recessionnet.training.
train_classifier_with_early_stopping` UNCHANGED (`loss_fn=nn.MSELoss()`,
identity `output_transform`), selecting its stopping point on a real
validation split that is never the test set -- the same methodology
Q-MACRO/RECESSIONNET/INFLATIONCAST already apply.

Real data: `data_ingestion.kaggle_macro`'s real GDP growth
(`KAGGLE_GDP_YOY`), unemployment-claims growth (`KAGGLE_CLAIMS_YOY`),
and the Fed funds rate (`KAGGLE_FEDFUNDS`) are the three FP-05 targets
("GDP, rates and unemployment", literally); `KAGGLE_M2_YOY` and
`KAGGLE_NASDAQ_YOY` are additional real predictors available to every
feature-window-based candidate. The validation/test split dates
(2001-01-01 / 2008-01-01) are the SAME split `kaggle_macro`'s own
FP-06 benchmark already established for this exact file, reused rather
than re-derived.

Null and negative results are reported exactly like every other engine
in this repository: if the shared Transformer does not beat its
classical challengers, that is what gets written down.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import torch
from torch import nn

from prometheus.data_ingestion.monthly_matrix import build_monthly_series_matrix
from prometheus.econosim.pit import MacroObservation
from prometheus.experiments.bootstrap import BootstrapResult, paired_bootstrap_difference
from prometheus.experiments.manifest import (
    RunManifest,
    compute_result_hash,
    new_run_id,
    now_iso,
    runtime_provenance,
)
from prometheus.macrocore.baselines import fit_autoregression, fit_vector_autoregression
from prometheus.macrocore.multihorizon_dataset import (
    FIXED_FEATURE_SCALE,
    MultihorizonDataset,
    in_sample_naive_mae,
)
from prometheus.macrocore.shared_transformer import (
    LinearMultihorizon,
    SharedMultihorizonMLP,
    SharedMultihorizonTransformer,
)
from prometheus.recessionnet.training import train_classifier_with_early_stopping

_CLASSICAL_CANDIDATE_NAMES = ("persistence", "ar", "var", "linear_regression", "classical_mlp")


@dataclass(frozen=True, slots=True)
class CandidateMetrics:
    target_series_id: str
    horizon: int
    n_samples: int
    mae: float
    rmse: float
    mase: float
    squared_errors: tuple[float, ...]


def _metrics_from_predictions(
    target_series_id: str,
    horizon: int,
    predictions: np.ndarray,
    actuals: np.ndarray,
    naive_mae: float,
) -> CandidateMetrics:
    errors = predictions - actuals
    abs_errors = np.abs(errors)
    mae = float(np.mean(abs_errors))
    return CandidateMetrics(
        target_series_id=target_series_id,
        horizon=horizon,
        n_samples=len(actuals),
        mae=mae,
        rmse=float(np.sqrt(np.mean(errors**2))),
        mase=mae / naive_mae if naive_mae > 0 else float("inf"),
        squared_errors=tuple(float(v) for v in errors**2),
    )


def _naive_maes(train: MultihorizonDataset) -> list[float]:
    return [in_sample_naive_mae(train, j) for j in range(len(train.target_series_ids))]


def evaluate_persistence(
    test: MultihorizonDataset, naive_maes: list[float]
) -> dict[tuple[str, int], CandidateMetrics]:
    results: dict[tuple[str, int], CandidateMetrics] = {}
    for j, target_series_id in enumerate(test.target_series_ids):
        predictions = test.most_recent_target_values[:, j]
        for h in test.horizons:
            actuals = test.target_column(j, h)
            results[(target_series_id, h)] = _metrics_from_predictions(
                target_series_id, h, predictions, actuals, naive_maes[j]
            )
    return results


def evaluate_ar(
    observations: list[MacroObservation],
    test: MultihorizonDataset,
    order: int,
    naive_maes: list[float],
) -> dict[tuple[str, int], CandidateMetrics]:
    results: dict[tuple[str, int], CandidateMetrics] = {}
    for j, target_series_id in enumerate(test.target_series_ids):
        months, matrix = build_monthly_series_matrix(observations, (target_series_id,))
        scaled_history = matrix[:, 0] / FIXED_FEATURE_SCALE
        month_index = {month: i for i, month in enumerate(months)}
        predictions_by_horizon: dict[int, list[float]] = {h: [] for h in test.horizons}
        for decision_month in test.decision_months:
            history = scaled_history[: month_index[decision_month] + 1]
            fitted = fit_autoregression(history, order)
            forecasts = fitted.forecast(list(test.horizons))
            for forecast in forecasts:
                predictions_by_horizon[forecast.horizon].append(forecast.mean)
        for h in test.horizons:
            predictions = np.array(predictions_by_horizon[h])
            actuals = test.target_column(j, h)
            results[(target_series_id, h)] = _metrics_from_predictions(
                target_series_id, h, predictions, actuals, naive_maes[j]
            )
    return results


def evaluate_var(
    observations: list[MacroObservation],
    test: MultihorizonDataset,
    order: int,
    naive_maes: list[float],
) -> dict[tuple[str, int], CandidateMetrics]:
    target_series_ids = list(test.target_series_ids)
    months, matrix = build_monthly_series_matrix(observations, target_series_ids)
    scaled_matrix = matrix / FIXED_FEATURE_SCALE
    month_index = {month: i for i, month in enumerate(months)}

    predictions_by_series_horizon: dict[tuple[str, int], list[float]] = {
        (sid, h): [] for sid in target_series_ids for h in test.horizons
    }
    for decision_month in test.decision_months:
        history = scaled_matrix[: month_index[decision_month] + 1, :]
        fitted = fit_vector_autoregression(history, order, target_series_ids)
        forecasts_by_series = fitted.forecast(list(test.horizons))
        for series_id in target_series_ids:
            for forecast in forecasts_by_series[series_id]:
                predictions_by_series_horizon[(series_id, forecast.horizon)].append(
                    forecast.mean
                )

    results: dict[tuple[str, int], CandidateMetrics] = {}
    for j, target_series_id in enumerate(target_series_ids):
        for h in test.horizons:
            predictions = np.array(predictions_by_series_horizon[(target_series_id, h)])
            actuals = test.target_column(j, h)
            results[(target_series_id, h)] = _metrics_from_predictions(
                target_series_id, h, predictions, actuals, naive_maes[j]
            )
    return results


def _predict(model: nn.Module, features: np.ndarray) -> np.ndarray:
    model.eval()
    with torch.no_grad():
        output: np.ndarray = model(torch.tensor(features, dtype=torch.float32)).numpy()
    return output


def _metrics_from_joint_predictions(
    predictions: np.ndarray, test: MultihorizonDataset, naive_maes: list[float]
) -> dict[tuple[str, int], CandidateMetrics]:
    results: dict[tuple[str, int], CandidateMetrics] = {}
    for j, target_series_id in enumerate(test.target_series_ids):
        for h_index, h in enumerate(test.horizons):
            column = j * len(test.horizons) + h_index
            actuals = test.target_column(j, h)
            results[(target_series_id, h)] = _metrics_from_predictions(
                target_series_id, h, predictions[:, column], actuals, naive_maes[j]
            )
    return results


@dataclass(frozen=True, slots=True)
class SharedMultihorizonBenchmarkReport:
    seed: int
    metrics: dict[str, dict[tuple[str, int], CandidateMetrics]]
    parameter_counts: dict[str, int]
    train_seconds: dict[str, float]
    selected_epochs: dict[str, int]
    best_classical_challenger: dict[tuple[str, int], str]
    transformer_vs_best_classical: dict[tuple[str, int], BootstrapResult]
    run_manifest: RunManifest

    def overall_mase(self, model_name: str) -> float:
        """Equal-weight mean MASE across every (target, horizon) pair
        -- one headline number per candidate, used only for a top-line
        summary; the per-pair numbers in `metrics` are the real record."""
        values = [m.mase for m in self.metrics[model_name].values()]
        return float(np.mean(values))


def run_shared_multihorizon_benchmark(
    observations: list[MacroObservation],
    train: MultihorizonDataset,
    validation: MultihorizonDataset,
    test: MultihorizonDataset,
    *,
    seed: int,
    ar_order: int = 3,
    var_order: int = 3,
    max_epochs: int = 500,
    patience: int = 20,
    bootstrap_resamples: int = 2000,
) -> SharedMultihorizonBenchmarkReport:
    if train.features.shape[1] != test.features.shape[1]:
        raise ValueError("train and test datasets must share the same feature width")
    if validation.features.shape[1] != test.features.shape[1]:
        raise ValueError("validation and test datasets must share the same feature width")

    naive_maes = _naive_maes(train)
    n_targets = len(test.target_series_ids)
    n_horizons = len(test.horizons)
    n_outputs = n_targets * n_horizons

    metrics: dict[str, dict[tuple[str, int], CandidateMetrics]] = {}
    parameter_counts: dict[str, int] = {
        "persistence": 0,
        "ar": (ar_order + 1) * n_targets,
        "var": n_targets * (1 + var_order * n_targets),
    }
    train_seconds: dict[str, float] = {"persistence": 0.0, "ar": 0.0, "var": 0.0}
    selected_epochs: dict[str, int] = {}

    metrics["persistence"] = evaluate_persistence(test, naive_maes)
    metrics["ar"] = evaluate_ar(observations, test, ar_order, naive_maes)
    metrics["var"] = evaluate_var(observations, test, var_order, naive_maes)

    input_dim = train.features.shape[1]
    window = train.window
    n_feature_series = len(train.feature_series_ids)
    model_factories: dict[str, Callable[[], nn.Module]] = {
        "linear_regression": lambda: LinearMultihorizon(input_dim, n_outputs),
        "classical_mlp": lambda: SharedMultihorizonMLP(input_dim, n_outputs),
        "shared_transformer": lambda: SharedMultihorizonTransformer(
            window, n_feature_series, n_outputs
        ),
    }
    for name, factory in model_factories.items():
        trained = train_classifier_with_early_stopping(
            factory,
            train.features,
            train.targets,
            validation.features,
            validation.targets,
            seed=seed,
            max_epochs=max_epochs,
            patience=patience,
            loss_fn=nn.MSELoss(),
            output_transform=lambda t: t,
        )
        predictions = _predict(trained.model, test.features)
        metrics[name] = _metrics_from_joint_predictions(predictions, test, naive_maes)
        parameter_counts[name] = trained.n_parameters
        train_seconds[name] = trained.train_seconds
        selected_epochs[name] = trained.selected_epoch

    best_classical_challenger: dict[tuple[str, int], str] = {}
    transformer_vs_best_classical: dict[tuple[str, int], BootstrapResult] = {}
    rng = np.random.default_rng(seed)
    for target_series_id in test.target_series_ids:
        for h in test.horizons:
            key = (target_series_id, h)
            best_name = min(_CLASSICAL_CANDIDATE_NAMES, key=lambda name: metrics[name][key].mae)
            best_classical_challenger[key] = best_name
            transformer_vs_best_classical[key] = paired_bootstrap_difference(
                lambda arr: float(np.mean(arr)),
                np.array(metrics["shared_transformer"][key].squared_errors),
                np.array(metrics[best_name][key].squared_errors),
                rng,
                n_resamples=bootstrap_resamples,
            )

    data_hash = compute_result_hash(
        {
            "train_features": train.features.tolist(),
            "train_targets": train.targets.tolist(),
            "validation_features": validation.features.tolist(),
            "validation_targets": validation.targets.tolist(),
            "test_features": test.features.tolist(),
            "test_targets": test.targets.tolist(),
        }
    )
    result_hash = compute_result_hash(
        {
            f"{name}:{key[0]}:{key[1]}": m.mae
            for name, by_key in metrics.items()
            for key, m in by_key.items()
        }
    )
    manifest = RunManifest(
        run_id=new_run_id("macrocore-shared-multihorizon"),
        created_at=now_iso(),
        seed=seed,
        config={
            "ar_order": ar_order,
            "var_order": var_order,
            "max_epochs": max_epochs,
            "patience": patience,
            "selected_epochs": selected_epochs,
            "window": train.window,
            "horizons": list(train.horizons),
            "feature_series_ids": list(train.feature_series_ids),
            "target_series_ids": list(train.target_series_ids),
        },
        result_hash=result_hash,
        code_hash=runtime_provenance()["source_sha256"],
        data_hash=data_hash,
        model_id="macrocore-shared-multihorizon-transformer-v1",
    )

    return SharedMultihorizonBenchmarkReport(
        seed=seed,
        metrics=metrics,
        parameter_counts=parameter_counts,
        train_seconds=train_seconds,
        selected_epochs=selected_epochs,
        best_classical_challenger=best_classical_challenger,
        transformer_vs_best_classical=transformer_vs_best_classical,
        run_manifest=manifest,
    )
