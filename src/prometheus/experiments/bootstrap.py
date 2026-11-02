"""Paired bootstrap confidence intervals (EXP-07).

Two policies here are always evaluated on the *identical* set of simulated
price paths (a paired design), so the bootstrap resamples path indices
once per resample and applies the same indices to both samples, preserving
whatever dependence exists between a path's outcome under policy A and
under policy B (e.g. both do worse on the same crash paths). An unpaired
bootstrap that resampled each sample's indices independently would throw
that dependence away and overstate the uncertainty.

The percentile method is used for the interval (sort the bootstrap
distribution of the difference, take the alpha/2 and 1-alpha/2 quantiles).
This is the simplest standard choice, not a claim that it is the most
accurate one for every situation (bias-corrected-and-accelerated, "BCa",
intervals can be tighter for skewed statistics).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    point_estimate: float
    ci_low: float
    ci_high: float
    confidence: float
    n_resamples: int

    def excludes_zero(self) -> bool:
        return self.ci_low > 0.0 or self.ci_high < 0.0


def paired_bootstrap_difference(
    metric_fn: Callable[[np.ndarray], float],
    sample_a: np.ndarray,
    sample_b: np.ndarray,
    rng: np.random.Generator,
    n_resamples: int = 2000,
    confidence: float = 0.95,
) -> BootstrapResult:
    """Percentile bootstrap CI for metric_fn(sample_a) - metric_fn(sample_b),
    where sample_a[i] and sample_b[i] are paired observations."""
    if sample_a.shape != sample_b.shape:
        raise ValueError("sample_a and sample_b must have matching shape (paired observations)")
    if sample_a.ndim != 1 or sample_a.size == 0:
        raise ValueError("samples must be non-empty 1-D arrays")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be in (0, 1)")
    if n_resamples < 1:
        raise ValueError("n_resamples must be >= 1")

    n = sample_a.size
    point_estimate = metric_fn(sample_a) - metric_fn(sample_b)

    diffs = np.empty(n_resamples)
    for i in range(n_resamples):
        idx = rng.integers(0, n, size=n)
        diffs[i] = metric_fn(sample_a[idx]) - metric_fn(sample_b[idx])

    alpha = 1.0 - confidence
    ci_low, ci_high = np.quantile(diffs, [alpha / 2, 1 - alpha / 2])
    return BootstrapResult(
        point_estimate=float(point_estimate),
        ci_low=float(ci_low),
        ci_high=float(ci_high),
        confidence=confidence,
        n_resamples=n_resamples,
    )
