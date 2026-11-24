"""The interval and decision rules the protocol applies to every endpoint.

Rule 4 (intervals): three primary endpoints, so each is reported with a two-sided `1 - 0.05/3`
interval (Bonferroni, a deliberately simple and conservative correction).
Rule 5 (outcome classes): for a paired effect `theta` (positive means the frozen model beats its
baseline) with interval `[L, U]` and an equivalence margin `delta` fixed in advance, checked in this
order:

    equivalent    -delta < L and U < delta   (a real but negligible difference is "equivalent")
    better        L > 0
    worse         U < 0
    inconclusive  otherwise

An interval that contains zero is NOT evidence of equality: only the first line says "equivalent",
and only because the whole interval sits inside the margin.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any, Literal

import numpy as np
from scipy import stats

from prometheus.experiments.block_bootstrap import moving_block_bootstrap

Outcome = Literal["better", "worse", "equivalent", "inconclusive"]

FAMILYWISE_ALPHA = 0.05
N_PRIMARY_ENDPOINTS = 3
"""E1, E2 and E3. E4 and the secondary statistics are not in the family."""


@dataclass(frozen=True, slots=True)
class Interval:
    estimate: float
    low: float
    high: float
    confidence: float
    n: int
    method: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def bonferroni_confidence(
    familywise_alpha: float = FAMILYWISE_ALPHA, n_endpoints: int = N_PRIMARY_ENDPOINTS
) -> float:
    """The two-sided confidence level of one endpoint's interval: `1 - alpha / k`."""
    if not 0.0 < familywise_alpha < 1.0:
        raise ValueError("familywise_alpha must be in (0, 1)")
    if n_endpoints < 1:
        raise ValueError("n_endpoints must be at least 1")
    return 1.0 - familywise_alpha / n_endpoints


def _finite_1d(sample: Sequence[float] | np.ndarray, minimum: int) -> np.ndarray:
    x = np.asarray(sample, dtype=np.float64)
    if x.ndim != 1 or x.size < minimum:
        raise ValueError(f"need a 1-D sample of at least {minimum} values")
    if not np.all(np.isfinite(x)):
        raise ValueError("the sample must contain only finite values")
    return x


def _check_confidence(confidence: float) -> None:
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be in (0, 1)")


def t_interval(sample: Sequence[float] | np.ndarray, confidence: float) -> Interval:
    """Student-t interval for a mean of independent observations (E1: one value per seed)."""
    _check_confidence(confidence)
    x = _finite_1d(sample, 2)
    n = int(x.size)
    mean = float(x.mean())
    half = float(stats.t.ppf(0.5 + confidence / 2.0, n - 1)) * float(x.std(ddof=1)) / math.sqrt(n)
    return Interval(
        mean, mean - half, mean + half, confidence, n, "t interval over independent seeds"
    )


def block_interval(
    sample: Sequence[float] | np.ndarray,
    *,
    block_length: int,
    confidence: float,
    n_resamples: int,
    seed: int,
) -> Interval:
    """Percentile moving-block-bootstrap interval for a mean of serially dependent differences
    (E2 and E3). The random generator is built here from `seed`: nothing global is touched."""
    _check_confidence(confidence)
    x = _finite_1d(sample, 1)
    result = moving_block_bootstrap(
        np.mean,
        x,
        block_length,
        np.random.default_rng(seed),
        n_resamples=n_resamples,
        confidence=confidence,
    )
    method = f"moving-block bootstrap, block {block_length}, {n_resamples} resamples, seed {seed}"
    return Interval(
        result.point_estimate, result.ci_low, result.ci_high, confidence, int(x.size), method
    )


def exact_binomial_interval(successes: int, trials: int, confidence: float) -> tuple[float, float]:
    """Clopper-Pearson interval for a proportion (E3: the exceedance rate)."""
    _check_confidence(confidence)
    if trials < 1 or not 0 <= successes <= trials:
        raise ValueError("need trials >= 1 and 0 <= successes <= trials")
    alpha = 1.0 - confidence
    low = (
        0.0
        if successes == 0
        else float(stats.beta.ppf(alpha / 2.0, successes, trials - successes + 1))
    )
    high = (
        1.0
        if successes == trials
        else float(stats.beta.ppf(1.0 - alpha / 2.0, successes + 1, trials - successes))
    )
    return low, high


def classify_effect(interval: Interval, margin: float) -> Outcome:
    """The protocol's rule 5, in the stated order."""
    if not math.isfinite(margin) or margin < 0.0:
        raise ValueError("margin must be a finite, non-negative number")
    if interval.low > interval.high:
        raise ValueError("an interval's low end cannot exceed its high end")
    if -margin < interval.low and interval.high < margin:
        return "equivalent"
    if interval.low > 0.0:
        return "better"
    if interval.high < 0.0:
        return "worse"
    return "inconclusive"
