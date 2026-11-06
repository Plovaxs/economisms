import numpy as np
import pytest

from prometheus.stochastica.heston import HestonParams, simulate_heston_paths


def _comfortable_feller_params() -> HestonParams:
    return HestonParams(mu=0.03, kappa=2.0, theta=0.04, xi=0.2, rho=-0.5, v0=0.04)


def test_rejects_invalid_params() -> None:
    with pytest.raises(ValueError):
        HestonParams(mu=0.0, kappa=-1.0, theta=0.04, xi=0.2, rho=0.0, v0=0.04)
    with pytest.raises(ValueError):
        HestonParams(mu=0.0, kappa=1.0, theta=0.04, xi=0.2, rho=1.5, v0=0.04)
    with pytest.raises(ValueError):
        HestonParams(mu=0.0, kappa=1.0, theta=0.04, xi=0.2, rho=0.0, v0=-0.01)


def test_rejects_nan_and_inf_fields() -> None:
    """VAL-13 ("perform NaN/Inf injection and solver fail-closed
    tests... no invalid output promoted or silently cached"): an
    ordinary `if kappa <= 0: raise` silently admits NaN (every
    comparison involving NaN is False), so before `require_finite` was
    added, `HestonParams(kappa=float("nan"), ...)` raised nothing and
    the NaN propagated silently into pricing/simulation."""
    with pytest.raises(ValueError, match="finite"):
        HestonParams(mu=float("nan"), kappa=2.0, theta=0.04, xi=0.2, rho=-0.5, v0=0.04)
    with pytest.raises(ValueError, match="finite"):
        HestonParams(mu=0.0, kappa=float("inf"), theta=0.04, xi=0.2, rho=-0.5, v0=0.04)


def test_feller_ratio_matches_definition() -> None:
    params = HestonParams(mu=0.0, kappa=2.0, theta=0.04, xi=0.2, rho=0.0, v0=0.04)
    assert params.feller_ratio() == pytest.approx(2 * 2.0 * 0.04 / 0.2**2)


def test_variance_path_never_negative() -> None:
    """Positivity holds by construction (full-truncation floor); this test
    is a defensive check that the floor was not silently bypassed."""
    rng = np.random.default_rng(3)
    params = HestonParams(mu=0.03, kappa=0.5, theta=0.02, xi=0.9, rho=-0.7, v0=0.01)
    _, v = simulate_heston_paths(100.0, params, 1.0, n_steps=252, n_paths=5_000, rng=rng)
    assert np.all(v >= 0.0)


def test_price_path_never_negative_or_nan() -> None:
    rng = np.random.default_rng(4)
    params = HestonParams(mu=0.03, kappa=0.5, theta=0.02, xi=0.9, rho=-0.7, v0=0.01)
    s, _ = simulate_heston_paths(100.0, params, 1.0, n_steps=252, n_paths=5_000, rng=rng)
    assert np.all(s > 0.0)
    assert not np.any(np.isnan(s))


def test_terminal_variance_mean_matches_exact_cir_moment() -> None:
    """SDE-03: compare against the reference fixture -- here the exact
    first moment of the continuous-time CIR variance process. Tolerance was
    set from an empirical run (~0.2% relative error at these settings with
    a comfortable Feller ratio); 3% leaves ample margin before flaking."""
    rng = np.random.default_rng(7)
    params = _comfortable_feller_params()
    _, v = simulate_heston_paths(100.0, params, maturity=1.0, n_steps=100, n_paths=50_000, rng=rng)
    exact_mean, _ = params.exact_variance_moments(1.0)
    sample_mean = v[:, -1].mean()
    assert abs(sample_mean - exact_mean) / exact_mean < 0.03


def test_low_feller_ratio_hits_the_zero_floor_far_more_often() -> None:
    """SDE-04/VAL-06 diagnostic: a Feller ratio well below 1 means the
    discretized variance process should spend noticeably more time at the
    zero floor than a comfortably-satisfied one, with everything else
    (including the RNG seed) held fixed."""
    low_feller = HestonParams(mu=0.03, kappa=1.0, theta=0.01, xi=0.5, rho=-0.5, v0=0.01)
    high_feller = HestonParams(mu=0.03, kappa=2.0, theta=0.04, xi=0.2, rho=-0.5, v0=0.04)
    assert low_feller.feller_ratio() < 1.0 < high_feller.feller_ratio()

    rng = np.random.default_rng(11)
    _, v_low = simulate_heston_paths(100.0, low_feller, 1.0, n_steps=100, n_paths=20_000, rng=rng)
    rng = np.random.default_rng(11)
    _, v_high = simulate_heston_paths(100.0, high_feller, 1.0, n_steps=100, n_paths=20_000, rng=rng)

    frac_at_zero_low = (v_low[:, 1:] == 0.0).mean()
    frac_at_zero_high = (v_high[:, 1:] == 0.0).mean()
    assert frac_at_zero_low > 10 * max(frac_at_zero_high, 1e-6)


def test_rejects_invalid_simulation_arguments() -> None:
    rng = np.random.default_rng(0)
    params = _comfortable_feller_params()
    with pytest.raises(ValueError):
        simulate_heston_paths(-1.0, params, 1.0, 10, 10, rng)
    with pytest.raises(ValueError):
        simulate_heston_paths(100.0, params, 0.0, 10, 10, rng)
    with pytest.raises(ValueError):
        simulate_heston_paths(100.0, params, 1.0, 0, 10, rng)
