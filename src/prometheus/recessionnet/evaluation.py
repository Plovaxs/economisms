"""RECESSIONNET evaluation metrics and the quantum-vs-classical
benchmark report (ECONOSIM-X/PROMETHEUS-X addendum FP-06's "calibrated
probabilities," E02's "AUROC, PR-AUC, Brier, reliability diagram," and
the user-supplied quantum blueprint's RQ2: "Can VQC-based recession
classification improve probability calibration or ... discrimination
relative to logistic regression, MLP?").

PR-AUC is NOT implemented here -- ROC-AUC, Brier score and a
calibration regression (slope/intercept) are; PR-AUC is a defensible
follow-up, not attempted in this PR to keep scope bounded. ROC-AUC is
computed directly from the Mann-Whitney U statistic (every positive/
negative score pair, vectorized; ties count as 0.5), not via a
third-party library -- this project has no runtime ML-metrics
dependency and this formula is exact, not an approximation.
Calibration slope/intercept are fit by a small, fully deterministic
(no randomness: convex problem, fixed iteration count) logistic
regression of labels on logit(probability), the standard "calibration
regression" diagnostic (slope 1 / intercept 0 = perfectly calibrated).

The quantum-vs-best-classical comparison reuses
`experiments.bootstrap.paired_bootstrap_difference` (EXP-07) over
PAIRED per-sample squared errors (the same test-set samples scored by
both models) -- not a new bootstrap implementation -- directly
answering the blueprint's own hypothesis framing (section 2: test
H0: E[L_Q - L_C] >= 0 against H1: E[L_Q - L_C] < 0 via a paired,
dependence-aware interval, not a bare point comparison). "Best
classical challenger" is chosen by test-set Brier score AFTER the
fact, honestly, not fixed in advance to flatter either side.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

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
from prometheus.quantum.models import (
    ClassicalMatchedClassifier,
    HybridQuantumClassifier,
    LogisticRegressionClassifier,
)
from prometheus.recessionnet.dataset import RecessionDataset
from prometheus.recessionnet.training import train_classifier


@dataclass(frozen=True, slots=True)
class ReliabilityBin:
    bin_lower: float
    bin_upper: float
    mean_predicted: float
    mean_actual: float
    count: int


@dataclass(frozen=True, slots=True)
class ClassificationMetrics:
    n_samples: int
    n_positive: int
    brier_score: float
    roc_auc: float | None
    """None when the test set is single-class (AUC is undefined)."""
    calibration_slope: float
    calibration_intercept: float
    reliability: tuple[ReliabilityBin, ...]
    squared_errors: tuple[float, ...]
    """Per-sample (probability - label)^2 -- kept for the paired
    bootstrap comparison below, not just the aggregate Brier score."""


def roc_auc(probs: np.ndarray, labels: np.ndarray) -> float:
    probs = np.asarray(probs, dtype=float)
    labels = np.asarray(labels, dtype=float)
    positive = probs[labels == 1.0]
    negative = probs[labels == 0.0]
    if positive.size == 0 or negative.size == 0:
        raise ValueError("roc_auc requires both classes to be present")
    diff = positive[:, None] - negative[None, :]
    wins = float(np.sum(diff > 0)) + 0.5 * float(np.sum(diff == 0))
    return wins / float(positive.size * negative.size)


def calibration_slope_intercept(
    probs: np.ndarray, labels: np.ndarray, *, n_iterations: int = 500, learning_rate: float = 0.1
) -> tuple[float, float]:
    clipped = np.clip(np.asarray(probs, dtype=float), 1e-6, 1 - 1e-6)
    logits = torch.tensor(np.log(clipped / (1 - clipped)), dtype=torch.float32)
    y = torch.tensor(np.asarray(labels, dtype=float), dtype=torch.float32)
    slope = torch.tensor(1.0, requires_grad=True)
    intercept = torch.tensor(0.0, requires_grad=True)
    optimizer = torch.optim.Adam([slope, intercept], lr=learning_rate)
    loss_fn = nn.BCEWithLogitsLoss()
    for _ in range(n_iterations):
        optimizer.zero_grad()
        loss = loss_fn(slope * logits + intercept, y)
        loss.backward()
        optimizer.step()
    return float(slope.item()), float(intercept.item())


def reliability_diagram(
    probs: np.ndarray, labels: np.ndarray, n_bins: int = 10
) -> tuple[ReliabilityBin, ...]:
    probs = np.asarray(probs, dtype=float)
    labels = np.asarray(labels, dtype=float)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    bins: list[ReliabilityBin] = []
    for i in range(n_bins):
        lower, upper = float(edges[i]), float(edges[i + 1])
        mask = (probs >= lower) & (probs <= upper if i == n_bins - 1 else probs < upper)
        if not np.any(mask):
            continue
        bins.append(
            ReliabilityBin(
                bin_lower=lower,
                bin_upper=upper,
                mean_predicted=float(probs[mask].mean()),
                mean_actual=float(labels[mask].mean()),
                count=int(np.sum(mask)),
            )
        )
    return tuple(bins)


def _metrics_from_probabilities(probs: np.ndarray, labels: np.ndarray) -> ClassificationMetrics:
    try:
        auc = roc_auc(probs, labels)
    except ValueError:
        auc = None
    slope, intercept = calibration_slope_intercept(probs, labels)
    return ClassificationMetrics(
        n_samples=len(labels),
        n_positive=int(np.sum(labels)),
        brier_score=float(np.mean((probs - labels) ** 2)),
        roc_auc=auc,
        calibration_slope=slope,
        calibration_intercept=intercept,
        reliability=reliability_diagram(probs, labels),
        squared_errors=tuple(float(v) for v in (probs - labels) ** 2),
    )


def evaluate_model(
    model: nn.Module, features: np.ndarray, labels: np.ndarray
) -> ClassificationMetrics:
    model.eval()
    with torch.no_grad():
        logits = model(torch.tensor(features, dtype=torch.float32))
        probs = torch.sigmoid(logits).numpy()
    return _metrics_from_probabilities(probs, labels)


def evaluate_constant_probability(probability: float, labels: np.ndarray) -> ClassificationMetrics:
    probs = np.full(len(labels), probability, dtype=float)
    return _metrics_from_probabilities(probs, labels)


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    seed: int
    n_epochs: int
    metrics: dict[str, ClassificationMetrics]
    parameter_counts: dict[str, int]
    train_seconds: dict[str, float]
    best_classical_challenger: str
    quantum_vs_best_classical: BootstrapResult
    """CI for mean(quantum squared error) - mean(best-classical squared
    error) over the paired test set. `excludes_zero()` and a NEGATIVE
    point estimate together are the only honest basis for claiming the
    quantum model improved on its best classical challenger; this
    report never asserts that on its own."""
    run_manifest: RunManifest


_CLASSICAL_CANDIDATE_NAMES = ("base_rate", "logistic_regression", "classical_matched_mlp")


def run_recessionnet_benchmark(
    train: RecessionDataset,
    test: RecessionDataset,
    *,
    seed: int,
    n_epochs: int = 300,
    bootstrap_resamples: int = 2000,
) -> BenchmarkReport:
    if train.features.shape[1] != test.features.shape[1]:
        raise ValueError("train and test datasets must share the same feature width")

    input_dim = train.features.shape[1]
    metrics: dict[str, ClassificationMetrics] = {}
    parameter_counts: dict[str, int] = {}
    train_seconds: dict[str, float] = {}

    base_rate_probability = float(np.clip(train.labels.mean(), 1e-6, 1 - 1e-6))
    metrics["base_rate"] = evaluate_constant_probability(base_rate_probability, test.labels)
    parameter_counts["base_rate"] = 0
    train_seconds["base_rate"] = 0.0

    model_factories: dict[str, Callable[[], nn.Module]] = {
        "logistic_regression": lambda: LogisticRegressionClassifier(input_dim),
        "classical_matched_mlp": lambda: ClassicalMatchedClassifier(input_dim),
        "hybrid_quantum": lambda: HybridQuantumClassifier(input_dim),
    }
    for name, factory in model_factories.items():
        trained = train_classifier(
            factory, train.features, train.labels, seed=seed, n_epochs=n_epochs
        )
        metrics[name] = evaluate_model(trained.model, test.features, test.labels)
        parameter_counts[name] = trained.n_parameters
        train_seconds[name] = trained.train_seconds

    best_classical_challenger = min(
        _CLASSICAL_CANDIDATE_NAMES, key=lambda name: metrics[name].brier_score
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
            "train_features": train.features.tolist(),
            "train_labels": train.labels.tolist(),
            "test_features": test.features.tolist(),
            "test_labels": test.labels.tolist(),
        }
    )
    result_hash = compute_result_hash({name: m.brier_score for name, m in metrics.items()})
    manifest = RunManifest(
        run_id=new_run_id("recessionnet"),
        created_at=now_iso(),
        seed=seed,
        config={
            "n_epochs": n_epochs,
            "window": train.window,
            "horizon": train.horizon,
            "series_ids": list(train.series_ids),
        },
        result_hash=result_hash,
        code_hash=runtime_provenance()["source_sha256"],
        data_hash=data_hash,
        model_id="recessionnet-hybrid-quantum-v1",
    )

    return BenchmarkReport(
        seed=seed,
        n_epochs=n_epochs,
        metrics=metrics,
        parameter_counts=parameter_counts,
        train_seconds=train_seconds,
        best_classical_challenger=best_classical_challenger,
        quantum_vs_best_classical=bootstrap,
        run_manifest=manifest,
    )
