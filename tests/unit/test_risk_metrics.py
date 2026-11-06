import numpy as np
import pytest
from scipy import stats

from prometheus.titan.risk_metrics import (
    es_unconditional_calibration_test,
    expected_shortfall_exceedance_residual_test,
    historical_expected_shortfall,
    historical_var,
    max_drawdown,
    parametric_var,
    pnl_to_losses,
    quantile_score,
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


def test_quantile_score_is_minimized_at_the_true_quantile() -> None:
    """RISK-09's strict-consistency claim, discriminating: the mean
    pinball score over a grid of candidate VaR thresholds must be
    minimized closest to the TRUE 95th percentile of a standard normal,
    not at some other, deliberately-wrong candidate."""
    rng = np.random.default_rng(1)
    alpha = 0.95
    losses = rng.standard_normal(100_000)
    true_var = parametric_var(mean=0.0, std=1.0, alpha=alpha)
    candidates = np.linspace(true_var - 1.0, true_var + 1.0, 21)
    mean_scores = [float(quantile_score(losses, c, alpha).mean()) for c in candidates]
    best = candidates[int(np.argmin(mean_scores))]
    assert abs(best - true_var) < 0.1


def test_quantile_score_rejects_empty_or_bad_alpha() -> None:
    with pytest.raises(ValueError):
        quantile_score(np.array([]), 0.0, 0.95)
    with pytest.raises(ValueError):
        quantile_score(np.array([1.0]), 0.0, 1.5)


def test_quantile_score_broadcasts_a_scalar_and_an_array_forecast_identically() -> None:
    losses = np.array([1.0, 2.0, 3.0])
    scalar_scores = quantile_score(losses, 2.0, 0.9)
    array_scores = quantile_score(losses, np.array([2.0, 2.0, 2.0]), 0.9)
    assert list(scalar_scores) == list(array_scores)


def test_exceedance_residual_test_accepts_well_calibrated_es() -> None:
    """Known Gaussian reference: a correctly-specified VaR/ES pair at
    their exact analytic values should not be flagged."""
    rng = np.random.default_rng(2)
    alpha = 0.95
    losses = rng.standard_normal(20_000)
    true_var = parametric_var(mean=0.0, std=1.0, alpha=alpha)
    true_es = historical_expected_shortfall(rng.standard_normal(2_000_000), alpha)
    result = expected_shortfall_exceedance_residual_test(losses, true_var, true_es)
    assert result.p_value > 0.01
    assert result.n_exceedances > 0


def test_exceedance_residual_test_flags_an_es_forecast_that_understates_risk() -> None:
    """An ES forecast set to half its true value (risk understated)
    must be reliably flagged -- this is the discriminating case."""
    rng = np.random.default_rng(3)
    alpha = 0.95
    losses = rng.standard_normal(20_000)
    true_var = parametric_var(mean=0.0, std=1.0, alpha=alpha)
    true_es = historical_expected_shortfall(rng.standard_normal(2_000_000), alpha)
    result = expected_shortfall_exceedance_residual_test(losses, true_var, true_es * 0.5)
    assert result.p_value < 1e-10
    assert result.mean_residual > 0


def test_exceedance_residual_test_rejects_fewer_than_two_exceedances() -> None:
    losses = np.array([0.0, 0.0, 0.0, 100.0])
    with pytest.raises(ValueError, match="exceedances"):
        expected_shortfall_exceedance_residual_test(losses, var_forecast=50.0, es_forecast=75.0)


def test_exceedance_residual_test_supports_a_time_varying_forecast_series() -> None:
    """Per-observation forecast arrays (the realistic rolling-forecast
    backtesting case), not just a constant threshold."""
    losses = np.array([5.0, 1.0, 6.0, 2.0, 7.0, 1.0])
    var_forecast = np.array([4.0, 4.0, 4.0, 4.0, 4.0, 4.0])
    es_forecast = np.array([6.0, 6.0, 6.0, 6.0, 6.0, 6.0])
    result = expected_shortfall_exceedance_residual_test(losses, var_forecast, es_forecast)
    assert result.n_exceedances == 3  # losses 5.0, 6.0, 7.0 exceed 4.0
    assert result.mean_residual == pytest.approx((5.0 + 6.0 + 7.0) / 3 - 6.0)


def test_es_calibration_statistic_accepts_well_calibrated_es() -> None:
    rng = np.random.default_rng(4)
    alpha = 0.95
    losses = rng.standard_normal(200_000)
    true_var = parametric_var(mean=0.0, std=1.0, alpha=alpha)
    true_es = historical_expected_shortfall(rng.standard_normal(2_000_000), alpha)
    result = es_unconditional_calibration_test(
        losses, true_var, true_es, alpha, rng=np.random.default_rng(5)
    )
    assert abs(result.statistic) < 0.1
    assert result.p_value > 0.05


def test_es_calibration_statistic_flags_an_es_forecast_that_understates_risk() -> None:
    rng = np.random.default_rng(6)
    alpha = 0.95
    losses = rng.standard_normal(200_000)
    true_var = parametric_var(mean=0.0, std=1.0, alpha=alpha)
    true_es = historical_expected_shortfall(rng.standard_normal(2_000_000), alpha)
    result = es_unconditional_calibration_test(
        losses, true_var, true_es * 0.5, alpha, rng=np.random.default_rng(7)
    )
    assert result.statistic > 0.5
    assert result.p_value < 1e-10


def test_es_calibration_statistic_handles_zero_exceedances_without_crashing() -> None:
    """A sample with no VaR exceedances at all must still produce a
    well-defined, finite statistic (-1.0, exactly) rather than a
    division-by-zero crash -- the case the exceedance-residual t-test
    above cannot handle."""
    losses = np.array([-5.0, -4.0, -3.0, -2.0, -1.0])
    result = es_unconditional_calibration_test(
        losses, var_forecast=10.0, es_forecast=1.0, alpha=0.95, rng=np.random.default_rng(8)
    )
    assert result.n_exceedances == 0
    assert result.statistic == -1.0
    assert result.bootstrap_standard_error == 0.0
    assert result.p_value == 0.0


def test_es_calibration_statistic_rejects_zero_es_forecast() -> None:
    losses = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    with pytest.raises(ValueError, match="es_forecast"):
        es_unconditional_calibration_test(
            losses, var_forecast=0.0, es_forecast=0.0, alpha=0.95, rng=np.random.default_rng(9)
        )


def test_es_calibration_statistic_rejects_too_few_bootstrap_resamples() -> None:
    losses = np.array([1.0, 2.0, 3.0])
    with pytest.raises(ValueError, match="n_bootstrap"):
        es_unconditional_calibration_test(
            losses,
            var_forecast=0.0,
            es_forecast=1.0,
            alpha=0.95,
            rng=np.random.default_rng(10),
            n_bootstrap=1,
        )
