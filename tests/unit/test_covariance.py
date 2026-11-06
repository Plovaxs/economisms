import numpy as np
import pytest
from sklearn.covariance import ledoit_wolf, ledoit_wolf_shrinkage

from prometheus.titan.covariance import (
    ledoit_wolf_shrinkage_intensity,
    shrink_covariance_ledoit_wolf,
    shrink_covariance_to_target,
    shrinkage_intensity_to_target,
)
from prometheus.titan.factor_model import estimate_factor_exposures, factor_model_implied_covariance
from prometheus.titan.portfolio import minimum_variance_portfolio


def test_rejects_non_2d_input() -> None:
    with pytest.raises(ValueError):
        ledoit_wolf_shrinkage_intensity(np.zeros(10))


def test_rejects_too_few_observations() -> None:
    with pytest.raises(ValueError):
        ledoit_wolf_shrinkage_intensity(np.zeros((1, 5)))


def test_rejects_zero_assets() -> None:
    with pytest.raises(ValueError):
        ledoit_wolf_shrinkage_intensity(np.zeros((10, 0)))


def test_single_asset_has_zero_shrinkage() -> None:
    rng = np.random.default_rng(0)
    returns = rng.normal(0.0, 0.1, (50, 1))
    assert ledoit_wolf_shrinkage_intensity(returns) == 0.0


@pytest.mark.parametrize("n,p", [(500, 5), (20, 5), (5, 20), (100, 100), (3, 50), (2, 2)])
def test_shrinkage_intensity_matches_sklearn_exactly(n: int, p: int) -> None:
    """Derived by reading sklearn's source, not reimplemented from memory
    of the paper -- cross-checked here against that same source across
    n > p, n < p, n == p and the n == 2 boundary case."""
    rng = np.random.default_rng(hash((n, p)) % (2**32))
    cov = np.eye(p) * 0.04
    returns = rng.multivariate_normal(np.zeros(p), cov, size=n)

    mine = ledoit_wolf_shrinkage_intensity(returns)
    theirs = ledoit_wolf_shrinkage(returns)
    assert mine == pytest.approx(theirs, abs=1e-9)


@pytest.mark.parametrize("n,p", [(50, 4), (8, 10), (30, 30)])
def test_shrunk_covariance_matches_sklearn_ledoit_wolf(n: int, p: int) -> None:
    rng = np.random.default_rng(hash((n, p, "cov")) % (2**32))
    base = rng.normal(0, 0.2, (p, p))
    true_cov = base @ base.T / p + np.eye(p) * 0.01
    returns = rng.multivariate_normal(np.zeros(p), true_cov, size=n)

    mine = shrink_covariance_ledoit_wolf(returns)
    their_cov, their_shrinkage = ledoit_wolf(returns)

    assert mine.shrinkage_intensity == pytest.approx(their_shrinkage, abs=1e-9)
    assert mine.covariance == pytest.approx(their_cov, abs=1e-9)


def test_shrunk_covariance_is_symmetric() -> None:
    rng = np.random.default_rng(1)
    returns = rng.normal(0, 0.1, (10, 6))
    result = shrink_covariance_ledoit_wolf(returns)
    assert result.covariance == pytest.approx(result.covariance.T)


def test_shrinkage_recovers_positive_definiteness_from_a_singular_sample() -> None:
    """n < p: the sample covariance is necessarily singular (rank <= n-1 <
    p), which silently breaks anything requiring Sigma^-1. The shrunk
    estimate must be strictly positive definite regardless."""
    rng = np.random.default_rng(2)
    p = 8
    base = rng.normal(0, 0.2, (p, p))
    true_cov = base @ base.T / p + np.eye(p) * 0.01
    returns = rng.multivariate_normal(np.zeros(p), true_cov, size=4)  # n=4 < p=8

    result = shrink_covariance_ledoit_wolf(returns)

    sample_eigenvalues = np.linalg.eigvalsh(result.sample_covariance)
    assert sample_eigenvalues.min() < 1e-8  # confirms the sample cov really is (near-)singular

    shrunk_eigenvalues = np.linalg.eigvalsh(result.covariance)
    assert shrunk_eigenvalues.min() > 0.0


def test_shrinkage_is_higher_for_a_small_sample_than_a_large_one() -> None:
    """With a non-identity true covariance (so the target is not trivially
    'already correct'), more data should mean less need to shrink."""
    rng = np.random.default_rng(3)
    p = 6
    base = rng.normal(0, 0.2, (p, p))
    true_cov = base @ base.T / p + np.eye(p) * 0.01

    small_sample = rng.multivariate_normal(np.zeros(p), true_cov, size=10)
    large_sample = rng.multivariate_normal(np.zeros(p), true_cov, size=5000)

    small_shrinkage = ledoit_wolf_shrinkage_intensity(small_sample)
    large_shrinkage = ledoit_wolf_shrinkage_intensity(large_sample)
    assert small_shrinkage > large_shrinkage
    assert large_shrinkage < 0.1  # should be nearly unshrunk with ample data


def test_reduces_true_out_of_sample_portfolio_variance_vs_raw_sample_covariance() -> None:
    """The practical payoff, connecting TITAN's covariance and portfolio
    modules directly: across repeated small-sample draws from a fixed true
    covariance, the minimum-variance portfolio built from the SHRUNK
    covariance has lower TRUE (population) variance than the one built
    from the raw sample covariance, on average and in most individual
    trials -- not just a claim about the covariance matrix in isolation."""
    rng = np.random.default_rng(7)
    p = 10
    base = rng.normal(0, 0.2, (p, p))
    true_cov = base @ base.T / p + np.eye(p) * 0.01
    n_train = 15

    raw_oos_variances = []
    shrunk_oos_variances = []
    for _ in range(60):
        train = rng.multivariate_normal(np.zeros(p), true_cov, size=n_train)
        sample_cov = np.cov(train, rowvar=False, ddof=0)
        shrunk_cov = shrink_covariance_ledoit_wolf(train).covariance

        raw_result = minimum_variance_portfolio(sample_cov)
        shrunk_result = minimum_variance_portfolio(shrunk_cov)
        if not (raw_result.success and shrunk_result.success):
            continue
        raw_oos_variances.append(raw_result.weights @ true_cov @ raw_result.weights)
        shrunk_oos_variances.append(shrunk_result.weights @ true_cov @ shrunk_result.weights)

    raw_oos_variances = np.array(raw_oos_variances)
    shrunk_oos_variances = np.array(shrunk_oos_variances)
    assert len(raw_oos_variances) > 50  # almost all trials should have succeeded

    assert shrunk_oos_variances.mean() < raw_oos_variances.mean()
    win_rate = (shrunk_oos_variances < raw_oos_variances).mean()
    assert win_rate > 0.6


# -- shrinkage_intensity_to_target / shrink_covariance_to_target ----------
# Generalizes the two functions above from "shrink toward mu*I" to "shrink
# toward any fixed target matrix" (PR-050). See covariance.py's own
# docstring for the derivation.


def test_target_shrinkage_rejects_non_2d_input() -> None:
    with pytest.raises(ValueError):
        shrinkage_intensity_to_target(np.zeros(10), np.eye(1))


def test_target_shrinkage_rejects_too_few_observations() -> None:
    with pytest.raises(ValueError):
        shrinkage_intensity_to_target(np.zeros((1, 5)), np.eye(5))


def test_target_shrinkage_rejects_zero_assets() -> None:
    with pytest.raises(ValueError):
        shrinkage_intensity_to_target(np.zeros((10, 0)), np.zeros((0, 0)))


def test_target_shrinkage_rejects_mismatched_target_shape() -> None:
    rng = np.random.default_rng(20)
    returns = rng.normal(0, 0.1, (10, 4))
    with pytest.raises(ValueError):
        shrinkage_intensity_to_target(returns, np.eye(3))


@pytest.mark.parametrize("n,p", [(500, 5), (20, 5), (5, 20), (100, 100), (3, 50), (50, 1)])
def test_target_shrinkage_matches_the_identity_special_case_exactly(n: int, p: int) -> None:
    """A completely independent implementation (shrinkage_intensity_to_target
    with target = mu*I) must reproduce ledoit_wolf_shrinkage_intensity's own
    specific-case implementation exactly -- the two are not one calling the
    other, so agreement here is real evidence, not a tautology."""
    rng = np.random.default_rng(hash((n, p, "target")) % (2**32))
    returns = rng.normal(scale=0.02, size=(n, p))

    x = returns - returns.mean(axis=0)
    sample_covariance = (x.T @ x) / n
    mu = float(np.trace(sample_covariance) / p)
    identity_target = mu * np.eye(p)

    general = shrinkage_intensity_to_target(returns, identity_target)
    specific = ledoit_wolf_shrinkage_intensity(returns)
    assert general == pytest.approx(specific, abs=1e-10)


def test_shrink_covariance_to_target_matches_ledoit_wolf_for_identity_target() -> None:
    rng = np.random.default_rng(21)
    p = 8
    base = rng.normal(0, 0.2, (p, p))
    true_cov = base @ base.T / p + np.eye(p) * 0.01
    returns = rng.multivariate_normal(np.zeros(p), true_cov, size=20)

    x = returns - returns.mean(axis=0)
    mu = float(np.trace((x.T @ x) / 20) / p)
    identity_target = mu * np.eye(p)

    general = shrink_covariance_to_target(returns, identity_target)
    specific = shrink_covariance_ledoit_wolf(returns)
    assert general.shrinkage_intensity == pytest.approx(specific.shrinkage_intensity, abs=1e-10)
    assert general.covariance == pytest.approx(specific.covariance, abs=1e-10)


def test_shrink_covariance_to_target_is_symmetric_and_positive_definite_from_singular_sample() -> (
    None
):
    rng = np.random.default_rng(22)
    p = 8
    base = rng.normal(0, 0.2, (p, p))
    true_cov = base @ base.T / p + np.eye(p) * 0.01
    returns = rng.multivariate_normal(np.zeros(p), true_cov, size=4)  # n=4 < p=8

    target = np.eye(p) * 0.05  # an arbitrary fixed target, not derived from the sample
    result = shrink_covariance_to_target(returns, target)

    assert result.covariance == pytest.approx(result.covariance.T)
    eigenvalues = np.linalg.eigvalsh(result.covariance)
    assert eigenvalues.min() > 0.0


def test_factor_target_reduces_average_estimation_error_vs_identity_target() -> None:
    """The actual point of adding a second target: when returns really ARE
    generated by a known factor structure, shrinking toward that
    (estimated) structure gives lower average Frobenius-norm error against
    the TRUE covariance than shrinking toward scaled identity, over
    repeated modest-sample draws -- not just a claim about one matrix."""
    rng = np.random.default_rng(23)
    n_assets, n_factors = 10, 2
    true_betas = rng.normal(scale=1.0, size=(n_assets, n_factors))
    true_factor_cov = np.array([[0.0004, 0.00005], [0.00005, 0.0002]])
    true_idio_var = rng.uniform(0.0005, 0.002, size=n_assets)
    true_covariance = factor_model_implied_covariance(true_betas, true_factor_cov, true_idio_var)

    n_obs = 60  # modest: only ~6x the number of assets
    identity_errors = []
    factor_errors = []
    for _ in range(200):
        factor_returns = rng.multivariate_normal(np.zeros(n_factors), true_factor_cov, size=n_obs)
        idio = rng.normal(size=(n_obs, n_assets)) * np.sqrt(true_idio_var)
        asset_returns = factor_returns @ true_betas.T + idio

        identity_shrunk = shrink_covariance_ledoit_wolf(asset_returns)
        identity_errors.append(np.sum((identity_shrunk.covariance - true_covariance) ** 2))

        exposures = estimate_factor_exposures(asset_returns, factor_returns)
        factor_cov_hat = np.cov(factor_returns, rowvar=False, ddof=0)
        factor_target = factor_model_implied_covariance(
            exposures.betas, factor_cov_hat, exposures.residual_variances
        )
        factor_shrunk = shrink_covariance_to_target(asset_returns, factor_target)
        factor_errors.append(np.sum((factor_shrunk.covariance - true_covariance) ** 2))

    assert np.mean(factor_errors) < np.mean(identity_errors)


def test_factor_target_portfolio_has_lower_true_variance_than_identity_target_portfolio() -> None:
    """The practical payoff, mirroring
    test_reduces_true_out_of_sample_portfolio_variance_vs_raw_sample_covariance
    above: the minimum-variance portfolio built from the factor-shrunk
    covariance has lower TRUE out-of-sample variance, on average, than the
    one built from the identity-shrunk covariance, when the true
    covariance really does follow that factor structure."""
    rng = np.random.default_rng(24)
    n_assets, n_factors = 8, 2
    true_betas = rng.normal(scale=1.0, size=(n_assets, n_factors))
    true_factor_cov = np.array([[0.0004, 0.00005], [0.00005, 0.0002]])
    true_idio_var = rng.uniform(0.0005, 0.002, size=n_assets)
    true_covariance = factor_model_implied_covariance(true_betas, true_factor_cov, true_idio_var)

    n_obs = 40
    identity_oos_variances = []
    factor_oos_variances = []
    for _ in range(80):
        factor_returns = rng.multivariate_normal(np.zeros(n_factors), true_factor_cov, size=n_obs)
        idio = rng.normal(size=(n_obs, n_assets)) * np.sqrt(true_idio_var)
        asset_returns = factor_returns @ true_betas.T + idio

        identity_shrunk = shrink_covariance_ledoit_wolf(asset_returns).covariance
        exposures = estimate_factor_exposures(asset_returns, factor_returns)
        factor_cov_hat = np.cov(factor_returns, rowvar=False, ddof=0)
        factor_target = factor_model_implied_covariance(
            exposures.betas, factor_cov_hat, exposures.residual_variances
        )
        factor_shrunk = shrink_covariance_to_target(asset_returns, factor_target).covariance

        identity_result = minimum_variance_portfolio(identity_shrunk)
        factor_result = minimum_variance_portfolio(factor_shrunk)
        if not (identity_result.success and factor_result.success):
            continue
        identity_oos_variances.append(
            identity_result.weights @ true_covariance @ identity_result.weights
        )
        factor_oos_variances.append(
            factor_result.weights @ true_covariance @ factor_result.weights
        )

    identity_oos_variances = np.array(identity_oos_variances)
    factor_oos_variances = np.array(factor_oos_variances)
    assert len(identity_oos_variances) > 60  # almost all trials should have succeeded
    assert factor_oos_variances.mean() < identity_oos_variances.mean()
