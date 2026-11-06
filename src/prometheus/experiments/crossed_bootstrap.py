"""Exploratory bootstrap of a mean over crossed training/test seed effects.

Rows identify independently retrained policies; columns identify independent
test-path banks shared by all policies. Resample complete rows and columns
independently (the pigeonhole construction, Owen 2007,
https://arxiv.org/abs/0712.1111), retaining the full Cartesian crossing.
Cells must not be flattened into falsely independent observations.

The endpoint is the mean of cell-level CVaR differences, not CVaR of pooled
losses. Percentile intervals here have no exact finite-sample guarantee,
especially with few training/test seeds. Single-axis intervals are
conditional diagnostics, not a decomposition into independent variances.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from prometheus.experiments.bootstrap import BootstrapResult


@dataclass(frozen=True, slots=True)
class CrossedBootstrapResult:
    crossed: BootstrapResult
    training_only: BootstrapResult
    evaluation_only: BootstrapResult
    training_seed_std: float
    test_bank_std: float
    n_training_seeds: int
    n_test_banks: int


def bonferroni_confidence(family_confidence: float, n_comparisons: int) -> float:
    """Allocate nominal tail error across a predeclared scenario family.

    Allocation does not establish that approximate bootstrap intervals have
    their nominal marginal coverage.
    """
    if not math.isfinite(family_confidence) or not 0 < family_confidence < 1:
        raise ValueError("family_confidence must be in (0, 1)")
    if type(n_comparisons) is not int or n_comparisons < 1:
        raise ValueError("n_comparisons must be a positive integer")
    confidence = 1.0 - (1.0 - family_confidence) / n_comparisons
    if confidence >= 1.0:
        raise ValueError("tail allocation is below floating-point resolution")
    return confidence


def crossed_mean_bootstrap(
    differences: np.ndarray,
    rng: np.random.Generator,
    *,
    n_resamples: int = 2_000,
    confidence: float = 0.95,
) -> CrossedBootstrapResult:
    values = np.asarray(differences, dtype=float)
    if values.ndim != 2 or min(values.shape) < 2:
        raise ValueError("differences must have at least two training rows and two test columns")
    if not np.all(np.isfinite(values)):
        raise ValueError("differences must be finite")
    if type(n_resamples) is not int or n_resamples < 1:
        raise ValueError("n_resamples must be a positive integer")
    if not math.isfinite(confidence) or not 0 < confidence < 1:
        raise ValueError("confidence must be in (0, 1)")

    n_training, n_banks = values.shape
    point = float(values.mean())
    training_draws = np.empty(n_resamples)
    evaluation_draws = np.empty(n_resamples)
    crossed_draws = np.empty(n_resamples)
    for index in range(n_resamples):
        rows = rng.integers(0, n_training, size=n_training)
        columns = rng.integers(0, n_banks, size=n_banks)
        training_draws[index] = values[rows, :].mean()
        evaluation_draws[index] = values[:, columns].mean()
        crossed_draws[index] = values[rows, :][:, columns].mean()

    def interval(draws: np.ndarray) -> BootstrapResult:
        tail = (1.0 - confidence) / 2.0
        low, high = np.quantile(draws, [tail, 1.0 - tail])
        return BootstrapResult(point, float(low), float(high), confidence, n_resamples)

    return CrossedBootstrapResult(
        crossed=interval(crossed_draws),
        training_only=interval(training_draws),
        evaluation_only=interval(evaluation_draws),
        training_seed_std=float(values.mean(axis=1).std(ddof=1)),
        test_bank_std=float(values.mean(axis=0).std(ddof=1)),
        n_training_seeds=n_training,
        n_test_banks=n_banks,
    )
