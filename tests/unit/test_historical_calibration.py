from datetime import date

import numpy as np
import pytest
from scipy.optimize import minimize

from prometheus.stochastica.historical_calibration import (
    CalibrationHistory,
    InsufficientDataError,
    calibrate_gbm_mle,
)


def _simulate_log_returns(
    mu: float, sigma: float, dt: float, n: int, rng: np.random.Generator
) -> np.ndarray:
    mean_r = (mu - 0.5 * sigma**2) * dt
    return rng.normal(mean_r, sigma * np.sqrt(dt), n)


def _neg_log_lik(params: tuple[float, float], data: np.ndarray, dt: float) -> float:
    mu, sigma = params
    if sigma <= 0:
        return 1e10
    mean_r = (mu - 0.5 * sigma**2) * dt
    var_r = sigma**2 * dt
    ll = -0.5 * np.log(2 * np.pi * var_r) - (data - mean_r) ** 2 / (2 * var_r)
    return float(-ll.sum())


def test_closed_form_mle_matches_a_tightly_converged_numerical_optimizer() -> None:
    """SDE-10's own closed-form claim, discriminating: cross-checked
    against a general-purpose numerical MLE search on the SAME data, not
    merely trusted from the textbook formula. (A loosely-converged
    optimizer run does NOT match -- GBM's drift is weakly identified, a
    known fact, not a bug -- so the comparison uses tight tolerances.)"""
    rng = np.random.default_rng(0)
    dt = 1 / 252
    log_returns = _simulate_log_returns(0.08, 0.25, dt, 2000, rng)
    record = calibrate_gbm_mle(
        log_returns, dt, date(2026, 1, 1), date(2026, 9, 1), date(2026, 9, 2)
    )

    numerical = minimize(
        _neg_log_lik,
        x0=[0.0, 0.1],
        args=(log_returns, dt),
        method="Nelder-Mead",
        options={"xatol": 1e-10, "fatol": 1e-12, "maxiter": 20_000, "maxfev": 20_000},
    )
    assert numerical.success
    assert record.mu == pytest.approx(numerical.x[0], abs=1e-4)
    assert record.sigma == pytest.approx(numerical.x[1], abs=1e-4)


def test_closed_form_mle_recovers_true_parameters_at_large_sample_size() -> None:
    rng = np.random.default_rng(1)
    true_mu, true_sigma, dt = 0.10, 0.20, 1 / 252
    log_returns = _simulate_log_returns(true_mu, true_sigma, dt, 50_000, rng)
    record = calibrate_gbm_mle(
        log_returns, dt, date(2020, 1, 1), date(2026, 1, 1), date(2026, 1, 2)
    )
    assert record.sigma == pytest.approx(true_sigma, abs=0.01)
    assert record.mu == pytest.approx(true_mu, abs=0.1)  # drift recovers much more slowly


def test_calibration_record_states_closed_form_optimizer_and_fit_window() -> None:
    rng = np.random.default_rng(2)
    dt = 1 / 252
    log_returns = _simulate_log_returns(0.05, 0.15, dt, 500, rng)
    record = calibrate_gbm_mle(
        log_returns, dt, date(2026, 1, 1), date(2026, 3, 1), date(2026, 3, 2)
    )
    assert record.optimizer == "closed_form_mle"
    assert record.fit_window_start == date(2026, 1, 1)
    assert record.fit_window_end == date(2026, 3, 1)
    assert record.calibrated_at == date(2026, 3, 2)
    assert record.n_observations == 500
    assert np.isfinite(record.calibration_error)


def test_rejects_fewer_than_two_observations() -> None:
    with pytest.raises(InsufficientDataError):
        calibrate_gbm_mle(
            np.array([0.01]), 1 / 252, date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)
        )


def test_rejects_a_zero_variance_sample() -> None:
    with pytest.raises(InsufficientDataError):
        calibrate_gbm_mle(
            np.zeros(10), 1 / 252, date(2026, 1, 1), date(2026, 1, 10), date(2026, 1, 11)
        )


def test_rejects_non_positive_dt() -> None:
    with pytest.raises(ValueError, match="dt"):
        calibrate_gbm_mle(
            np.array([0.01, -0.02, 0.015]), 0.0, date(2026, 1, 1), date(2026, 1, 3),
            date(2026, 1, 4),
        )


def test_rejects_an_inverted_fit_window() -> None:
    with pytest.raises(ValueError, match="fit_window_start"):
        calibrate_gbm_mle(
            np.array([0.01, -0.02, 0.015]), 1 / 252, date(2026, 1, 10), date(2026, 1, 1),
            date(2026, 1, 11),
        )


def test_rejects_calibrated_at_before_the_fit_window_ends() -> None:
    with pytest.raises(ValueError, match="calibrated_at"):
        calibrate_gbm_mle(
            np.array([0.01, -0.02, 0.015]), 1 / 252, date(2026, 1, 1), date(2026, 1, 10),
            date(2026, 1, 5),
        )


def test_calibration_history_as_of_returns_none_before_any_calibration() -> None:
    history = CalibrationHistory()
    assert history.as_of(date(2026, 1, 1)) is None


def test_calibration_history_as_of_returns_the_latest_eligible_version() -> None:
    """Dated parameter VERSIONS, not just a single snapshot: a second,
    later calibration must not be visible before its own calibrated_at,
    and must become the answer once it is."""
    history = CalibrationHistory()
    rng = np.random.default_rng(3)
    dt = 1 / 252
    first = calibrate_gbm_mle(
        _simulate_log_returns(0.05, 0.15, dt, 200, rng), dt,
        date(2026, 1, 1), date(2026, 3, 1), date(2026, 3, 2),
    )
    second = calibrate_gbm_mle(
        _simulate_log_returns(0.07, 0.18, dt, 200, rng), dt,
        date(2026, 3, 1), date(2026, 6, 1), date(2026, 6, 2),
    )
    history.record(first)
    history.record(second)

    assert history.as_of(date(2026, 3, 15)) == first  # second not yet calibrated
    assert history.as_of(date(2026, 6, 2)) == second  # second now eligible
    assert history.as_of(date(2027, 1, 1)) == second  # still the latest


def test_calibration_history_is_order_independent() -> None:
    """Recording out of chronological order must still answer correctly
    -- the as-of lookup is driven by calibrated_at, not insertion order."""
    history = CalibrationHistory()
    rng = np.random.default_rng(4)
    dt = 1 / 252
    first = calibrate_gbm_mle(
        _simulate_log_returns(0.05, 0.15, dt, 200, rng), dt,
        date(2026, 1, 1), date(2026, 3, 1), date(2026, 3, 2),
    )
    second = calibrate_gbm_mle(
        _simulate_log_returns(0.07, 0.18, dt, 200, rng), dt,
        date(2026, 3, 1), date(2026, 6, 1), date(2026, 6, 2),
    )
    history.record(second)
    history.record(first)
    assert history.as_of(date(2026, 3, 15)) == first
    assert history.as_of(date(2026, 6, 2)) == second
