"""Ledoit-Wolf covariance shrinkage (OPT-05: "robust covariance/scenario
uncertainty extension"; RISK-05: "volatility and covariance estimators --
PSD and shrinkage safeguards unit-tested").

The sample covariance of N assets from a short history of T < N (or T only
modestly larger than N) observations is a poor, high-variance estimate --
in the T < N case it is not even invertible, which silently breaks mean-
variance optimization (it needs Sigma^-1, or a solver that implicitly
requires Sigma to be well-conditioned). Ledoit & Wolf (2004, "A Well-
Conditioned Estimator for Large-Dimensional Covariance Matrices", J.
Multivariate Analysis 88) shrink the sample covariance toward a scaled-
identity target mu*I (mu = trace(S)/N) by an analytically-derived,
asymptotically optimal intensity -- no cross-validation or numerical
search is needed, and the shrunk result is provably positive definite even
when the sample covariance itself is singular.

This implementation was derived by reading scikit-learn's
`sklearn.covariance.ledoit_wolf_shrinkage` source (not reimplemented from
memory of the paper) and is cross-checked against it directly in
tests/unit/test_covariance.py across several (n_observations, n_assets)
regimes, including n < p; scikit-learn itself is a dev-only dependency
used purely as that test oracle, not a runtime dependency of this module.

`shrinkage_intensity_to_target`/`shrink_covariance_to_target` generalize
the above from "shrink toward mu*I specifically" to "shrink toward ANY
fixed target matrix" (Ledoit & Wolf 2003, "Honey, I Shrunk the Sample
Covariance Matrix", J. Portfolio Management: for a target that is a fixed
constant rather than itself estimated from this same sample, the
asymptotic covariance between the target and the sample estimator is
zero, so the optimal intensity reduces to pi_hat / gamma_hat, where
pi_hat -- the sample covariance's own total estimation-error variance --
does not depend on the target at all, and gamma_hat is the squared
Frobenius distance between target and population covariance, estimated
by the distance to the sample covariance). This is a separate,
independently-written implementation, not a refactor of
`ledoit_wolf_shrinkage_intensity` -- tests/unit/test_covariance.py
confirms the two agree exactly when `target = mu * I`, the scaled-
identity special case. `titan.factor_model.factor_model_implied_covariance`
is one useful choice of target beyond the identity: shrinking toward a
believed factor structure instead of toward "no structure at all."
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def ledoit_wolf_shrinkage_intensity(returns: np.ndarray) -> float:
    """The shrinkage intensity delta* in [0, 1] for shrinking the sample
    covariance of `returns` (shape (n_observations, n_assets)) toward
    mu*I. delta* = 0 means "use the raw sample covariance unshrunk";
    delta* = 1 means "use mu*I entirely", though in practice it is clamped
    to a feasible upper bound derived from the data's own estimation
    error, never chosen by cross-validation."""
    returns = np.asarray(returns, dtype=float)
    if returns.ndim != 2:
        raise ValueError("returns must be 2-D (n_observations, n_assets)")
    n, p = returns.shape
    if n < 2:
        raise ValueError("returns must have at least 2 observations")
    if p < 1:
        raise ValueError("returns must have at least 1 asset")
    if p == 1:
        return 0.0

    x = returns - returns.mean(axis=0)
    x_squared = x**2
    trace_terms = x_squared.sum(axis=0) / n
    mu = float(trace_terms.sum() / p)

    beta_sum = float(np.sum(x_squared.T @ x_squared))
    delta_sum = float(np.sum((x.T @ x) ** 2)) / (n**2)

    beta = (beta_sum / n - delta_sum) / (p * n)
    gamma = (delta_sum - p * mu**2) / p

    beta = min(beta, gamma)
    if beta <= 0.0:
        return 0.0
    return float(np.clip(beta / gamma, 0.0, 1.0))


@dataclass(frozen=True, slots=True)
class ShrinkageResult:
    covariance: np.ndarray
    """The shrunk covariance estimate: (1 - shrinkage) * sample_covariance
    + shrinkage * target."""
    sample_covariance: np.ndarray
    target: np.ndarray
    shrinkage_intensity: float


def shrink_covariance_ledoit_wolf(returns: np.ndarray) -> ShrinkageResult:
    returns = np.asarray(returns, dtype=float)
    shrinkage = ledoit_wolf_shrinkage_intensity(returns)  # validates shape/size first
    n, p = returns.shape

    x = returns - returns.mean(axis=0)
    sample_covariance = (x.T @ x) / n
    mu = float(np.trace(sample_covariance) / p)
    target = mu * np.eye(p)
    covariance = (1.0 - shrinkage) * sample_covariance + shrinkage * target

    return ShrinkageResult(
        covariance=covariance,
        sample_covariance=sample_covariance,
        target=target,
        shrinkage_intensity=shrinkage,
    )


def shrinkage_intensity_to_target(returns: np.ndarray, target: np.ndarray) -> float:
    """The optimal linear-shrinkage intensity in [0, 1] for shrinking the
    sample covariance of `returns` toward `target` -- any FIXED (p, p)
    matrix, not re-estimated from `returns` itself. See this module's own
    docstring for the closed-form derivation; `target = mu * I` is this
    function's own special case, kept separately as
    `ledoit_wolf_shrinkage_intensity` above."""
    returns = np.asarray(returns, dtype=float)
    if returns.ndim != 2:
        raise ValueError("returns must be 2-D (n_observations, n_assets)")
    n, p = returns.shape
    if n < 2:
        raise ValueError("returns must have at least 2 observations")
    if p < 1:
        raise ValueError("returns must have at least 1 asset")
    target = np.asarray(target, dtype=float)
    if target.shape != (p, p):
        raise ValueError(f"target must have shape ({p}, {p}), got {target.shape}")

    x = returns - returns.mean(axis=0)
    x_squared = x**2
    sample_covariance = (x.T @ x) / n
    beta_sum = float(np.sum(x_squared.T @ x_squared))
    delta_sum = float(np.sum((x.T @ x) ** 2)) / (n**2)
    # pi_hat: the sample covariance's own estimation-error variance --
    # identical to ledoit_wolf_shrinkage_intensity's `beta`, and, unlike
    # gamma_hat below, independent of which target was chosen.
    pi_hat = (beta_sum / n - delta_sum) / (p * n)
    gamma_hat = float(np.sum((target - sample_covariance) ** 2)) / p

    pi_hat = min(pi_hat, gamma_hat)
    if pi_hat <= 0.0 or gamma_hat <= 0.0:
        return 0.0
    return float(np.clip(pi_hat / gamma_hat, 0.0, 1.0))


def shrink_covariance_to_target(returns: np.ndarray, target: np.ndarray) -> ShrinkageResult:
    returns = np.asarray(returns, dtype=float)
    target = np.asarray(target, dtype=float)
    shrinkage = shrinkage_intensity_to_target(returns, target)  # validates shapes first
    n, _p = returns.shape

    x = returns - returns.mean(axis=0)
    sample_covariance = (x.T @ x) / n
    covariance = (1.0 - shrinkage) * sample_covariance + shrinkage * target

    return ShrinkageResult(
        covariance=covariance,
        sample_covariance=sample_covariance,
        target=target,
        shrinkage_intensity=shrinkage,
    )
