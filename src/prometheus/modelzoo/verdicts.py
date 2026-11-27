"""The decision rules the model-zoo studies use, written once so that every study judges the same
way.

A claim is one of three things at the end: SUPPORTED, CONTRADICTED or INCONCLUSIVE. Nothing is
promoted to SUPPORTED on a point estimate.

* `direction_verdict`: for a claim "this paired difference is positive" (for example, error of
model B
  minus error of model A), the 95% bootstrap interval of the mean over seeds must lie wholly above
  zero
  to support it and wholly below zero to contradict it.
* `threshold_verdict`: for a claim "this error is at most x", the median over seeds must be at
most x to
  support it, above `contradicted_above` to contradict it, and is inconclusive between.
"""

from __future__ import annotations

import numpy as np


def paired_bootstrap_ci(
    values: list[float] | np.ndarray,
    *,
    seed: int = 0,
    replications: int = 4000,
    level: float = 0.95,
) -> tuple[float, float]:
    data = np.asarray(values, dtype=float)
    if data.size < 2:
        raise ValueError("a bootstrap interval needs at least two seeds")
    rng = np.random.default_rng(seed)
    means = rng.choice(data, size=(replications, data.size), replace=True).mean(axis=1)
    tail = (1.0 - level) / 2.0
    return float(np.quantile(means, tail)), float(np.quantile(means, 1.0 - tail))


def direction_verdict(low: float, high: float) -> str:
    if low > 0.0:
        return "SUPPORTED"
    if high < 0.0:
        return "CONTRADICTED"
    return "INCONCLUSIVE"


def threshold_verdict(median: float, supported_at_most: float, contradicted_above: float) -> str:
    if supported_at_most > contradicted_above:
        raise ValueError("the support threshold must not exceed the contradiction threshold")
    if median <= supported_at_most:
        return "SUPPORTED"
    if median > contradicted_above:
        return "CONTRADICTED"
    return "INCONCLUSIVE"


def summarise_difference(values: list[float] | np.ndarray, *, seed: int = 0) -> dict[str, object]:
    low, high = paired_bootstrap_ci(values, seed=seed)
    return {
        "mean": float(np.mean(values)),
        "low": low,
        "high": high,
        "seeds": int(len(values)),
        "verdict": direction_verdict(low, high),
    }
