"""NSD-08/NSD-09: proper scoring rules and distributional moment
diagnostics.

NSD-08 ("CRPS/log score or justified alternatives reported"): the log
score is `neural_sde.training.gaussian_transition_nll`, reused directly
rather than recomputed -- it already IS the Gaussian log-likelihood. For
CRPS, this package's predictive distribution is a MULTIVARIATE Gaussian
(the full Sigma output by `DriftDiffusionNet`), and there is no closed
form for multivariate CRPS/the energy score in general; the justified
alternative used here is the per-dimension (marginal) CRPS -- the
closed-form univariate Gneiting & Raftery (2007) formula applied to
each state dimension's own (marginal mean, marginal variance = diag of
Sigma), averaged across dimensions. This is disclosed explicitly, not
silently presented as a full multivariate score.

NSD-09 ("return tails, skew, volatility persistence -- moment
diagnostics with confidence intervals") reports skew and excess kurtosis
of a Monte Carlo-simulated terminal distribution, with percentile
bootstrap confidence intervals (resampling the simulated PATHS, not the
underlying data -- the underlying real monthly series is far too short,
~40 years of monthly data, to bootstrap meaningfully on its own).
"Volatility persistence" is reported as the lag-1 autocorrelation of
simulated |return| (a standard proxy for volatility clustering), also
with a bootstrap CI.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats

_SQRT_PI = float(np.sqrt(np.pi))


def gaussian_log_score(mu: np.ndarray, sigma: np.ndarray, observed: np.ndarray) -> float:
    """Mean Gaussian negative log-likelihood (the log score), computed in
    plain numpy -- the evaluation-time counterpart of
    `neural_sde.training.gaussian_transition_nll` (torch, differentiable,
    used only inside the training loop). Both implement the identical
    Cholesky-based multivariate Gaussian NLL independently (torch
    autograd vs. numpy) because training needs autograd and
    post-hoc/baseline scoring does not; `test_neural_sde_scoring.py`
    cross-checks the two agree numerically on a shared toy case so the
    duplication cannot silently drift apart. Used here to score every
    `neural_sde.benchmark` candidate -- including non-neural baselines
    that never touch torch -- on the same metric."""
    mu = np.asarray(mu, dtype=float)
    sigma = np.asarray(sigma, dtype=float)
    observed = np.asarray(observed, dtype=float)
    if mu.ndim == 1:
        mu, sigma, observed = mu[None, :], sigma[None, :, :], observed[None, :]
    n_obs, k = mu.shape
    nlls = np.empty(n_obs)
    for i in range(n_obs):
        residual = observed[i] - mu[i]
        chol = np.linalg.cholesky(sigma[i] + 1e-10 * np.eye(k))
        z = np.linalg.solve(chol, residual)
        quadratic = float(z @ z)
        log_det = 2.0 * float(np.sum(np.log(np.diag(chol))))
        nlls[i] = 0.5 * (quadratic + log_det + k * np.log(2 * np.pi))
    return float(nlls.mean())


def gaussian_crps(mu: float, sigma: float, observed: float) -> float:
    """Closed-form CRPS of N(mu, sigma^2) against a single observed
    value (Gneiting & Raftery 2007, eq. 5)."""
    if sigma <= 0:
        raise ValueError("sigma must be positive")
    z = (observed - mu) / sigma
    crps = sigma * (z * (2 * stats.norm.cdf(z) - 1) + 2 * stats.norm.pdf(z) - 1 / _SQRT_PI)
    return float(crps)


def marginal_crps_report(
    mu: np.ndarray, sigma_diag: np.ndarray, observed: np.ndarray
) -> dict[str, float]:
    """mu, sigma_diag, observed: (n_obs, state_dim). Returns the mean
    per-dimension CRPS, averaged first within each dimension across
    observations, then across dimensions -- so one noisy dimension
    cannot dominate purely by having larger raw units."""
    mu = np.asarray(mu, dtype=float)
    sigma_diag = np.asarray(sigma_diag, dtype=float)
    observed = np.asarray(observed, dtype=float)
    if not (mu.shape == sigma_diag.shape == observed.shape):
        raise ValueError("mu, sigma_diag and observed must all share the same shape")
    n_obs, state_dim = mu.shape
    per_dim_crps = np.empty(state_dim)
    for d in range(state_dim):
        values = [
            gaussian_crps(float(mu[i, d]), float(sigma_diag[i, d]) ** 0.5, float(observed[i, d]))
            for i in range(n_obs)
        ]
        per_dim_crps[d] = float(np.mean(values))
    return {
        "mean_crps": float(per_dim_crps.mean()),
        **{f"crps_dim_{d}": float(per_dim_crps[d]) for d in range(state_dim)},
    }


@dataclass(frozen=True, slots=True)
class MomentDiagnostics:
    skew: float
    skew_ci_low: float
    skew_ci_high: float
    excess_kurtosis: float
    kurtosis_ci_low: float
    kurtosis_ci_high: float
    volatility_persistence: float
    volatility_persistence_ci_low: float
    volatility_persistence_ci_high: float
    n_paths: int
    n_bootstrap: int


def _lag1_autocorrelation_of_abs(path: np.ndarray) -> float:
    abs_returns = np.abs(np.diff(path))
    if len(abs_returns) < 2 or np.std(abs_returns) == 0:
        return 0.0
    corr = np.corrcoef(abs_returns[:-1], abs_returns[1:])[0, 1]
    return float(corr) if np.isfinite(corr) else 0.0


def moment_diagnostics(
    terminal_values: np.ndarray,
    full_paths: np.ndarray,
    *,
    n_bootstrap: int = 500,
    seed: int = 0,
    confidence: float = 0.90,
) -> MomentDiagnostics:
    """terminal_values: (n_paths,) terminal state values for one state
    dimension. full_paths: (n_paths, n_steps + 1) the same dimension's
    full simulated paths, for the volatility-persistence diagnostic."""
    terminal_values = np.asarray(terminal_values, dtype=float)
    full_paths = np.asarray(full_paths, dtype=float)
    n_paths = terminal_values.shape[0]
    if n_paths < 10:
        raise ValueError("need at least 10 simulated paths for moment diagnostics")

    rng = np.random.default_rng(seed)
    skews = np.empty(n_bootstrap)
    kurtoses = np.empty(n_bootstrap)
    persistences = np.empty(n_bootstrap)
    for b in range(n_bootstrap):
        idx: np.ndarray = rng.integers(0, n_paths, size=(n_paths,))
        sample = terminal_values[idx]
        skews[b] = stats.skew(sample)
        kurtoses[b] = stats.kurtosis(sample)
        subsample_idx = idx[:50]
        persistences[b] = np.mean(
            [_lag1_autocorrelation_of_abs(full_paths[i]) for i in subsample_idx]
        )

    alpha = (1 - confidence) / 2
    lo, hi = 100 * alpha, 100 * (1 - alpha)
    return MomentDiagnostics(
        skew=float(stats.skew(terminal_values)),
        skew_ci_low=float(np.percentile(skews, lo)),
        skew_ci_high=float(np.percentile(skews, hi)),
        excess_kurtosis=float(stats.kurtosis(terminal_values)),
        kurtosis_ci_low=float(np.percentile(kurtoses, lo)),
        kurtosis_ci_high=float(np.percentile(kurtoses, hi)),
        volatility_persistence=float(
            np.mean([_lag1_autocorrelation_of_abs(full_paths[i]) for i in range(min(n_paths, 50))])
        ),
        volatility_persistence_ci_low=float(np.percentile(persistences, lo)),
        volatility_persistence_ci_high=float(np.percentile(persistences, hi)),
        n_paths=n_paths,
        n_bootstrap=n_bootstrap,
    )
