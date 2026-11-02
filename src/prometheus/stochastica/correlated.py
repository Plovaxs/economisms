"""Correlated normal draws from a validated covariance matrix.

VAL-04: "Validate covariance symmetry and positive semidefiniteness --
Adversarial matrices rejected or repaired with warning." A covariance
matrix that is symmetric but has small negative eigenvalues purely from
floating-point error in its construction (common after averaging or
shrinkage) is repaired by clipping those eigenvalues to zero, with a
warning; a matrix with a materially negative eigenvalue, or one that is not
symmetric at all, is rejected outright.
"""

from __future__ import annotations

import warnings

import numpy as np

_SYMMETRY_ATOL = 1e-8
_NEGATIVE_EIGENVALUE_REPAIR_TOLERANCE = 1e-8


class CovarianceError(ValueError):
    """Raised when a covariance matrix is not usable even after repair."""


def validate_and_repair_covariance(cov: np.ndarray) -> np.ndarray:
    """Return a covariance matrix guaranteed to be symmetric PSD (up to
    floating-point tolerance), raising CovarianceError if `cov` cannot be
    trusted even after clipping small negative eigenvalues."""
    cov = np.asarray(cov, dtype=float)
    if cov.ndim != 2 or cov.shape[0] != cov.shape[1]:
        raise CovarianceError(f"covariance must be a square matrix, got shape {cov.shape}")
    if not np.allclose(cov, cov.T, atol=_SYMMETRY_ATOL):
        raise CovarianceError("covariance matrix is not symmetric")

    eigenvalues, eigenvectors = np.linalg.eigh(cov)
    min_eigenvalue = float(eigenvalues.min())
    if min_eigenvalue < -_NEGATIVE_EIGENVALUE_REPAIR_TOLERANCE:
        raise CovarianceError(
            f"covariance matrix is not positive semidefinite: "
            f"minimum eigenvalue={min_eigenvalue:.3e}"
        )
    if min_eigenvalue < 0:
        warnings.warn(
            f"covariance matrix had a small negative eigenvalue ({min_eigenvalue:.3e}); "
            "clipping it to zero",
            stacklevel=2,
        )
    clipped = np.clip(eigenvalues, 0.0, None)
    result: np.ndarray = eigenvectors @ np.diag(clipped) @ eigenvectors.T
    return result


def correlated_normal_draws(
    rng: np.random.Generator, n_draws: int, cov: np.ndarray
) -> np.ndarray:
    """Draw `n_draws` i.i.d. samples from N(0, cov). Returns an array of
    shape (n_draws, dim). Uses an eigendecomposition rather than a Cholesky
    factorization so that an exactly-singular (rank-deficient) but valid
    PSD covariance does not raise -- Cholesky would."""
    repaired = validate_and_repair_covariance(cov)
    eigenvalues, eigenvectors = np.linalg.eigh(repaired)
    sqrt_cov = eigenvectors @ np.diag(np.sqrt(np.clip(eigenvalues, 0.0, None)))
    dim = repaired.shape[0]
    z = rng.standard_normal((n_draws, dim))
    draws: np.ndarray = z @ sqrt_cov.T
    return draws
