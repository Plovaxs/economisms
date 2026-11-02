import numpy as np
import pytest
from scipy import stats

from prometheus.titan.risk_metrics import (
    historical_expected_shortfall,
    historical_var,
    max_drawdown,
    parametric_var,
    pnl_to_losses,
    var_exception_coverage_test,
)


def test_pnl_to_losses_negates() -> None:
    pnl = np.array([10.0, -5.0, 0.0])
    assert list(pnl_to_losses(pnl)) == [-10.0, 5.0, 0.0]


def test_historical_var_rejects_empty_or_bad_alpha() -> None:
    with pytest.raises(ValueError):
        historical_var(np.array([]), 0.95)
    with pytest.raises(ValueError):
        historical_var(np.array([1.0, 2.0]), 1.5)


def test_historical_var_matches_numpy_quantile_directly() -> None:
    losses = np.array([1.0, 5.0, 3.0, 2.0, 4.0])
    assert historical_var(losses, 0.8) == pytest.approx(np.quantile(losses, 0.8))


def test_parametric_var_known_value() -> None:
    # 99% VaR of a standard normal loss distribution is its 99th percentile.
    value = parametric_var(mean=0.0, std=1.0, alpha=0.99)
    assert value == pytest.approx(2.3263478740408408, abs=1e-9)


def test_parametric_var_rejects_negative_std() -> None:
    with pytest.raises(ValueError):
        parametric_var(mean=0.0, std=-1.0, alpha=0.95)


def test_expected_shortfall_discrete_worked_example_no_ties() -> None:
    """losses = 1..10, alpha = 0.8: top 20% (2 of 10) = {9, 10}, mean 9.5.
    n*(1-alpha) = 2 is an integer, so the boundary weight is exactly zero
    and this reduces to a plain tail average -- the simplest case."""
    losses = np.arange(1, 11, dtype=float)
    es = historical_expected_shortfall(losses, 0.8)
    assert es == pytest.approx(9.5)


def test_expected_shortfall_discrete_worked_example_with_ties() -> None:
    """losses with a run of tied 3s: [1,1,1,2,2,3,3,3,3,10]. alpha=0.8 means
    the top 2 order statistics are the last two entries {3, 10} (not all
    four 3s), mean 6.5 -- this is the case that would go wrong if ties were
    handled by grouping on distinct values instead of order statistics."""
    losses = np.array([1, 1, 1, 2, 2, 3, 3, 3, 3, 10], dtype=float)
    es = historical_expected_shortfall(losses, 0.8)
    assert es == pytest.approx(6.5)


def test_expected_shortfall_partial_boundary_weight_single_worst_loss() -> None:
    """n=10, alpha=0.95: n*(1-alpha)=0.5 is not an integer; the top "half an
    observation" collapses to exactly the single worst loss."""
    losses = np.arange(1, 11, dtype=float)
    es = historical_expected_shortfall(losses, 0.95)
    assert es == pytest.approx(10.0)


def test_expected_shortfall_matches_exact_gaussian_reference() -> None:
    """Continuous-tail reference check: for losses ~ N(mu, sigma^2), the
    exact ES_alpha = mu + sigma * phi(Phi^-1(alpha)) / (1 - alpha)."""
    rng = np.random.default_rng(1)
    n = 500_000
    alpha = 0.975
    losses = rng.standard_normal(n)
    z = stats.norm.ppf(alpha)
    exact_es = stats.norm.pdf(z) / (1 - alpha)

    empirical_es = historical_expected_shortfall(losses, alpha)
    assert abs(empirical_es - exact_es) / exact_es < 0.01


def test_expected_shortfall_rejects_empty_or_bad_alpha() -> None:
    with pytest.raises(ValueError):
        historical_expected_shortfall(np.array([]), 0.95)
    with pytest.raises(ValueError):
        historical_expected_shortfall(np.array([1.0]), 0.0)


def test_es_is_never_less_extreme_than_var_for_a_loss_distribution() -> None:
    """By definition ES_alpha >= VaR_alpha for a loss random variable."""
    rng = np.random.default_rng(2)
    losses = rng.standard_t(df=5, size=10_000)  # fat-tailed
    for alpha in (0.90, 0.95, 0.99):
        var = historical_var(losses, alpha)
        es = historical_expected_shortfall(losses, alpha)
        assert es >= var


def test_max_drawdown_hand_example() -> None:
    cumulative = np.array([100.0, 110.0, 90.0, 95.0, 120.0, 80.0])
    assert max_drawdown(cumulative) == pytest.approx(-40.0)


def test_max_drawdown_is_zero_for_monotonically_increasing_series() -> None:
    cumulative = np.array([1.0, 2.0, 3.0, 4.0])
    assert max_drawdown(cumulative) == 0.0


def test_max_drawdown_rejects_empty_array() -> None:
    with pytest.raises(ValueError):
        max_drawdown(np.array([]))


def test_var_coverage_test_accepts_well_calibrated_model() -> None:
    """Losses drawn exactly from the distribution the VaR threshold was
    computed from should not be flagged (high p-value)."""
    rng = np.random.default_rng(3)
    alpha = 0.95
    losses = rng.standard_normal(5_000)
    threshold = parametric_var(mean=0.0, std=1.0, alpha=alpha)
    result = var_exception_coverage_test(losses, threshold, alpha)
    assert result.p_value > 0.05
    assert result.expected_exception_rate == pytest.approx(0.05)


def test_var_coverage_test_flags_badly_miscalibrated_model() -> None:
    """A VaR threshold set far too low (e.g. zero, for a distribution
    centered at zero) should produce far more exceptions than expected and
    a tiny p-value."""
    rng = np.random.default_rng(4)
    alpha = 0.95
    losses = rng.standard_normal(5_000)
    too_low_threshold = 0.0  # ~50% of losses will exceed this, not 5%
    result = var_exception_coverage_test(losses, too_low_threshold, alpha)
    assert result.p_value < 1e-10
    assert result.observed_exception_rate > 0.3


def test_var_coverage_test_rejects_bad_inputs() -> None:
    with pytest.raises(ValueError):
        var_exception_coverage_test(np.array([]), 0.0, 0.95)
    with pytest.raises(ValueError):
        var_exception_coverage_test(np.array([1.0]), 0.0, 1.5)
