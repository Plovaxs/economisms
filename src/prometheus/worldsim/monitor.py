"""Early-warning indicators, alert levels, and a test of whether they warn before a crisis.

The composite averages the expanding-window z-scores of four indicators: equity volatility (EWMA,
lambda 0.94), the weakest bank's capital ratio (inverted), the output gap (inverted) and twelve-
month loan growth. It is NaN for the first `BURN_IN` months. Amber from 1, red from 2. Whether it
warns is measured only on months that are not already in a crisis: the label is "a crisis begins
within the next HORIZON months".
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.stats import rankdata

from prometheus.worldsim.config import CRISIS
from prometheus.worldsim.world import WorldPath

BURN_IN = 36
HORIZON = 6
AMBER = 1.0
RED = 2.0
EWMA_LAMBDA = 0.94


@dataclass(frozen=True, slots=True)
class Indicators:
    volatility: np.ndarray
    min_capital_ratio: np.ndarray
    output_gap: np.ndarray
    credit_growth: np.ndarray
    composite: np.ndarray
    alert: np.ndarray  # 0 green, 1 amber, 2 red


def ewma_volatility(returns: np.ndarray) -> np.ndarray:
    variance = np.zeros(returns.size)
    variance[0] = float(returns[: min(12, returns.size)].var()) + 1e-8
    for t in range(1, returns.size):
        variance[t] = EWMA_LAMBDA * variance[t - 1] + (1.0 - EWMA_LAMBDA) * returns[t - 1] ** 2
    return np.asarray(np.sqrt(variance * 12.0), dtype=np.float64)


def _expanding_z(values: np.ndarray) -> np.ndarray:
    z = np.full(values.size, np.nan)
    for t in range(BURN_IN, values.size):
        window = values[:t]
        std = float(window.std())
        z[t] = 0.0 if std <= 1e-12 else (values[t] - float(window.mean())) / std
    return z


def indicators(path: WorldPath) -> Indicators:
    volatility = ewma_volatility(path.asset_returns[:, 0])
    alive_ratio = np.where(path.bank_failed, np.nan, path.bank_capital_ratio)
    with np.errstate(all="ignore"):
        weakest = np.nanmin(np.where(np.isnan(alive_ratio), np.inf, alive_ratio), axis=1)
    weakest = np.where(np.isinf(weakest), 0.0, weakest)
    credit = np.zeros(path.n_months)
    credit[12:] = path.total_loans[12:] / np.maximum(path.total_loans[:-12], 1e-9) - 1.0
    stacked = np.vstack(
        [
            _expanding_z(volatility),
            _expanding_z(-weakest),
            _expanding_z(-path.output_gap),
            _expanding_z(credit),
        ]
    )
    defined = ~np.isnan(stacked)
    composite = np.where(
        defined.all(axis=0), np.where(defined, stacked, 0.0).sum(axis=0) / stacked.shape[0], np.nan
    )
    alert = np.where(composite >= RED, 2, np.where(composite >= AMBER, 1, 0)).astype(np.int64)
    return Indicators(volatility, weakest, path.output_gap, credit, composite, alert)


def warning_samples(path: WorldPath, composite: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(score, label) for each non-crisis month with a defined score and a full horizon."""
    n = path.n_months
    scores: list[float] = []
    labels: list[bool] = []
    for t in range(BURN_IN, n - HORIZON):
        if path.regime[t] == CRISIS or np.isnan(composite[t]):
            continue
        ahead = path.regime[t + 1 : t + 1 + HORIZON]
        scores.append(float(composite[t]))
        labels.append(bool(np.any(ahead == CRISIS)))
    return np.array(scores), np.array(labels, dtype=bool)


def auc(scores: np.ndarray, labels: np.ndarray) -> float:
    """Chance that a random positive outscores a random negative (ties count half)."""
    positives, negatives = scores[labels], scores[~labels]
    if positives.size == 0 or negatives.size == 0:
        return float("nan")
    ranks = rankdata(np.concatenate([positives, negatives]))
    u = ranks[: positives.size].sum() - positives.size * (positives.size + 1) / 2.0
    return float(u / (positives.size * negatives.size))
