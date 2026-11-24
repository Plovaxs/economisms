"""The Diebold-Mariano test of equal predictive accuracy, with the small-sample correction.

Diebold and Mariano (1995) test whether two forecasts have the same expected loss by treating the
loss differential `d_t = loss_1,t - loss_2,t` as a stationary series and asking whether its mean
is zero. Because the differentials of multi-step forecasts, and of overlapping or serially
dependent errors generally, are autocorrelated, the variance of the mean uses a long-run (HAC)
estimate: the autocovariances up to `lags`, weighted by a Bartlett kernel so the estimate stays
non-negative. For an `h`-step-ahead forecast the natural choice is `lags = h - 1`; more are allowed
for dependence of another origin (a 12-month window, say).

Harvey, Leybourne and Newbold (1997) show the plain statistic over-rejects in the small samples
forecasters actually have, and propose multiplying it by

    sqrt((n + 1 - 2h + h(h - 1)/n) / n)

and comparing it with Student's t on n - 1 degrees of freedom; both are done here by default.

Diebold (2015) cautions that the test was designed to compare FORECASTS, not models: a rejection
says one forecast was more accurate over this sample, not that its model is better. This module is
an exploratory tool for the repository's findings (the confirmatory protocol uses paired block
bootstrap intervals), added because the audit asked for it and it is the field's standard check.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from scipy import stats


@dataclass(frozen=True, slots=True)
class DieboldMarianoResult:
    n: int
    mean_loss_difference: float
    """Mean of `loss_1 - loss_2`: negative means forecast 1 has the smaller loss."""
    statistic: float
    p_value: float
    """Two-sided; Student's t on n - 1 degrees of freedom (the normal without the correction)."""
    horizon: int
    lags: int
    small_sample: bool


def long_run_variance(d: np.ndarray, lags: int) -> float:
    """Bartlett-weighted long-run variance of the mean of `d`, per observation (divide by n for the
    variance of the mean). `lags = 0` is the ordinary (biased, 1/n) sample variance."""
    n = d.size
    centred = d - d.mean()
    total = float(centred @ centred) / n
    for k in range(1, lags + 1):
        weight = 1.0 - k / (lags + 1.0)
        total += 2.0 * weight * float(centred[k:] @ centred[:-k]) / n
    return total


def diebold_mariano(
    loss_1: Sequence[float] | np.ndarray,
    loss_2: Sequence[float] | np.ndarray,
    *,
    horizon: int = 1,
    lags: int | None = None,
    small_sample: bool = True,
) -> DieboldMarianoResult:
    """Test `E[loss_1 - loss_2] = 0` against the two-sided alternative."""
    a = np.asarray(loss_1, dtype=np.float64)
    b = np.asarray(loss_2, dtype=np.float64)
    if a.ndim != 1 or a.shape != b.shape:
        raise ValueError("the two loss series must be 1-D and of the same length")
    if not (np.all(np.isfinite(a)) and np.all(np.isfinite(b))):
        raise ValueError("the loss series must be finite")
    n = int(a.size)
    if horizon < 1:
        raise ValueError("horizon must be at least 1")
    used_lags = horizon - 1 if lags is None else lags
    if used_lags < 0 or n < 3 or used_lags >= n:
        raise ValueError("need n >= 3 observations and 0 <= lags < n")
    d = a - b
    variance = long_run_variance(d, used_lags)
    if variance <= 0.0:
        raise ValueError(
            "the long-run variance of the loss differential is zero: the forecasts have identical "
            "losses, or the series is constant, and the statistic is undefined"
        )
    statistic = float(d.mean() / math.sqrt(variance / n))
    if small_sample:
        factor = math.sqrt((n + 1 - 2 * horizon + horizon * (horizon - 1) / n) / n)
        statistic *= factor
        p_value = float(2.0 * stats.t.sf(abs(statistic), n - 1))
    else:
        p_value = float(2.0 * stats.norm.sf(abs(statistic)))
    return DieboldMarianoResult(
        n=n,
        mean_loss_difference=float(d.mean()),
        statistic=statistic,
        p_value=p_value,
        horizon=horizon,
        lags=used_lags,
        small_sample=small_sample,
    )
