import numpy as np
import pytest

from prometheus.stochastica.garch import (
    GarchParams,
    autocorrelation,
    simulate_garch_paths,
    volatility_clustering_diagnostics,
)


def _params(**overrides: float) -> GarchParams:
    defaults: dict = dict(mu=0.0, omega=0.00001, alpha=0.08, beta=0.90)
    defaults.update(overrides)
    return GarchParams(**defaults)


def test_rejects_non_positive_omega() -> None:
    with pytest.raises(ValueError, match="omega"):
        _params(omega=0.0)
    with pytest.raises(ValueError, match="omega"):
        _params(omega=-1e-5)


def test_rejects_negative_alpha_or_beta() -> None:
    with pytest.raises(ValueError, match="alpha"):
        _params(alpha=-0.1)
    with pytest.raises(ValueError, match="beta"):
        _params(beta=-0.1)


def test_rejects_the_non_stationary_regime() -> None:
    """Bollerslev's condition alpha+beta<1; at or above it the
    unconditional variance is infinite/undefined, so this must be
    rejected upfront rather than silently simulated."""
    with pytest.raises(ValueError, match="stationarity"):
        _params(alpha=0.5, beta=0.5)
    with pytest.raises(ValueError, match="stationarity"):
        _params(alpha=0.6, beta=0.5)


def test_rejects_nan_and_inf_fields() -> None:
    with pytest.raises(ValueError, match="finite"):
        _params(mu=float("nan"))
    with pytest.raises(ValueError, match="finite"):
        _params(omega=float("inf"))


def test_unconditional_variance_matches_the_closed_form() -> None:
    p = _params(omega=0.00001, alpha=0.08, beta=0.90)
    assert p.unconditional_variance() == pytest.approx(0.00001 / (1 - 0.08 - 0.90))


def test_long_run_sample_variance_matches_the_unconditional_variance() -> None:
    """Independent cross-check (this project's established discipline):
    a long simulation's realized variance should match the closed-form
    unconditional variance within sampling noise."""
    p = _params()
    rng = np.random.default_rng(0)
    returns, h = simulate_garch_paths(p, n_steps=200_000, n_paths=1, rng=rng)
    theory_var = p.unconditional_variance()
    # Var(Var_hat) for a sample variance of n draws from a distribution
    # with excess kurtosis is not simply 2*theory_var^2/n (GARCH returns
    # are fat-tailed), so a generous relative band is used instead of a
    # tight analytic standard error.
    assert abs(returns.var() - theory_var) / theory_var < 0.15
    assert h.mean() == pytest.approx(theory_var, rel=0.15)


def test_paths_are_always_finite() -> None:
    p = _params()
    rng = np.random.default_rng(1)
    returns, h = simulate_garch_paths(p, n_steps=1000, n_paths=200, rng=rng)
    assert np.all(np.isfinite(returns))
    assert np.all(np.isfinite(h))
    assert np.all(h > 0.0)


def test_shapes_and_default_initial_variance() -> None:
    p = _params()
    rng = np.random.default_rng(2)
    returns, h = simulate_garch_paths(p, n_steps=10, n_paths=5, rng=rng)
    assert returns.shape == (5, 10)
    assert h.shape == (5, 10)
    # h[:, 0] = omega + alpha*h0 + beta*h0, with h0 the unconditional variance
    expected_h0 = p.omega + (p.alpha + p.beta) * p.unconditional_variance()
    assert h[:, 0] == pytest.approx(expected_h0)


def test_rejects_non_positive_initial_variance() -> None:
    p = _params()
    rng = np.random.default_rng(0)
    with pytest.raises(ValueError, match="initial_variance"):
        simulate_garch_paths(p, n_steps=10, n_paths=5, rng=rng, initial_variance=0.0)
    with pytest.raises(ValueError, match="initial_variance"):
        simulate_garch_paths(p, n_steps=10, n_paths=5, rng=rng, initial_variance=float("nan"))


def test_extreme_omega_near_the_representable_range_raises_a_clear_error() -> None:
    """SDE-12-style discipline applied to this new model too: omega
    large enough that the unconditional variance itself approaches
    float64's representable range eventually overflows a squared
    deviation deep in the recursion; raises a clear ValueError rather
    than returning a silent inf."""
    p = GarchParams(mu=0.0, omega=1e306, alpha=0.08, beta=0.90)
    rng = np.random.default_rng(0)
    with pytest.raises(ValueError, match="non-finite"):
        simulate_garch_paths(p, n_steps=20, n_paths=5000, rng=rng)


def test_rejects_non_positive_steps_or_paths() -> None:
    p = _params()
    rng = np.random.default_rng(0)
    with pytest.raises(ValueError):
        simulate_garch_paths(p, n_steps=0, n_paths=5, rng=rng)
    with pytest.raises(ValueError):
        simulate_garch_paths(p, n_steps=10, n_paths=0, rng=rng)


def test_autocorrelation_on_a_single_1d_series() -> None:
    """The 1D branch, exercised directly rather than only through a
    multi-path batch -- a known AR(1)-like series should show the
    expected decaying positive autocorrelation."""
    rng = np.random.default_rng(5)
    n = 2000
    x = np.empty(n)
    x[0] = 0.0
    phi = 0.6
    for t in range(1, n):
        x[t] = phi * x[t - 1] + rng.standard_normal()
    acf = autocorrelation(x, max_lag=3)
    assert acf.shape == (3,)
    assert acf[0] == pytest.approx(phi, abs=0.1)
    assert acf[0] > acf[1] > acf[2] > 0


def test_autocorrelation_rejects_invalid_max_lag() -> None:
    x = np.arange(10.0)
    with pytest.raises(ValueError, match="max_lag"):
        autocorrelation(x, 0)
    with pytest.raises(ValueError, match="max_lag"):
        autocorrelation(x, 10)


def test_autocorrelation_rejects_wrong_dimensionality() -> None:
    with pytest.raises(ValueError, match="1D or 2D"):
        autocorrelation(np.zeros((2, 3, 4)), 1)


def test_batched_autocorrelation_matches_per_path_aggregation_not_naive_flattening() -> None:
    """The documented bug `autocorrelation`'s own docstring warns about:
    flattening a (n_paths, n_steps) batch into one concatenated series
    before computing ACF spuriously pairs the last observation of one
    path with the first of the next at every path boundary. Confirmed
    here directly against a hand-computed aggregate that sums the
    numerator/denominator across paths without ever concatenating."""
    rng = np.random.default_rng(3)
    x = rng.standard_normal((50, 30))
    lag = 2
    result = autocorrelation(x, max_lag=lag)[lag - 1]

    centered = x - x.mean()
    expected = np.sum(centered[:, :-lag] * centered[:, lag:]) / np.sum(centered**2)
    assert result == pytest.approx(expected)

    naive_flatten = np.sum((x.reshape(-1) - x.mean())[:-lag] * (x.reshape(-1) - x.mean())[lag:])
    naive_flatten /= np.sum(centered**2)
    # The two should differ (boundary contamination is real, not a
    # distinction without a difference), even if only slightly here.
    assert result != pytest.approx(naive_flatten, abs=0.0)


def test_garch_squared_returns_show_volatility_clustering_unlike_iid_returns() -> None:
    """The literal SDE-07 behavioral signature: GARCH-simulated squared
    returns must show meaningfully positive autocorrelation (volatility
    clustering), while i.i.d. Gaussian returns with the SAME
    unconditional variance must not -- a contrasting negative control,
    not just "the function runs"."""
    p = _params(omega=0.00001, alpha=0.08, beta=0.90)
    rng = np.random.default_rng(4)
    returns, h = simulate_garch_paths(p, n_steps=5000, n_paths=100, rng=rng)
    diag = volatility_clustering_diagnostics(returns, h, max_lag=5)

    assert np.all(diag.squared_return_autocorrelation > 0.1)
    assert np.all(diag.absolute_return_autocorrelation > 0.1)
    assert diag.mean_conditional_variance == pytest.approx(
        p.unconditional_variance(), rel=0.15
    )

    iid_returns = rng.normal(p.mu, np.sqrt(p.unconditional_variance()), size=returns.shape)
    iid_acf = autocorrelation(iid_returns**2, max_lag=5)
    assert np.all(np.abs(iid_acf) < 0.05)
