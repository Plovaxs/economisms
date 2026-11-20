"""PR-202: GARCH(1,1) / GJR-GARCH(1,1) by Gaussian QMLE.

Known-answer tests (returns simulated from KNOWN parameters, which the fit must recover), a
check of the vectorised variance filter against a plain loop, a causality test, and a
cross-check against the independent legacy `neural_sde.benchmark.fit_garch11`.
"""

from __future__ import annotations

import numpy as np
import pytest

from prometheus.neural_sde.benchmark import fit_garch11
from prometheus.titan.garch_family import (
    FittedGarchFamily,
    fit_garch_family,
    simulate_gjr_garch,
)

TRUE_GJR = {"mu": 0.0003, "omega": 2e-6, "alpha": 0.03, "gamma": 0.08, "beta": 0.90}
TRUE_SYMMETRIC = {"mu": 0.0003, "omega": 2e-6, "alpha": 0.06, "gamma": 0.0, "beta": 0.91}


@pytest.fixture(scope="module")
def gjr_returns() -> np.ndarray:
    return simulate_gjr_garch(30_000, seed=1, **TRUE_GJR)


@pytest.fixture(scope="module")
def symmetric_returns() -> np.ndarray:
    return simulate_gjr_garch(30_000, seed=2, **TRUE_SYMMETRIC)


def _loop_variances(fit: FittedGarchFamily, returns: np.ndarray) -> np.ndarray:
    """The textbook recursion, one observation at a time."""
    out = np.empty(returns.size)
    h = fit.initial_variance
    for t in range(returns.size):
        out[t] = h
        e = returns[t] - fit.mu
        h = fit.omega + (fit.alpha + fit.gamma * (e < 0.0)) * e * e + fit.beta * h
    return out


def test_the_vectorised_filter_matches_a_plain_loop() -> None:
    rng = np.random.default_rng(0)
    returns = rng.standard_t(5, 2_000) * 0.01
    fit = FittedGarchFamily(0.0002, 3e-6, 0.04, 0.07, 0.88, 1.2e-4, 0.0)
    assert fit.conditional_variances(returns) == pytest.approx(
        _loop_variances(fit, returns), rel=1e-12
    )


def test_the_variance_for_day_t_never_depends_on_day_t_or_later() -> None:
    """Slicing the filtered variances to a test window must not leak the future."""
    rng = np.random.default_rng(1)
    returns = rng.normal(0, 0.01, 500)
    fit = FittedGarchFamily(0.0, 2e-6, 0.05, 0.05, 0.9, 1e-4, 0.0)
    baseline = fit.conditional_variances(returns)
    altered = returns.copy()
    altered[300:] = rng.normal(0, 0.5, 200)  # a wildly different future
    assert np.array_equal(fit.conditional_variances(altered)[:301], baseline[:301])
    assert not np.array_equal(fit.conditional_variances(altered)[301:], baseline[301:])


def test_a_gjr_fit_recovers_known_parameters(gjr_returns: np.ndarray) -> None:
    fit = fit_garch_family(gjr_returns, asymmetric=True)
    assert fit.alpha == pytest.approx(TRUE_GJR["alpha"], abs=0.03)
    assert fit.gamma == pytest.approx(TRUE_GJR["gamma"], abs=0.04)
    assert fit.beta == pytest.approx(TRUE_GJR["beta"], abs=0.04)
    assert fit.persistence == pytest.approx(0.97, abs=0.02)
    assert fit.omega > 0.0 and fit.mu == pytest.approx(TRUE_GJR["mu"], abs=5e-4)


def test_a_symmetric_fit_recovers_garch_and_reports_exactly_zero_gamma(
    symmetric_returns: np.ndarray,
) -> None:
    fit = fit_garch_family(symmetric_returns, asymmetric=False)
    assert fit.gamma == 0.0
    assert fit.alpha == pytest.approx(0.06, abs=0.03)
    assert fit.beta == pytest.approx(0.91, abs=0.04)
    assert fit.persistence == pytest.approx(0.97, abs=0.02)


def test_the_asymmetric_fit_finds_leverage_where_it_exists_and_not_where_it_does_not(
    gjr_returns: np.ndarray, symmetric_returns: np.ndarray
) -> None:
    assert fit_garch_family(gjr_returns, asymmetric=True).gamma > 0.04
    assert fit_garch_family(symmetric_returns, asymmetric=True).gamma < 0.03


def test_the_fit_is_at_least_as_good_as_the_true_parameters(gjr_returns: np.ndarray) -> None:
    """A maximum-likelihood optimiser must not end below the truth's likelihood."""
    fit = fit_garch_family(gjr_returns, asymmetric=True)
    truth = FittedGarchFamily(
        mu=TRUE_GJR["mu"],
        omega=TRUE_GJR["omega"],
        alpha=TRUE_GJR["alpha"],
        gamma=TRUE_GJR["gamma"],
        beta=TRUE_GJR["beta"],
        initial_variance=fit.initial_variance,
        negative_log_likelihood=0.0,
    )
    assert (
        fit.negative_log_likelihood_of(gjr_returns)
        <= truth.negative_log_likelihood_of(gjr_returns) + 1e-6
    )
    # and the stored training likelihood (decimal units) agrees with recomputing it
    assert fit.negative_log_likelihood == pytest.approx(
        fit.negative_log_likelihood_of(gjr_returns), rel=1e-6
    )


def test_the_persistence_cap_is_respected_and_binds_on_integrated_data() -> None:
    returns = simulate_gjr_garch(
        20_000, seed=3, mu=0.0, omega=5e-7, alpha=0.10, gamma=0.0, beta=0.895
    )
    capped = fit_garch_family(returns, asymmetric=False, max_persistence=0.95)
    assert capped.persistence <= 0.95 + 1e-6
    assert capped.persistence > 0.93, "the cap, not the data, set the persistence"
    free = fit_garch_family(returns, asymmetric=False, max_persistence=0.999)
    assert free.persistence > capped.persistence
    assert free.negative_log_likelihood < capped.negative_log_likelihood


def test_standardised_residuals_of_a_correct_model_are_close_to_standard_normal(
    gjr_returns: np.ndarray,
) -> None:
    fit = fit_garch_family(gjr_returns, asymmetric=True)
    z = fit.standardised_residuals(gjr_returns)
    assert abs(float(z.mean())) < 0.03 and float(z.std()) == pytest.approx(1.0, abs=0.03)
    assert abs(float(np.mean(z**4) - 3.0)) < 0.3, "no excess kurtosis left"


def test_the_symmetric_special_case_agrees_with_the_independent_legacy_fitter() -> None:
    """`neural_sde.benchmark.fit_garch11` is a different optimiser with a 0.98 cap; with
    the same cap the two must describe the same volatility process."""
    returns = simulate_gjr_garch(
        8_000, seed=4, mu=0.0, omega=3e-6, alpha=0.07, gamma=0.0, beta=0.90
    )
    ours = fit_garch_family(returns, asymmetric=False, max_persistence=0.98)
    legacy = fit_garch11(returns)
    assert ours.persistence == pytest.approx(legacy.alpha + legacy.beta, abs=0.02)
    legacy_h = legacy.conditional_variances(returns)
    assert float(np.corrcoef(ours.conditional_variances(returns), legacy_h)[0, 1]) > 0.99


@pytest.mark.parametrize(
    ("returns", "kwargs", "message"),
    [
        (np.zeros(500), {}, "zero variance"),
        (np.ones(50), {}, "at least 100"),
        (np.full(500, np.nan), {}, "finite"),
        (np.arange(500.0).reshape(100, 5), {}, "1-D"),
        (np.random.default_rng(0).normal(0, 0.01, 500), {"max_persistence": 1.0}, "strictly"),
        (np.random.default_rng(0).normal(0, 0.01, 500), {"max_persistence": 0.0}, "strictly"),
    ],
)
def test_bad_inputs_are_rejected_by_name(
    returns: np.ndarray, kwargs: dict[str, float], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        fit_garch_family(returns, asymmetric=True, **kwargs)


def test_a_non_stationary_simulation_is_refused() -> None:
    with pytest.raises(ValueError, match="persistence below 1"):
        simulate_gjr_garch(100, seed=0, mu=0.0, omega=1e-6, alpha=0.1, gamma=0.1, beta=0.95)


def test_the_simulation_is_reproducible_and_has_the_leverage_signature() -> None:
    a = simulate_gjr_garch(5_000, seed=9, **TRUE_GJR)
    assert np.array_equal(a, simulate_gjr_garch(5_000, seed=9, **TRUE_GJR))
    h = FittedGarchFamily(**TRUE_GJR, initial_variance=1e-4, negative_log_likelihood=0.0)
    variance = h.conditional_variances(a)
    after_negative = variance[1:][a[:-1] < TRUE_GJR["mu"]].mean()
    after_positive = variance[1:][a[:-1] >= TRUE_GJR["mu"]].mean()
    assert after_negative > after_positive, "bad news raises next-day variance more"
