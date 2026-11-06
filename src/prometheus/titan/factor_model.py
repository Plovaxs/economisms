"""Factor exposure model and risk decomposition (RISK-07): recover each
asset's loadings on a set of common factors by ordinary least squares, then
split a portfolio's total variance into systematic (factor-driven) and
idiosyncratic (asset-specific) components under the standard APT
assumption that idiosyncratic shocks are uncorrelated across assets.

estimate_factor_exposures     -- per-asset alpha, factor betas, residual
                                  variance and R^2 from historical asset
                                  and factor returns, via the OLS normal
                                  equations. Cross-checked in tests against
                                  an independent linear-algebra method
                                  (`numpy.linalg.lstsq`, a different
                                  algorithm -- QR/SVD-based, not matrix
                                  inversion) to machine precision.
decompose_portfolio_variance  -- splits total portfolio variance into
                                  `factor_variance` + `idiosyncratic_variance`,
                                  plus a per-factor Euler/marginal variance
                                  contribution (`x_f * (Sigma_f x)_f`) that
                                  sums exactly to `factor_variance` -- the
                                  same marginal-contribution allocation
                                  idea already used informally elsewhere in
                                  risk-contribution literature.
factor_model_implied_covariance -- the full (n_assets, n_assets) matrix
                                  Sigma = B Sigma_f B' + diag(resid_var)
                                  this factor model implies. The identical
                                  quadratic form `decompose_portfolio_variance`
                                  already computes via its factor-space
                                  Euler decomposition, promoted to its own
                                  reusable matrix so a caller that needs the
                                  full covariance (e.g. titan.covariance's
                                  factor-model shrinkage target, PR-050)
                                  does not re-derive it inline.

Validated end to end with a Monte Carlo recovery test, not just unit
self-consistency: returns are simulated from a KNOWN factor model (known
betas, known factor covariance, known idiosyncratic variances), exposures
are estimated from the simulated sample alone, and the ESTIMATED
decomposition is confirmed to converge toward the TRUE one as the sample
grows.

Standalone, like every TITAN module before it had been at the point it was
introduced: not wired into `StepHooks`, `titan.portfolio`, or
`titan.covariance`, though a portfolio built by `titan.portfolio` and a
covariance estimated by `titan.covariance` compose naturally with this
module's `decompose_portfolio_variance` -- demonstrated in
`tests/unit/test_factor_model.py`, not assumed.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class FactorExposureResult:
    alphas: np.ndarray
    betas: np.ndarray
    residual_variances: np.ndarray
    r_squared: np.ndarray


def estimate_factor_exposures(
    asset_returns: np.ndarray, factor_returns: np.ndarray
) -> FactorExposureResult:
    """OLS regression of each asset's returns on the factor returns, with
    an intercept. `asset_returns` is (n_obs, n_assets), `factor_returns` is
    (n_obs, n_factors); every asset is regressed in one normal-equations
    solve (one shared design matrix), not asset by asset."""
    asset_returns = np.asarray(asset_returns, dtype=float)
    factor_returns = np.asarray(factor_returns, dtype=float)
    if asset_returns.ndim != 2:
        raise ValueError("asset_returns must be 2-D (n_obs, n_assets)")
    if factor_returns.ndim != 2:
        raise ValueError("factor_returns must be 2-D (n_obs, n_factors)")
    n_obs, n_assets = asset_returns.shape
    n_obs_factors, n_factors = factor_returns.shape
    if n_obs != n_obs_factors:
        raise ValueError(
            f"asset_returns has {n_obs} observations but factor_returns has {n_obs_factors}"
        )
    required = n_factors + 2
    if n_obs < required:
        raise ValueError(
            f"need at least n_factors + 2 = {required} observations "
            f"(intercept + {n_factors} factor slopes + 1 residual degree of freedom), got {n_obs}"
        )

    design = np.column_stack([np.ones(n_obs), factor_returns])
    gram = design.T @ design
    try:
        coeffs = np.linalg.solve(gram, design.T @ asset_returns)
    except np.linalg.LinAlgError as exc:
        raise ValueError(
            "factor_returns columns are singular/collinear (including the intercept); "
            "cannot estimate a unique OLS solution"
        ) from exc

    alphas = coeffs[0]
    betas = coeffs[1:].T
    fitted = design @ coeffs
    residuals = asset_returns - fitted
    residual_variances = np.mean(residuals**2, axis=0)
    total_variances = np.var(asset_returns, axis=0, ddof=0)
    has_variance = total_variances > 0.0
    safe_total_variances = np.where(has_variance, total_variances, 1.0)
    r_squared = np.where(has_variance, 1.0 - residual_variances / safe_total_variances, 0.0)
    return FactorExposureResult(
        alphas=alphas,
        betas=betas,
        residual_variances=residual_variances,
        r_squared=r_squared,
    )


@dataclass(frozen=True, slots=True)
class FactorRiskDecomposition:
    total_variance: float
    factor_variance: float
    idiosyncratic_variance: float
    factor_variance_contributions: np.ndarray


def decompose_portfolio_variance(
    weights: np.ndarray,
    betas: np.ndarray,
    factor_covariance: np.ndarray,
    residual_variances: np.ndarray,
) -> FactorRiskDecomposition:
    """Split a portfolio's total variance into systematic and
    idiosyncratic components, assuming idiosyncratic shocks are
    uncorrelated across assets (the standard APT/factor-model assumption):

        portfolio exposure e = weights @ betas               (n_factors,)
        factor_variance      = e' Sigma_f e
        idiosyncratic_var    = sum_i weights_i^2 * residual_variance_i
        total_variance        = factor_variance + idiosyncratic_variance

    `factor_variance_contributions[f] = e_f * (Sigma_f e)_f` is the Euler
    (marginal) allocation of `factor_variance` across factors; it sums to
    `factor_variance` exactly, by the algebraic identity e' Sigma_f e =
    sum_f e_f * (Sigma_f e)_f for any vector e and matrix Sigma_f.
    """
    weights = np.asarray(weights, dtype=float)
    betas = np.asarray(betas, dtype=float)
    factor_covariance = np.asarray(factor_covariance, dtype=float)
    residual_variances = np.asarray(residual_variances, dtype=float)

    n_assets, n_factors = betas.shape
    if weights.shape != (n_assets,):
        raise ValueError(f"weights must have shape ({n_assets},), got {weights.shape}")
    if factor_covariance.shape != (n_factors, n_factors):
        raise ValueError(
            f"factor_covariance must have shape ({n_factors}, {n_factors}), "
            f"got {factor_covariance.shape}"
        )
    if residual_variances.shape != (n_assets,):
        raise ValueError(
            f"residual_variances must have shape ({n_assets},), got {residual_variances.shape}"
        )
    if np.any(residual_variances < 0.0):
        raise ValueError("residual_variances must be non-negative")

    exposure = weights @ betas
    marginal = factor_covariance @ exposure
    contributions = exposure * marginal
    factor_variance = float(contributions.sum())
    idiosyncratic_variance = float(np.sum(weights**2 * residual_variances))

    return FactorRiskDecomposition(
        total_variance=factor_variance + idiosyncratic_variance,
        factor_variance=factor_variance,
        idiosyncratic_variance=idiosyncratic_variance,
        factor_variance_contributions=contributions,
    )


def factor_model_implied_covariance(
    betas: np.ndarray, factor_covariance: np.ndarray, residual_variances: np.ndarray
) -> np.ndarray:
    """The full (n_assets, n_assets) covariance matrix this factor model
    implies: Sigma = B Sigma_f B' + diag(residual_variances). Positive
    semi-definite whenever `factor_covariance` is (the diagonal term only
    adds non-negative values on the diagonal), since B Sigma_f B' is PSD
    for any PSD Sigma_f and any B.

    For any weight vector w, `w @ factor_model_implied_covariance(...) @ w`
    equals `decompose_portfolio_variance(w, ...).total_variance` exactly --
    the same quadratic form, computed two different ways. See
    `tests/unit/test_factor_model.py` for that cross-check.
    """
    betas = np.asarray(betas, dtype=float)
    factor_covariance = np.asarray(factor_covariance, dtype=float)
    residual_variances = np.asarray(residual_variances, dtype=float)

    if betas.ndim != 2:
        raise ValueError("betas must be 2-D (n_assets, n_factors)")
    n_assets, n_factors = betas.shape
    if factor_covariance.shape != (n_factors, n_factors):
        raise ValueError(
            f"factor_covariance must have shape ({n_factors}, {n_factors}), "
            f"got {factor_covariance.shape}"
        )
    if residual_variances.shape != (n_assets,):
        raise ValueError(
            f"residual_variances must have shape ({n_assets},), got {residual_variances.shape}"
        )
    if np.any(residual_variances < 0.0):
        raise ValueError("residual_variances must be non-negative")

    implied: np.ndarray = betas @ factor_covariance @ betas.T + np.diag(residual_variances)
    return implied
