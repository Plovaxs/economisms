import numpy as np
import pytest

from prometheus.stochastica.gbm import terminal_moments
from prometheus.stochastica.regime_switching import (
    RegimeSwitchingParams,
    is_stationary_distribution,
    simulate_regime_switching_paths,
    stationary_distribution,
)


def _two_state_params(p01: float = 0.1, p10: float = 0.3) -> RegimeSwitchingParams:
    transition = np.array([[1 - p01, p01], [p10, 1 - p10]])
    return RegimeSwitchingParams(
        transition_matrix=transition,
        regime_mu=np.array([0.08, -0.05]),
        regime_sigma=np.array([0.15, 0.5]),
    )


def test_rejects_non_row_stochastic_transition_matrix() -> None:
    with pytest.raises(ValueError, match="sum to exactly 1.0"):
        RegimeSwitchingParams(
            transition_matrix=np.array([[0.9, 0.2], [0.3, 0.7]]),
            regime_mu=np.array([0.05, -0.05]),
            regime_sigma=np.array([0.2, 0.3]),
        )


def test_rejects_transition_entries_outside_unit_interval() -> None:
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        RegimeSwitchingParams(
            transition_matrix=np.array([[1.1, -0.1], [0.3, 0.7]]),
            regime_mu=np.array([0.05, -0.05]),
            regime_sigma=np.array([0.2, 0.3]),
        )


def test_rejects_mismatched_regime_parameter_shapes() -> None:
    with pytest.raises(ValueError, match="shape"):
        RegimeSwitchingParams(
            transition_matrix=np.array([[0.9, 0.1], [0.3, 0.7]]),
            regime_mu=np.array([0.05]),
            regime_sigma=np.array([0.2, 0.3]),
        )


def test_rejects_negative_sigma() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        RegimeSwitchingParams(
            transition_matrix=np.array([[0.9, 0.1], [0.3, 0.7]]),
            regime_mu=np.array([0.05, -0.05]),
            regime_sigma=np.array([0.2, -0.3]),
        )


def test_rejects_non_square_transition_matrix() -> None:
    with pytest.raises(ValueError, match="square"):
        RegimeSwitchingParams(
            transition_matrix=np.array([[0.9, 0.1, 0.0], [0.3, 0.7, 0.0]]),
            regime_mu=np.array([0.05, -0.05]),
            regime_sigma=np.array([0.2, 0.3]),
        )


def test_rejects_nan_and_inf_fields() -> None:
    """VAL-13 discipline (see barrier_options.py, merton_pricer.py and
    friends this session): an ordinary comparison check silently admits
    NaN, so finiteness is checked explicitly rather than left to the
    sign/range checks alone."""
    with pytest.raises(ValueError, match="finite"):
        RegimeSwitchingParams(
            transition_matrix=np.array([[0.9, 0.1], [0.3, 0.7]]),
            regime_mu=np.array([float("nan"), -0.05]),
            regime_sigma=np.array([0.2, 0.3]),
        )
    with pytest.raises(ValueError, match="finite"):
        RegimeSwitchingParams(
            transition_matrix=np.array([[0.9, 0.1], [0.3, float("inf")]]),
            regime_mu=np.array([0.05, -0.05]),
            regime_sigma=np.array([0.2, 0.3]),
        )
    with pytest.raises(ValueError, match="finite"):
        RegimeSwitchingParams(
            transition_matrix=np.array([[0.9, 0.1], [0.3, 0.7]]),
            regime_mu=np.array([0.05, -0.05]),
            regime_sigma=np.array([0.2, float("nan")]),
        )


def test_stationary_distribution_matches_the_closed_form_two_state_formula() -> None:
    """pi0 = p10/(p01+p10), derived directly from the stationarity
    equation pi0*p00 + pi1*p10 = pi0 (not assumed from outside memory)."""
    p01, p10 = 0.1, 0.3
    transition = np.array([[1 - p01, p01], [p10, 1 - p10]])
    pi = stationary_distribution(transition)
    expected = np.array([p10 / (p01 + p10), p01 / (p01 + p10)])
    assert pi == pytest.approx(expected, abs=1e-9)


def test_stationary_distribution_satisfies_the_fixed_point_equation_for_three_states() -> None:
    transition = np.array([[0.8, 0.15, 0.05], [0.1, 0.7, 0.2], [0.3, 0.1, 0.6]])
    pi = stationary_distribution(transition)
    assert pi.sum() == pytest.approx(1.0, abs=1e-9)
    assert np.all(pi >= -1e-9)
    assert pi @ transition == pytest.approx(pi, abs=1e-9)


def test_is_stationary_distribution_accepts_the_true_stationary_distribution() -> None:
    transition = np.array([[0.9, 0.1], [0.3, 0.7]])
    pi = stationary_distribution(transition)
    assert is_stationary_distribution(transition, pi)


def test_is_stationary_distribution_rejects_a_non_stationary_candidate() -> None:
    """The literal "stationary TEST" SDE-06 asks for must actually
    discriminate, not just return True on the happy path."""
    transition = np.array([[0.9, 0.1], [0.3, 0.7]])
    assert not is_stationary_distribution(transition, np.array([0.5, 0.5]))
    assert not is_stationary_distribution(transition, np.array([0.6, 0.5]))  # doesn't sum to 1
    assert not is_stationary_distribution(transition, np.array([1.5, -0.5]))  # negative entry


def test_is_stationary_distribution_rejects_a_mismatched_shape() -> None:
    transition = np.array([[0.9, 0.1], [0.3, 0.7]])
    with pytest.raises(ValueError, match="shape"):
        is_stationary_distribution(transition, np.array([0.5, 0.3, 0.2]))


def test_stationary_distribution_matches_a_long_run_empirical_simulation() -> None:
    """Independent cross-check (this project's established discipline):
    a 2,000,000-step single-path simulation of the SAME chain should
    spend a fraction of its time in each regime matching the computed
    stationary distribution, within sampling noise."""
    transition = np.array([[0.9, 0.1], [0.3, 0.7]])
    pi = stationary_distribution(transition)

    rng = np.random.default_rng(0)
    n_steps = 2_000_000
    state = 0
    counts = np.zeros(2)
    for _ in range(n_steps):
        counts[state] += 1
        state = rng.choice(2, p=transition[state])
    empirical = counts / n_steps
    assert empirical == pytest.approx(pi, abs=5e-3)


def test_simulate_paths_shape_and_initial_value() -> None:
    rng = np.random.default_rng(0)
    params = _two_state_params()
    paths, regimes = simulate_regime_switching_paths(100.0, params, 1.0, 10, 50, rng)
    assert paths.shape == (50, 11)
    assert regimes.shape == (50, 11)
    assert np.all(paths[:, 0] == 100.0)
    assert np.all((regimes == 0) | (regimes == 1))


def test_paths_are_always_finite_and_positive() -> None:
    rng = np.random.default_rng(1)
    params = _two_state_params()
    paths, _ = simulate_regime_switching_paths(100.0, params, 2.0, 100, 1000, rng)
    assert np.all(np.isfinite(paths))
    assert np.all(paths > 0.0)


def test_regime_occupancy_converges_to_the_stationary_distribution() -> None:
    """Long-horizon simulated paths should spend a fraction of their
    steps in each regime matching `stationary_distribution`, confirming
    the simulator's own Markov dynamics are consistent with the
    analytical stationary calculation above (an independent check: this
    test does not call `stationary_distribution` to GENERATE its
    expectation from the same code path being tested elsewhere, only to
    state what the simulator's output should converge to)."""
    transition = np.array([[0.9, 0.1], [0.3, 0.7]])
    params = RegimeSwitchingParams(
        transition_matrix=transition,
        regime_mu=np.array([0.05, 0.05]),
        regime_sigma=np.array([0.2, 0.2]),
    )
    rng = np.random.default_rng(2)
    _, regimes = simulate_regime_switching_paths(
        100.0, params, 50.0, 5000, 20, rng, initial_regime_distribution=np.array([0.5, 0.5])
    )
    pi = stationary_distribution(transition)
    empirical = np.array([(regimes == 0).mean(), (regimes == 1).mean()])
    assert empirical == pytest.approx(pi, abs=0.02)


def test_single_regime_reduces_to_plain_gbm_moments() -> None:
    """Degenerate case (n_regimes=1, self-transition probability 1):
    must match plain GBM's own exact closed-form terminal moments,
    confirmed via a large-sample Monte Carlo comparison (the same style
    `test_gbm.py` uses for GBM itself) rather than a bit-exact path
    comparison, since the regime machinery still consumes RNG state
    even when there is only one regime to choose from."""
    s0, mu, sigma, maturity = 100.0, 0.05, 0.2, 1.0
    params = RegimeSwitchingParams(
        transition_matrix=np.array([[1.0]]),
        regime_mu=np.array([mu]),
        regime_sigma=np.array([sigma]),
    )
    rng = np.random.default_rng(7)
    n_paths = 200_000
    paths, regimes = simulate_regime_switching_paths(s0, params, maturity, 50, n_paths, rng)
    assert np.all(regimes == 0)

    terminal = paths[:, -1]
    theory_mean, theory_var = terminal_moments(s0, mu, sigma, maturity)
    standard_error = np.sqrt(theory_var / n_paths)
    assert abs(terminal.mean() - theory_mean) < 6 * standard_error


def test_extreme_positive_drift_raises_a_clear_error_not_a_silent_inf() -> None:
    """Same SDE-12 finding as `stochastica.gbm` (this module shares its
    log-Euler-then-exponentiate pattern): a large enough positive drift
    over a long enough maturity overflows np.exp for the upper tail of
    paths; raises a clear ValueError rather than returning a silent inf."""
    params = RegimeSwitchingParams(
        transition_matrix=np.array([[1.0]]),
        regime_mu=np.array([5.0]),
        regime_sigma=np.array([0.5]),
    )
    rng = np.random.default_rng(0)
    with pytest.raises(ValueError, match="non-finite"):
        simulate_regime_switching_paths(1.0, params, 142.0, n_steps=10, n_paths=5000, rng=rng)


def test_rejects_invalid_initial_regime_distribution() -> None:
    rng = np.random.default_rng(0)
    params = _two_state_params()
    with pytest.raises(ValueError, match="sum to 1"):
        simulate_regime_switching_paths(
            100.0, params, 1.0, 10, 10, rng, initial_regime_distribution=np.array([0.5, 0.6])
        )


def test_rejects_non_positive_scalars() -> None:
    rng = np.random.default_rng(0)
    params = _two_state_params()
    with pytest.raises(ValueError):
        simulate_regime_switching_paths(-1.0, params, 1.0, 10, 10, rng)
    with pytest.raises(ValueError):
        simulate_regime_switching_paths(100.0, params, 0.0, 10, 10, rng)
    with pytest.raises(ValueError):
        simulate_regime_switching_paths(100.0, params, 1.0, 0, 10, rng)
    with pytest.raises(ValueError):
        simulate_regime_switching_paths(100.0, params, 1.0, 10, 0, rng)
