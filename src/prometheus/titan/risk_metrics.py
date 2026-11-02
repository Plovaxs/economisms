"""Historical/parametric VaR, Expected Shortfall, drawdown and VaR-exception
coverage testing.

Sign convention: a *loss* is positive when money is lost. If you have a
P&L series (positive = gain), convert with pnl_to_losses() first.
VaR_alpha(L) is the alpha-quantile of the loss distribution; ES_alpha(L) =
E[L | L >= VaR_alpha(L)] (section 3.4 of the specification). Every function
here requires an explicit alpha and declares its interpolation/estimator
choice in its docstring (RISK-02's "horizon, alpha, losses and
interpolation declared" -- "horizon" itself is the caller's responsibility:
these functions are horizon-agnostic over whatever period the input array
already represents).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np
from scipy import stats

QuantileInterpolation = Literal[
    "linear", "lower", "higher", "midpoint", "nearest", "inverted_cdf"
]


def pnl_to_losses(pnl: np.ndarray) -> np.ndarray:
    return -np.asarray(pnl, dtype=float)


def _validate_losses(losses: np.ndarray) -> np.ndarray:
    losses = np.asarray(losses, dtype=float)
    if losses.ndim != 1 or losses.size == 0:
        raise ValueError("losses must be a non-empty 1-D array")
    return losses


def _validate_alpha(alpha: float) -> None:
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be in (0, 1)")


def historical_var(
    losses: np.ndarray, alpha: float, interpolation: QuantileInterpolation = "linear"
) -> float:
    """Empirical alpha-quantile of the loss sample (RISK-02). `interpolation`
    is passed straight through to numpy.quantile's `method` argument --
    "linear" (numpy's default) is the declared convention here."""
    losses = _validate_losses(losses)
    _validate_alpha(alpha)
    return float(np.quantile(losses, alpha, method=interpolation))


def parametric_var(mean: float, std: float, alpha: float) -> float:
    """VaR under an assumed Gaussian loss distribution N(mean, std^2) (RISK-03)."""
    if std < 0:
        raise ValueError("std must be non-negative")
    _validate_alpha(alpha)
    return float(mean + std * stats.norm.ppf(alpha))


def historical_expected_shortfall(losses: np.ndarray, alpha: float) -> float:
    """Tie/atom-safe empirical Expected Shortfall (RISK-04): the
    quantile-integral estimator applied directly to order statistics.

    With sorted losses L_(1) <= ... <= L_(n) and k = ceil(alpha * n):

        ES_alpha = [ sum_{i=k+1}^{n} L_(i) + (k - alpha*n) * L_(k) ]
                   / (n * (1 - alpha))

    This handles repeated loss values (ties) correctly with no special
    casing -- it operates on order statistics, not distinct values -- and
    handles n*(1-alpha) not being an integer via a partial weight on the
    boundary order statistic L_(k), rather than silently rounding the tail
    size to the nearest whole observation.
    """
    losses = _validate_losses(losses)
    _validate_alpha(alpha)
    n = losses.size
    sorted_losses = np.sort(losses)
    k = min(math.ceil(alpha * n), n)
    tail_sum = sorted_losses[k:].sum()
    boundary_value = sorted_losses[k - 1]
    boundary_weight = k - alpha * n
    numerator = tail_sum + boundary_weight * boundary_value
    denominator = n * (1 - alpha)
    return float(numerator / denominator)


def max_drawdown(cumulative_values: np.ndarray) -> float:
    """RISK-06: the most negative peak-to-trough decline in a cumulative
    P&L or portfolio-value series. Returns a value <= 0 (0 if the series
    never falls below its running maximum)."""
    cumulative_values = np.asarray(cumulative_values, dtype=float)
    if cumulative_values.ndim != 1 or cumulative_values.size == 0:
        raise ValueError("cumulative_values must be a non-empty 1-D array")
    running_max = np.maximum.accumulate(cumulative_values)
    drawdowns = cumulative_values - running_max
    return float(drawdowns.min())


@dataclass(frozen=True, slots=True)
class VarCoverageResult:
    n_observations: int
    n_exceptions: int
    expected_exception_rate: float
    observed_exception_rate: float
    p_value: float


def var_exception_coverage_test(
    losses: np.ndarray, var_threshold: float, alpha: float
) -> VarCoverageResult:
    """RISK-08: an exact two-sided binomial (Kupiec-style unconditional
    coverage) test of whether the observed count of VaR exceptions (losses
    strictly greater than var_threshold) is consistent with the expected
    exception rate (1 - alpha) under the null hypothesis that the VaR model
    is correctly calibrated. A low p-value is evidence against calibration,
    not proof against it -- this is a diagnostic, not an automatic pass/fail
    gate, and the caller decides what p-value threshold to act on."""
    losses = _validate_losses(losses)
    _validate_alpha(alpha)
    n = losses.size
    n_exceptions = int(np.sum(losses > var_threshold))
    expected_rate = 1.0 - alpha
    test_result = stats.binomtest(n_exceptions, n, expected_rate, alternative="two-sided")
    return VarCoverageResult(
        n_observations=n,
        n_exceptions=n_exceptions,
        expected_exception_rate=expected_rate,
        observed_exception_rate=n_exceptions / n,
        p_value=float(test_result.pvalue),
    )
