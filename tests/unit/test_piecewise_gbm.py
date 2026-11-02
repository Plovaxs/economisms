import numpy as np
import pytest

from prometheus.stochastica.gbm import (
    piecewise_gbm_terminal_moments,
    simulate_piecewise_drift_gbm_paths,
    terminal_moments,
)


def test_rejects_empty_mu_path() -> None:
    rng = np.random.default_rng(0)
    with pytest.raises(ValueError):
        simulate_piecewise_drift_gbm_paths(100.0, [], 0.2, 1 / 12, 10, rng)


def test_shape_and_initial_value() -> None:
    rng = np.random.default_rng(0)
    paths = simulate_piecewise_drift_gbm_paths(100.0, [0.02, 0.05, -0.01], 0.2, 1 / 12, 50, rng)
    assert paths.shape == (50, 4)
    assert np.all(paths[:, 0] == 100.0)


def test_constant_drift_reduces_to_ordinary_gbm_moments() -> None:
    mean_constant, var_constant = terminal_moments(100.0, 0.03, 0.2, 1.0)
    mean_piecewise, var_piecewise = piecewise_gbm_terminal_moments(
        100.0, [0.03] * 12, 0.2, 1 / 12
    )
    assert mean_piecewise == pytest.approx(mean_constant)
    assert var_piecewise == pytest.approx(var_constant)


def test_terminal_distribution_matches_piecewise_theory_within_ci() -> None:
    s0, sigma, dt = 100.0, 0.2, 1 / 12
    mu_path = [0.02] * 6 + [0.05] * 6  # a regime change halfway through
    n_paths = 200_000
    rng = np.random.default_rng(1)
    paths = simulate_piecewise_drift_gbm_paths(s0, mu_path, sigma, dt, n_paths, rng)
    terminal = paths[:, -1]

    theory_mean, theory_var = piecewise_gbm_terminal_moments(s0, mu_path, sigma, dt)
    standard_error = np.sqrt(theory_var / n_paths)
    assert abs(terminal.mean() - theory_mean) < 6 * standard_error


def test_later_drift_cannot_affect_earlier_simulated_prices() -> None:
    """No-lookahead guarantee: changing only the second half of mu_path
    must leave the first half of every path bit-identical, given the same
    RNG seed."""
    s0, sigma, dt = 100.0, 0.2, 1 / 12
    mu_path_a = [0.02] * 6 + [0.05] * 6
    mu_path_b = [0.02] * 6 + [0.99] * 6  # wildly different tail

    rng_a = np.random.default_rng(5)
    rng_b = np.random.default_rng(5)
    paths_a = simulate_piecewise_drift_gbm_paths(s0, mu_path_a, sigma, dt, 500, rng_a)
    paths_b = simulate_piecewise_drift_gbm_paths(s0, mu_path_b, sigma, dt, 500, rng_b)

    assert np.array_equal(paths_a[:, :7], paths_b[:, :7])
    assert not np.allclose(paths_a[:, -1], paths_b[:, -1])  # tails do diverge
