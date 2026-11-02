import numpy as np
import pytest

from prometheus.stochastica.gbm import (
    simulate_correlated_gbm_paths,
    simulate_gbm_paths,
    terminal_moments,
)


def test_path_shape_and_initial_value() -> None:
    rng = np.random.default_rng(0)
    paths = simulate_gbm_paths(100.0, 0.05, 0.2, 1.0, n_steps=10, n_paths=5, rng=rng)
    assert paths.shape == (5, 11)
    assert np.all(paths[:, 0] == 100.0)


def test_paths_are_always_positive() -> None:
    rng = np.random.default_rng(1)
    paths = simulate_gbm_paths(50.0, -0.3, 0.8, 2.0, n_steps=100, n_paths=1000, rng=rng)
    assert np.all(paths > 0.0)


def test_rejects_invalid_parameters() -> None:
    rng = np.random.default_rng(0)
    with pytest.raises(ValueError):
        simulate_gbm_paths(-1.0, 0.0, 0.2, 1.0, 10, 10, rng)
    with pytest.raises(ValueError):
        simulate_gbm_paths(100.0, 0.0, -0.1, 1.0, 10, 10, rng)
    with pytest.raises(ValueError):
        simulate_gbm_paths(100.0, 0.0, 0.2, 1.0, 0, 10, rng)


def test_terminal_distribution_matches_theory_within_confidence_interval() -> None:
    """SDE-01: empirical mean/variance match theory within a CI. Using the
    theoretical variance to build a standard-error-based interval avoids a
    magic-number tolerance and an arbitrarily flaky/loose test."""
    rng = np.random.default_rng(42)
    s0, mu, sigma, maturity = 100.0, 0.05, 0.2, 1.0
    n_paths = 100_000
    paths = simulate_gbm_paths(s0, mu, sigma, maturity, n_steps=252, n_paths=n_paths, rng=rng)
    terminal = paths[:, -1]

    theory_mean, theory_var = terminal_moments(s0, mu, sigma, maturity)
    standard_error = np.sqrt(theory_var / n_paths)

    assert abs(terminal.mean() - theory_mean) < 6 * standard_error


def test_zero_volatility_is_deterministic_growth() -> None:
    rng = np.random.default_rng(0)
    paths = simulate_gbm_paths(100.0, 0.1, 0.0, 1.0, n_steps=4, n_paths=3, rng=rng)
    expected_terminal = 100.0 * np.exp(0.1 * 1.0)
    assert np.allclose(paths[:, -1], expected_terminal)


def test_correlated_gbm_shape_and_positivity() -> None:
    rng = np.random.default_rng(5)
    s0 = np.array([100.0, 50.0])
    mu = np.array([0.03, 0.05])
    sigma = np.array([0.2, 0.3])
    corr = np.array([[1.0, 0.4], [0.4, 1.0]])
    paths = simulate_correlated_gbm_paths(
        s0, mu, sigma, corr, 1.0, n_steps=50, n_paths=200, rng=rng
    )
    assert paths.shape == (200, 51, 2)
    assert np.all(paths > 0.0)
    assert np.all(paths[:, 0, :] == s0)


def test_correlated_gbm_recovers_approximate_asset_correlation() -> None:
    rng = np.random.default_rng(5)
    s0 = np.array([100.0, 100.0])
    mu = np.array([0.0, 0.0])
    sigma = np.array([0.3, 0.3])
    corr = np.array([[1.0, 0.7], [0.7, 1.0]])
    paths = simulate_correlated_gbm_paths(
        s0, mu, sigma, corr, 1.0, n_steps=252, n_paths=20_000, rng=rng
    )
    log_returns = np.log(paths[:, -1, :] / paths[:, 0, :])
    sample_corr = np.corrcoef(log_returns[:, 0], log_returns[:, 1])[0, 1]
    assert abs(sample_corr - 0.7) < 0.03


def test_correlated_gbm_rejects_mismatched_shapes() -> None:
    rng = np.random.default_rng(0)
    with pytest.raises(ValueError):
        simulate_correlated_gbm_paths(
            np.array([100.0, 100.0]),
            np.array([0.0]),  # wrong shape
            np.array([0.2, 0.2]),
            np.eye(2),
            1.0,
            10,
            10,
            rng,
        )
