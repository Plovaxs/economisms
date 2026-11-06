import numpy as np
import pytest

from prometheus.titan.out_of_sample import compare_in_sample_and_out_of_sample
from prometheus.titan.portfolio import PortfolioConstraints, minimum_variance_portfolio


def test_rejects_non_2d_returns() -> None:
    with pytest.raises(ValueError, match="2D"):
        compare_in_sample_and_out_of_sample(np.zeros(10), train_periods=5)


def test_rejects_too_few_train_periods() -> None:
    returns = np.zeros((20, 3))
    with pytest.raises(ValueError, match="train_periods"):
        compare_in_sample_and_out_of_sample(returns, train_periods=1)


def test_rejects_train_periods_leaving_no_test_data() -> None:
    returns = np.zeros((20, 3))
    with pytest.raises(ValueError, match="test period"):
        compare_in_sample_and_out_of_sample(returns, train_periods=20)
    with pytest.raises(ValueError, match="test period"):
        compare_in_sample_and_out_of_sample(returns, train_periods=25)


def test_rejects_fewer_than_two_assets() -> None:
    returns = np.zeros((20, 1))
    with pytest.raises(ValueError, match="2 assets"):
        compare_in_sample_and_out_of_sample(returns, train_periods=10)


def test_raises_a_clear_error_when_the_train_fit_is_infeasible() -> None:
    """OPT-09's "no infeasible solution silently labeled optimal" extends
    here too: an infeasible constraint combination must raise, not
    silently return garbage weights."""
    rng = np.random.default_rng(0)
    returns = rng.multivariate_normal(np.zeros(3), np.eye(3) * 0.01, size=30)
    infeasible_constraints = PortfolioConstraints(min_weight=0.0, max_weight=0.2, budget=1.0)
    with pytest.raises(ValueError, match="failed"):
        compare_in_sample_and_out_of_sample(
            returns, train_periods=20, constraints=infeasible_constraints
        )


def test_weights_are_frozen_and_applied_unchanged_to_both_blocks() -> None:
    rng = np.random.default_rng(1)
    n_assets = 4
    returns = rng.multivariate_normal(np.zeros(n_assets), np.eye(n_assets) * 0.01, size=100)
    result = compare_in_sample_and_out_of_sample(returns, train_periods=40)

    assert result.train_weights.shape == (n_assets,)
    assert result.train_weights.sum() == pytest.approx(1.0, abs=1e-6)
    assert result.train_periods == 40
    assert result.test_periods == 60

    expected_train_returns = returns[:40] @ result.train_weights
    expected_test_returns = returns[40:] @ result.train_weights
    assert result.train_variance == pytest.approx(expected_train_returns.var())
    assert result.test_variance == pytest.approx(expected_test_returns.var())
    assert result.train_mean_return == pytest.approx(expected_train_returns.mean())
    assert result.test_mean_return == pytest.approx(expected_test_returns.mean())
    assert result.train_volatility == pytest.approx(np.sqrt(result.train_variance))
    assert result.test_volatility == pytest.approx(np.sqrt(result.test_variance))


def test_shrinkage_can_be_used_instead_of_the_plain_sample_covariance() -> None:
    rng = np.random.default_rng(2)
    n_assets = 6
    # n_periods < n_assets: the plain sample covariance would be singular,
    # exactly the regime shrinkage exists to fix (RISK-05).
    returns = rng.multivariate_normal(np.zeros(n_assets), np.eye(n_assets) * 0.01, size=4)
    test_returns = rng.multivariate_normal(np.zeros(n_assets), np.eye(n_assets) * 0.01, size=20)
    combined = np.vstack([returns, test_returns])
    result = compare_in_sample_and_out_of_sample(combined, train_periods=4, use_shrinkage=True)
    assert result.shrinkage_used is True
    assert np.isfinite(result.train_variance)
    assert np.isfinite(result.test_variance)


def test_in_sample_variance_is_systematically_optimistic_versus_out_of_sample() -> None:
    """The genuine, empirically-confirmed finding this module's own
    docstring states (OPT-08's literal "comparison"): across many
    independent trials drawn from the SAME known covariance, mean
    in-sample variance < the TRUE optimal portfolio's variance < mean
    out-of-sample variance. A single trial is noisy (either side could
    win by chance), so this is checked on averages over many trials,
    matching how the finding was itself confirmed empirically before
    being written into production code."""
    n_assets = 8
    true_covariance = np.eye(n_assets) * 0.01 + 0.002
    constraints = PortfolioConstraints(min_weight=-1.0, max_weight=1.0)
    true_optimal_variance = minimum_variance_portfolio(true_covariance, constraints).objective_value

    rng = np.random.default_rng(3)
    n_trials = 200
    train_n, test_n = 60, 250
    in_sample_variances = []
    out_sample_variances = []
    for _ in range(n_trials):
        data = rng.multivariate_normal(np.zeros(n_assets), true_covariance, size=train_n + test_n)
        result = compare_in_sample_and_out_of_sample(
            data, train_periods=train_n, constraints=constraints
        )
        in_sample_variances.append(result.train_variance)
        out_sample_variances.append(result.test_variance)

    mean_in_sample = float(np.mean(in_sample_variances))
    mean_out_sample = float(np.mean(out_sample_variances))
    assert mean_in_sample < true_optimal_variance < mean_out_sample
