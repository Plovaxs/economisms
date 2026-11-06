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


def _broadcast_forecast(forecast: np.ndarray | float, shape: tuple[int, ...]) -> np.ndarray:
    return np.broadcast_to(np.asarray(forecast, dtype=float), shape)


def quantile_score(
    losses: np.ndarray, var_forecast: np.ndarray | float, alpha: float
) -> np.ndarray:
    """RISK-09: the pinball/quantile loss (Gneiting 2011) -- the strictly
    consistent scoring function for a quantile forecast, whose expectation
    is minimized exactly at the TRUE alpha-quantile (confirmed empirically
    against a known Gaussian reference -- the minimizer over a grid of
    candidate thresholds landed on the true quantile to within simulation
    noise -- before being trusted here). `var_forecast` may be a single
    constant threshold or a per-observation forecast array (the realistic
    backtesting case, e.g. a rolling GARCH-based VaR series); either way
    it is broadcast against `losses`.

    Lower mean score indicates a better-calibrated VaR forecast -- this
    RANKS competing VaR models, it is not itself a pass/fail test (pair it
    with `var_exception_coverage_test` for a calibration verdict)."""
    losses = _validate_losses(losses)
    _validate_alpha(alpha)
    var_forecast_arr = _broadcast_forecast(var_forecast, losses.shape)
    indicator = (losses < var_forecast_arr).astype(float)
    return np.asarray((losses - var_forecast_arr) * (alpha - indicator), dtype=float)


@dataclass(frozen=True, slots=True)
class ExceedanceResidualTestResult:
    n_observations: int
    n_exceedances: int
    mean_residual: float
    t_statistic: float
    p_value: float


def expected_shortfall_exceedance_residual_test(
    losses: np.ndarray,
    var_forecast: np.ndarray | float,
    es_forecast: np.ndarray | float,
) -> ExceedanceResidualTestResult:
    """RISK-09: the McNeil & Frey (2000) Expected Shortfall backtest.
    ES_alpha is defined as E[loss | loss > VaR_alpha] -- directly from
    that definition, the "exceedance residual" loss - es_forecast, taken
    only over observations where loss actually exceeds its var_forecast,
    must average to zero under correct calibration. A one-sample t-test
    of those residuals against zero is the diagnostic: a repeated-trial
    simulation confirmed its false-positive rate matches its nominal
    size under correct calibration, and that it reliably flags an ES
    forecast deliberately understating tail severity. Like
    `var_exception_coverage_test`, this is a diagnostic the caller
    interprets, not an automatic gate.

    `var_forecast`/`es_forecast` may be constants or per-observation
    arrays (broadcast against `losses`), supporting both a fixed
    threshold and a time-varying forecast series."""
    losses = _validate_losses(losses)
    var_forecast_arr = _broadcast_forecast(var_forecast, losses.shape)
    es_forecast_arr = _broadcast_forecast(es_forecast, losses.shape)
    exceeds = losses > var_forecast_arr
    n_exceedances = int(np.sum(exceeds))
    if n_exceedances < 2:
        raise ValueError(
            f"need at least 2 exceedances for a t-test, got {n_exceedances}"
        )
    residuals = losses[exceeds] - es_forecast_arr[exceeds]
    t_result = stats.ttest_1samp(residuals, 0.0)
    return ExceedanceResidualTestResult(
        n_observations=losses.size,
        n_exceedances=n_exceedances,
        mean_residual=float(residuals.mean()),
        t_statistic=float(t_result.statistic),
        p_value=float(t_result.pvalue),
    )


@dataclass(frozen=True, slots=True)
class EsCalibrationResult:
    n_observations: int
    n_exceedances: int
    statistic: float
    bootstrap_standard_error: float
    p_value: float


def _es_calibration_statistic(
    losses: np.ndarray, var_forecast_arr: np.ndarray, es_forecast_arr: np.ndarray, alpha: float
) -> np.ndarray:
    """Vectorized over a leading axis so the same code path handles both
    the single observed statistic and a batch of bootstrap resamples.
    `es_forecast_arr` divides each term INSIDE the sum (not the summed
    total), the correct generalization when the ES forecast varies by
    observation: E[loss_t * 1{loss_t>VaR_t}] = (1-alpha)*ES_t holds
    PER OBSERVATION, so each term must be normalized by its own ES_t
    before summing, not by one ES value applied to the aggregate."""
    n = losses.shape[-1]
    indicator = (losses > var_forecast_arr).astype(float)
    normalized_tail = np.sum(losses * indicator / es_forecast_arr, axis=-1)
    return np.asarray(normalized_tail / (n * (1.0 - alpha)) - 1.0, dtype=float)


def es_unconditional_calibration_test(
    losses: np.ndarray,
    var_forecast: np.ndarray | float,
    es_forecast: np.ndarray | float,
    alpha: float,
    rng: np.random.Generator,
    n_bootstrap: int = 1000,
) -> EsCalibrationResult:
    """RISK-09: an Acerbi-Szekely (2014)-style unconditional ES
    calibration statistic, usable even when there are zero VaR
    exceedances in-sample (unlike the exceedance-residual test above,
    which needs at least 2).

    By definition E[loss * 1{loss > VaR_alpha}] = (1 - alpha) * ES_alpha,
    so

        Z = sum(loss * 1{loss > VaR_forecast}) / (n * (1-alpha) * ES_forecast) - 1

    has expectation zero under correct calibration (a direct algebraic
    consequence of the ES definition, not a result that needed deriving
    from asymptotic theory). A repeated-trial simulation confirmed Z
    concentrates near zero under correct calibration and is strongly
    positive when the ES forecast understates tail severity, with no
    special-casing needed when a sample happens to have zero
    exceedances (the statistic is then exactly -1.0, a well-defined
    "no evidence of tail loss, relative to a positive ES forecast"
    reading, not a crash).

    The p-value comes from a nonparametric bootstrap standard error (an
    i.i.d. resample of the (loss, var_forecast, es_forecast) triples)
    combined with a normal approximation -- confirmed, via a repeated-
    trial simulation at a fixed nominal size, to produce a false-positive
    rate close to that nominal size. `rng` must be supplied explicitly
    (no hidden global random state)."""
    losses = _validate_losses(losses)
    _validate_alpha(alpha)
    var_forecast_arr = _broadcast_forecast(var_forecast, losses.shape)
    es_forecast_arr = _broadcast_forecast(es_forecast, losses.shape)
    if np.any(es_forecast_arr == 0.0):
        raise ValueError("es_forecast must be non-zero everywhere (it is used as a divisor)")
    if n_bootstrap < 2:
        raise ValueError("n_bootstrap must be at least 2")

    n = losses.size
    observed = float(_es_calibration_statistic(losses, var_forecast_arr, es_forecast_arr, alpha))

    idx = rng.integers(0, n, size=(n_bootstrap, n))
    boot_statistics = _es_calibration_statistic(
        losses[idx], var_forecast_arr[idx], es_forecast_arr[idx], alpha
    )
    bootstrap_se = float(np.std(boot_statistics, ddof=1))
    if bootstrap_se == 0.0:
        p_value = 0.0 if observed != 0.0 else 1.0
    else:
        p_value = float(2.0 * stats.norm.sf(abs(observed / bootstrap_se)))

    return EsCalibrationResult(
        n_observations=n,
        n_exceedances=int(np.sum(losses > var_forecast_arr)),
        statistic=observed,
        bootstrap_standard_error=bootstrap_se,
        p_value=p_value,
    )
