"""Historical (physical-measure) GBM calibration with dated parameter
versions (SDE-10: "fit windows, optimizer state and calibration error
logged").

GBM's maximum-likelihood estimator is CLOSED FORM -- no iterative
optimizer is needed, and deliberately none is used here: an earlier
attempt at GARCH(1,1) historical calibration in this project, via
general-purpose numerical optimization (Nelder-Mead with a
reparameterization, SLSQP, trust-constr), was abandoned after
demonstrating genuine non-robustness -- slow convergence, a badly
identified mean parameter, and solver-dependent failure to converge
from some starting points -- unacceptable given this project's
zero-tolerance-for-flaky-tests standard. GBM carries no such risk: its
log-returns are i.i.d. Gaussian under the model, and the textbook
closed-form sample mean/variance formulas ARE the exact global MLE --
confirmed here, not merely assumed from theory, by cross-checking
against a tightly-converged general-purpose numerical optimizer
(Nelder-Mead minimizing the negative log-likelihood directly) across
multiple independent samples. A loosely-converged optimizer run did NOT
match the closed form at first (the likelihood is very flat along the
drift direction for realistic sample sizes, a known GBM drift-
identifiability fact); tightening its convergence tolerance resolved
the discrepancy, confirming the closed form, not the optimizer, was
right all along.

`CalibrationRecord.optimizer` is stated explicitly as
`"closed_form_mle"` rather than implying an iterative search happened.
`calibration_error` is the mean negative log-likelihood per observation
at the fitted parameters (lower is a better in-sample fit).
`CalibrationHistory` answers "which parameter version was in effect as
of date t" via the SAME point-in-time convention
`econosim.pit.PointInTimeStore` already established (the latest record
whose `calibrated_at <= t`, with no "give me the latest version
regardless of date" accessor) -- reused rather than reinvented.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np


class InsufficientDataError(ValueError):
    """Raised when fewer than 2 return observations are given, or the
    sample has exactly zero variance -- neither admits a meaningful
    GBM volatility estimate."""


@dataclass(frozen=True, slots=True)
class CalibrationRecord:
    fit_window_start: date
    fit_window_end: date
    calibrated_at: date
    mu: float
    sigma: float
    optimizer: str
    calibration_error: float
    n_observations: int


def calibrate_gbm_mle(
    log_returns: np.ndarray,
    dt: float,
    fit_window_start: date,
    fit_window_end: date,
    calibrated_at: date,
) -> CalibrationRecord:
    """Fits GBM's drift (`mu`) and volatility (`sigma`) to a series of
    log-returns observed over [fit_window_start, fit_window_end], via
    the closed-form MLE: sigma_hat = std(log_returns) / sqrt(dt),
    mu_hat = mean(log_returns) / dt + sigma_hat^2 / 2."""
    log_returns = np.asarray(log_returns, dtype=float)
    if log_returns.ndim != 1 or log_returns.size < 2:
        raise InsufficientDataError(
            f"need at least 2 return observations, got {log_returns.size}"
        )
    if dt <= 0:
        raise ValueError("dt must be positive")
    if fit_window_start > fit_window_end:
        raise ValueError("fit_window_start must not be after fit_window_end")
    if calibrated_at < fit_window_end:
        raise ValueError("calibrated_at cannot precede the fit window's own end")

    sigma_hat = float(log_returns.std(ddof=0) / np.sqrt(dt))
    if sigma_hat <= 0.0:
        raise InsufficientDataError("sample has exactly zero variance; no GBM fit exists")
    mu_hat = float(log_returns.mean() / dt + 0.5 * sigma_hat**2)

    mean_r = (mu_hat - 0.5 * sigma_hat**2) * dt
    var_r = sigma_hat**2 * dt
    nll = 0.5 * np.log(2.0 * np.pi * var_r) + (log_returns - mean_r) ** 2 / (2.0 * var_r)
    calibration_error = float(nll.mean())

    return CalibrationRecord(
        fit_window_start=fit_window_start,
        fit_window_end=fit_window_end,
        calibrated_at=calibrated_at,
        mu=mu_hat,
        sigma=sigma_hat,
        optimizer="closed_form_mle",
        calibration_error=calibration_error,
        n_observations=int(log_returns.size),
    )


class CalibrationHistory:
    """An append-only sequence of dated `CalibrationRecord`s, queryable
    only through the as-of predicate -- the same point-in-time
    discipline `econosim.pit.PointInTimeStore` already established,
    deliberately reused rather than reinvented: there is no "give me
    the latest version regardless of date" accessor, so a caller
    cannot accidentally use a future recalibration."""

    def __init__(self) -> None:
        self._records: list[CalibrationRecord] = []

    def record(self, calibration: CalibrationRecord) -> None:
        self._records.append(calibration)

    def as_of(self, t: date) -> CalibrationRecord | None:
        """The most recently calibrated record eligible as of t (i.e.
        `calibrated_at <= t`), or None if nothing is eligible yet."""
        eligible = [r for r in self._records if r.calibrated_at <= t]
        if not eligible:
            return None
        return max(eligible, key=lambda r: r.calibrated_at)
