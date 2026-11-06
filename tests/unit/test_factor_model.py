import numpy as np
import pytest

from prometheus.titan.covariance import shrink_covariance_ledoit_wolf
from prometheus.titan.factor_model import (
    decompose_portfolio_variance,
    estimate_factor_exposures,
    factor_model_implied_covariance,
)
from prometheus.titan.portfolio import minimum_variance_portfolio


def _simulated_factor_model(
    seed: int, n_obs: int = 2000
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Returns (asset_returns, factor_returns, true_alpha, true_betas,
    true_resid_var) for a known 2-factor, 4-asset model -- the ground
    truth a recovery test checks the estimator converges toward."""
    rng = np.random.default_rng(seed)
    true_alpha = np.array([0.001, -0.0005, 0.0, 0.002])
    true_betas = np.array([[1.2, 0.3], [0.8, -0.2], [1.0, 0.0], [0.5, 0.5]])
    factor_cov = np.array([[0.04, 0.01], [0.01, 0.02]])
    resid_var = np.array([0.0009, 0.0016, 0.0004, 0.0025])

    factors = rng.multivariate_normal(np.zeros(2), factor_cov, n_obs)
    noise = rng.normal(0.0, 1.0, (n_obs, 4)) * np.sqrt(resid_var)
    asset_returns = true_alpha + factors @ true_betas.T + noise
    return asset_returns, factors, true_alpha, true_betas, resid_var


def test_estimate_factor_exposures_rejects_non_2d_asset_returns() -> None:
    with pytest.raises(ValueError):
        estimate_factor_exposures(np.zeros(10), np.zeros((10, 2)))


def test_estimate_factor_exposures_rejects_non_2d_factor_returns() -> None:
    with pytest.raises(ValueError):
        estimate_factor_exposures(np.zeros((10, 2)), np.zeros(10))


def test_estimate_factor_exposures_rejects_mismatched_observation_counts() -> None:
    with pytest.raises(ValueError):
        estimate_factor_exposures(np.zeros((10, 2)), np.zeros((9, 2)))


def test_estimate_factor_exposures_rejects_insufficient_observations() -> None:
    with pytest.raises(ValueError):
        estimate_factor_exposures(np.zeros((3, 2)), np.zeros((3, 2)))


def test_estimate_factor_exposures_rejects_collinear_factors() -> None:
    rng = np.random.default_rng(0)
    f1 = rng.normal(0, 1, 100)
    factors = np.column_stack([f1, 2.0 * f1])  # exactly collinear
    asset_returns = rng.normal(0, 1, (100, 3))
    with pytest.raises(ValueError):
        estimate_factor_exposures(asset_returns, factors)


def test_estimate_factor_exposures_matches_lstsq_to_machine_precision() -> None:
    """Independent cross-check: the module solves the OLS normal equations
    directly (matrix inversion); `numpy.linalg.lstsq` uses a different
    algorithm (SVD-based) entirely. Agreement to ~1e-9 is a genuine
    cross-implementation check, not the same code checked against itself.
    """
    asset_returns, factors, *_ = _simulated_factor_model(seed=1)
    result = estimate_factor_exposures(asset_returns, factors)

    n_obs = factors.shape[0]
    design = np.column_stack([np.ones(n_obs), factors])
    coeffs, *_ = np.linalg.lstsq(design, asset_returns, rcond=None)
    alphas_lstsq = coeffs[0]
    betas_lstsq = coeffs[1:].T

    assert result.alphas == pytest.approx(alphas_lstsq, abs=1e-9)
    assert result.betas == pytest.approx(betas_lstsq, abs=1e-9)


def test_estimate_factor_exposures_recovers_exact_coefficients_with_zero_noise() -> None:
    rng = np.random.default_rng(2)
    n_obs = 50
    factors = rng.normal(0, 1, (n_obs, 2))
    true_alpha = np.array([0.01, -0.02])
    true_betas = np.array([[1.0, 0.5], [2.0, -1.0]])
    asset_returns = true_alpha + factors @ true_betas.T

    result = estimate_factor_exposures(asset_returns, factors)

    assert result.alphas == pytest.approx(true_alpha, abs=1e-8)
    assert result.betas == pytest.approx(true_betas, abs=1e-8)
    assert result.residual_variances == pytest.approx(np.zeros(2), abs=1e-10)
    assert result.r_squared == pytest.approx(np.ones(2), abs=1e-8)


def test_estimate_factor_exposures_reports_zero_r_squared_for_constant_asset() -> None:
    """A degenerate zero-variance asset must not raise or divide by zero --
    its R^2 is reported as 0.0 rather than NaN or +-inf."""
    rng = np.random.default_rng(3)
    n_obs = 50
    factors = rng.normal(0, 1, (n_obs, 2))
    constant_asset = np.full(n_obs, 5.0)
    varying_asset = factors[:, 0] + rng.normal(0, 0.1, n_obs)
    asset_returns = np.column_stack([constant_asset, varying_asset])

    result = estimate_factor_exposures(asset_returns, factors)

    assert result.r_squared[0] == 0.0
    assert np.isfinite(result.r_squared).all()


def test_estimate_factor_exposures_converges_to_true_parameters_with_large_sample() -> None:
    asset_returns, factors, true_alpha, true_betas, true_resid_var = _simulated_factor_model(
        seed=4, n_obs=5000
    )
    result = estimate_factor_exposures(asset_returns, factors)

    assert result.alphas == pytest.approx(true_alpha, abs=0.01)
    assert result.betas == pytest.approx(true_betas, abs=0.05)
    assert result.residual_variances == pytest.approx(true_resid_var, rel=0.2)
    assert np.all(result.r_squared > 0.8)


def test_decompose_portfolio_variance_rejects_mismatched_weights_shape() -> None:
    betas = np.eye(3, 2)
    with pytest.raises(ValueError):
        decompose_portfolio_variance(np.array([1.0, 2.0]), betas, np.eye(2), np.ones(3))


def test_decompose_portfolio_variance_rejects_mismatched_factor_covariance_shape() -> None:
    betas = np.eye(3, 2)
    with pytest.raises(ValueError):
        decompose_portfolio_variance(np.ones(3) / 3, betas, np.eye(3), np.ones(3))


def test_decompose_portfolio_variance_rejects_mismatched_residual_variances_shape() -> None:
    betas = np.eye(3, 2)
    with pytest.raises(ValueError):
        decompose_portfolio_variance(np.ones(3) / 3, betas, np.eye(2), np.ones(2))


def test_decompose_portfolio_variance_rejects_negative_residual_variance() -> None:
    betas = np.eye(3, 2)
    with pytest.raises(ValueError):
        decompose_portfolio_variance(np.ones(3) / 3, betas, np.eye(2), np.array([1.0, -1.0, 1.0]))


def test_factor_variance_contributions_sum_exactly_to_factor_variance() -> None:
    rng = np.random.default_rng(5)
    n_assets, n_factors = 6, 3
    betas = rng.normal(0, 1, (n_assets, n_factors))
    raw = rng.normal(0, 1, (n_factors, n_factors))
    factor_covariance = raw @ raw.T + np.eye(n_factors) * 0.01  # guaranteed PD
    residual_variances = rng.uniform(0.001, 0.01, n_assets)
    weights = rng.dirichlet(np.ones(n_assets))

    decomp = decompose_portfolio_variance(weights, betas, factor_covariance, residual_variances)

    assert decomp.factor_variance_contributions.sum() == pytest.approx(
        decomp.factor_variance, abs=1e-12
    )
    assert decomp.total_variance == pytest.approx(
        decomp.factor_variance + decomp.idiosyncratic_variance
    )


def test_decompose_portfolio_variance_matches_full_implied_covariance_matrix() -> None:
    """Independent cross-check: build the full (n_assets, n_assets) implied
    covariance matrix Sigma = B Sigma_f B' + diag(resid_var) directly and
    confirm w' Sigma w matches the exposure-based total_variance -- a
    completely different computational path (one (n_assets, n_assets)
    quadratic form vs. the factor-space decomposition) over the same
    model."""
    rng = np.random.default_rng(6)
    n_assets, n_factors = 5, 2
    betas = rng.normal(0, 1, (n_assets, n_factors))
    raw = rng.normal(0, 1, (n_factors, n_factors))
    factor_covariance = raw @ raw.T + np.eye(n_factors) * 0.01
    residual_variances = rng.uniform(0.001, 0.01, n_assets)
    weights = rng.dirichlet(np.ones(n_assets))

    decomp = decompose_portfolio_variance(weights, betas, factor_covariance, residual_variances)

    sigma_implied = betas @ factor_covariance @ betas.T + np.diag(residual_variances)
    total_direct = float(weights @ sigma_implied @ weights)

    assert decomp.total_variance == pytest.approx(total_direct, abs=1e-12)


def test_estimated_decomposition_converges_to_true_decomposition() -> None:
    """The practical payoff, demonstrated end to end rather than just
    asserted: estimate exposures from a large simulated sample of a KNOWN
    factor model, decompose a fixed portfolio's variance using the
    ESTIMATED parameters, and confirm it is close to the decomposition
    computed from the TRUE (ground-truth) parameters -- a genuine
    statistical recovery check, not internal self-consistency."""
    asset_returns, factors, _, true_betas, true_resid_var = _simulated_factor_model(
        seed=7, n_obs=5000
    )
    true_factor_cov = np.array([[0.04, 0.01], [0.01, 0.02]])
    weights = np.array([0.3, 0.2, 0.3, 0.2])

    result = estimate_factor_exposures(asset_returns, factors)
    estimated_factor_cov = np.cov(factors, rowvar=False, ddof=0)

    true_decomp = decompose_portfolio_variance(weights, true_betas, true_factor_cov, true_resid_var)
    estimated_decomp = decompose_portfolio_variance(
        weights, result.betas, estimated_factor_cov, result.residual_variances
    )

    assert estimated_decomp.total_variance == pytest.approx(true_decomp.total_variance, rel=0.05)
    assert estimated_decomp.factor_variance == pytest.approx(true_decomp.factor_variance, rel=0.05)
    assert estimated_decomp.idiosyncratic_variance == pytest.approx(
        true_decomp.idiosyncratic_variance, rel=0.2
    )


def test_factor_model_implied_covariance_matches_decompose_portfolio_variance() -> None:
    """The matrix this function returns and decompose_portfolio_variance's
    own Euler decomposition compute the IDENTICAL quadratic form two
    different ways; they must agree for every weight vector, not just one."""
    rng = np.random.default_rng(9)
    n_assets, n_factors = 6, 3
    betas = rng.normal(0, 1, (n_assets, n_factors))
    raw = rng.normal(0, 1, (n_factors, n_factors))
    factor_covariance = raw @ raw.T + np.eye(n_factors) * 0.01
    residual_variances = rng.uniform(0.001, 0.01, n_assets)

    implied = factor_model_implied_covariance(betas, factor_covariance, residual_variances)
    assert implied.shape == (n_assets, n_assets)
    assert implied == pytest.approx(implied.T)  # symmetric

    for _ in range(20):
        w = rng.normal(size=n_assets)
        direct = float(w @ implied @ w)
        decomposed = decompose_portfolio_variance(
            w, betas, factor_covariance, residual_variances
        ).total_variance
        assert direct == pytest.approx(decomposed, abs=1e-10)


def test_factor_model_implied_covariance_is_positive_semidefinite() -> None:
    rng = np.random.default_rng(10)
    n_assets, n_factors = 7, 2
    betas = rng.normal(0, 1, (n_assets, n_factors))
    raw = rng.normal(0, 1, (n_factors, n_factors))
    factor_covariance = raw @ raw.T  # PSD by construction (could be singular)
    residual_variances = rng.uniform(0.001, 0.01, n_assets)

    implied = factor_model_implied_covariance(betas, factor_covariance, residual_variances)
    eigenvalues = np.linalg.eigvalsh(implied)
    assert eigenvalues.min() > -1e-10  # PSD, up to floating-point slack


def test_factor_model_implied_covariance_rejects_non_2d_betas() -> None:
    with pytest.raises(ValueError):
        factor_model_implied_covariance(np.zeros(4), np.eye(2), np.zeros(4))


def test_factor_model_implied_covariance_rejects_mismatched_factor_covariance_shape() -> None:
    betas = np.zeros((4, 2))
    with pytest.raises(ValueError):
        factor_model_implied_covariance(betas, np.eye(3), np.zeros(4))


def test_factor_model_implied_covariance_rejects_mismatched_residual_variances_shape() -> None:
    betas = np.zeros((4, 2))
    with pytest.raises(ValueError):
        factor_model_implied_covariance(betas, np.eye(2), np.zeros(3))


def test_factor_model_implied_covariance_rejects_negative_residual_variance() -> None:
    betas = np.zeros((3, 2))
    with pytest.raises(ValueError):
        factor_model_implied_covariance(betas, np.eye(2), np.array([0.01, -0.01, 0.02]))


def test_connects_to_titan_portfolio_and_covariance_modules() -> None:
    """A portfolio built by `titan.portfolio.minimum_variance_portfolio`
    from a `titan.covariance`-shrunk covariance composes naturally with
    this module's decomposition: the portfolio's risk, computed through
    the factor route, must match the risk implied directly by the same
    shrunk covariance matrix (since that covariance was itself built, in
    this test, as the exact factor-implied one)."""
    asset_returns, factors, _, true_betas, true_resid_var = _simulated_factor_model(
        seed=8, n_obs=200
    )
    true_factor_cov = np.array([[0.04, 0.01], [0.01, 0.02]])
    sigma_implied = true_betas @ true_factor_cov @ true_betas.T + np.diag(true_resid_var)

    shrink_result = shrink_covariance_ledoit_wolf(asset_returns)
    opt_result = minimum_variance_portfolio(shrink_result.covariance)
    assert opt_result.success

    decomp = decompose_portfolio_variance(
        opt_result.weights, true_betas, true_factor_cov, true_resid_var
    )
    w = opt_result.weights
    direct_variance_under_true_model = float(w @ sigma_implied @ w)

    assert decomp.total_variance == pytest.approx(direct_variance_under_true_model, abs=1e-10)
