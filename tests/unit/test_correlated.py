import numpy as np
import pytest

from prometheus.stochastica.correlated import (
    CovarianceError,
    correlated_normal_draws,
    validate_and_repair_covariance,
)


def test_valid_covariance_passes_through_unchanged() -> None:
    cov = np.array([[1.0, 0.5], [0.5, 2.0]])
    repaired = validate_and_repair_covariance(cov)
    assert np.allclose(repaired, cov)


def test_asymmetric_matrix_rejected() -> None:
    cov = np.array([[1.0, 0.9], [0.1, 1.0]])
    with pytest.raises(CovarianceError):
        validate_and_repair_covariance(cov)


def test_materially_non_psd_matrix_rejected() -> None:
    cov = np.array([[1.0, 2.0], [2.0, 1.0]])  # eigenvalues -1, 3
    with pytest.raises(CovarianceError):
        validate_and_repair_covariance(cov)


def test_tiny_negative_eigenvalue_is_repaired_with_warning() -> None:
    # A covariance matrix that is PSD in exact arithmetic but has a tiny
    # negative eigenvalue from floating-point round-off.
    cov = np.array([[1.0, 1.0], [1.0, 1.0]]) + np.array([[0.0, 0.0], [0.0, -1e-14]])
    with pytest.warns(UserWarning):
        repaired = validate_and_repair_covariance(cov)
    eigenvalues = np.linalg.eigvalsh(repaired)
    assert eigenvalues.min() >= 0.0


def test_non_square_matrix_rejected() -> None:
    with pytest.raises(CovarianceError):
        validate_and_repair_covariance(np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]))


def test_singular_psd_matrix_does_not_raise() -> None:
    # Rank-1 covariance (perfectly correlated variables) -- a naive Cholesky
    # would work here too, but this exercises the exactly-singular boundary.
    cov = np.array([[1.0, 1.0], [1.0, 1.0]])
    repaired = validate_and_repair_covariance(cov)
    eigenvalues = np.linalg.eigvalsh(repaired)
    assert eigenvalues.min() >= -1e-12


def test_correlated_draws_recover_approximate_covariance() -> None:
    rng = np.random.default_rng(0)
    cov = np.array([[1.0, 0.6], [0.6, 2.0]])
    draws = correlated_normal_draws(rng, 200_000, cov)
    sample_cov = np.cov(draws, rowvar=False)
    assert np.allclose(sample_cov, cov, atol=0.05)


def test_correlated_draws_shape() -> None:
    rng = np.random.default_rng(0)
    cov = np.eye(3)
    draws = correlated_normal_draws(rng, 10, cov)
    assert draws.shape == (10, 3)
