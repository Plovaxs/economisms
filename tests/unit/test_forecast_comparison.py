"""The Diebold-Mariano test (audit item SCI-04): checked by hand, by its size and power, and by
the case it exists for, serially dependent loss differentials."""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy import stats

from prometheus.experiments.forecast_comparison import (
    diebold_mariano,
    long_run_variance,
)


def test_the_statistic_equals_a_hand_computation_for_one_step_forecasts() -> None:
    first = np.array([1.0, 2.5, 0.5, 3.0, 2.0, 1.5])
    second = np.array([0.5, 2.0, 1.5, 1.0, 1.0, 1.0])
    d = first - second
    n = d.size
    variance = float(np.mean((d - d.mean()) ** 2))  # lags = 0: the 1/n sample variance
    plain = d.mean() / math.sqrt(variance / n)
    corrected = plain * math.sqrt((n - 1) / n)  # Harvey-Leybourne-Newbold, h = 1
    got = diebold_mariano(first, second)
    assert got.statistic == pytest.approx(corrected)
    assert got.p_value == pytest.approx(2 * stats.t.sf(abs(corrected), n - 1))
    assert got.mean_loss_difference == pytest.approx(d.mean())
    uncorrected = diebold_mariano(first, second, small_sample=False)
    assert uncorrected.statistic == pytest.approx(plain)
    assert uncorrected.p_value == pytest.approx(2 * stats.norm.sf(abs(plain)))


def test_the_sign_says_which_forecast_has_the_smaller_loss() -> None:
    better = np.array([1.0, 1.1, 0.9, 1.0, 1.2, 0.8, 1.0, 1.1])
    worse = better + np.array([0.5, 0.4, 0.6, 0.5, 0.45, 0.55, 0.5, 0.5])
    result = diebold_mariano(better, worse)
    assert result.statistic < 0 and result.mean_loss_difference < 0 and result.p_value < 0.001
    assert diebold_mariano(worse, better).statistic == pytest.approx(-result.statistic)


def test_the_long_run_variance_adds_bartlett_weighted_autocovariances() -> None:
    d = np.array([1.0, -1.0, 2.0, -2.0, 1.5, -0.5, 0.5, 0.0])
    c = d - d.mean()
    n = d.size
    gamma0 = float(c @ c) / n
    gamma1 = float(c[1:] @ c[:-1]) / n
    gamma2 = float(c[2:] @ c[:-2]) / n
    assert long_run_variance(d, 0) == pytest.approx(gamma0)
    assert long_run_variance(d, 1) == pytest.approx(gamma0 + 2 * 0.5 * gamma1)
    assert long_run_variance(d, 2) == pytest.approx(
        gamma0 + 2 * (2 / 3) * gamma1 + 2 * (1 / 3) * gamma2
    )


def test_the_multi_step_horizon_sets_the_lags_and_the_small_sample_factor() -> None:
    rng = np.random.default_rng(5)
    a, b = rng.normal(size=40), rng.normal(size=40)
    h4 = diebold_mariano(a, b, horizon=4)
    assert h4.lags == 3 and h4.horizon == 4
    assert diebold_mariano(a, b, horizon=4, lags=7).lags == 7
    n = 40
    raw = diebold_mariano(a, b, horizon=4, small_sample=False).statistic
    assert h4.statistic == pytest.approx(raw * math.sqrt((n + 1 - 8 + 12 / n) / n))


def _rejection_rate(phi: float, lags: int, shift: float, sims: int, n: int, seed: int) -> float:
    rng = np.random.default_rng(seed)
    rejections = 0
    for _ in range(sims):
        e = rng.normal(size=n + 50)
        d = np.empty_like(e)
        d[0] = e[0]
        for t in range(1, e.size):
            d[t] = phi * d[t - 1] + e[t]
        d = d[50:] + shift
        if diebold_mariano(d, np.zeros(n), lags=lags).p_value < 0.05:
            rejections += 1
    return rejections / sims


def test_the_size_is_close_to_five_percent_for_independent_differentials() -> None:
    assert _rejection_rate(0.0, 0, 0.0, sims=3000, n=60, seed=1) == pytest.approx(0.05, abs=0.015)


def test_the_test_has_power_against_a_genuine_difference() -> None:
    assert _rejection_rate(0.0, 0, 0.6, sims=600, n=60, seed=2) > 0.8


def test_serial_dependence_ruins_the_naive_test_and_the_long_run_variance_repairs_it() -> None:
    """With AR(1) differentials (phi = 0.6) and no true difference, the naive test over-rejects
    badly; the HAC test with lags comes back toward 5%, which is why the audit asks for
    dependence-aware inference."""
    naive = _rejection_rate(0.6, 0, 0.0, sims=1500, n=120, seed=3)
    hac = _rejection_rate(0.6, 6, 0.0, sims=1500, n=120, seed=3)
    assert naive > 0.15
    assert hac < naive - 0.07 and hac == pytest.approx(0.07, abs=0.04)


@pytest.mark.parametrize(
    ("a", "b", "kwargs", "message"),
    [
        ([1.0, 2.0], [1.0, 2.0, 3.0], {}, "same length"),
        ([[1.0, 2.0], [3.0, 4.0]], [[1.0, 2.0], [3.0, 4.0]], {}, "1-D"),
        ([1.0, np.nan, 3.0], [1.0, 2.0, 3.0], {}, "finite"),
        ([1.0, 2.0], [2.0, 1.0], {}, "n >= 3"),
        ([1.0, 2.0, 3.0], [3.0, 2.0, 1.0], {"horizon": 0}, "horizon"),
        ([1.0, 2.0, 3.0, 5.0], [3.0, 2.0, 1.0, 1.0], {"lags": 4}, "lags"),
        ([1.0, 2.0, 3.0], [1.0, 2.0, 3.0], {}, "identical"),
    ],
)
def test_input_it_cannot_use_is_refused(a: list, b: list, kwargs: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        diebold_mariano(a, b, **kwargs)
