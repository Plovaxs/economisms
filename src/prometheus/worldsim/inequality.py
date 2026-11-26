"""Inequality measures of a wealth vector."""

from __future__ import annotations

import numpy as np


def gini(values: np.ndarray) -> float:
    sorted_values = np.sort(np.clip(values, 0.0, None))
    n = sorted_values.size
    total = float(sorted_values.sum())
    if total <= 0.0:
        return 0.0
    index = np.arange(1, n + 1)
    return float((2.0 * np.sum(index * sorted_values)) / (n * total) - (n + 1.0) / n)


def shares(values: np.ndarray) -> tuple[float, float]:
    ordered = np.sort(np.clip(values, 0.0, None))
    total = float(ordered.sum())
    if total <= 0.0:
        return 0.0, 0.0
    n = ordered.size
    return float(ordered[int(0.9 * n) :].sum() / total), float(ordered[: n // 2].sum() / total)
