"""NSD-07/NSD-10: comparative benchmark report and multi-seed,
multi-solver sensitivity.

NSD-07 ("compare neural SDE with GBM/Heston and simple ML models --
pre-registered comparative benchmark report generated") compares five
FIXED candidates (`CANDIDATE_NAMES` below is a module-level constant,
defined once, before any benchmark is ever run, which is what makes the
comparison "pre-registered" rather than a post-hoc best-of selection):

  - `neural_sde`: the trained `DriftDiffusionNet` (state- and
    time-dependent drift/diffusion, learned).
  - `gbm_constant`: constant (not state-dependent) drift vector and full
    covariance matrix, MLE-fit (sample mean/covariance) on the TRAIN
    split's one-step deltas -- literally the multi-asset GBM family
    `stochastica.gbm.simulate_correlated_gbm_paths` already simulates
    from, with its (mu, sigma, correlation) estimated rather than given.
  - `garch_univariate`: a univariate GARCH(1,1) fit (Gaussian QMLE, via
    `scipy.optimize.minimize`) to the primary state dimension only
    (`KAGGLE_NASDAQ_YOY`'s one-step deltas); the second dimension and
    the cross-covariance term are held at their constant MLE values (no
    multivariate GARCH is implemented). This stands in for the
    acceptance text's literal "Heston": Heston prices an underlying with
    a price LEVEL and a stochastic variance process, and this package's
    state variables are YoY growth rates with no price level at all
    (see `neural_sde.design`'s constraints) -- forcing Heston's
    machinery onto a non-price series would be a worse category error
    than substituting the standard state-dependent-volatility benchmark
    for a RETURN series, which is GARCH, already implemented in this
    repository (`stochastica.garch`) for exactly this reason. This
    substitution is disclosed here, not silently made.
  - `persistence`: the "did the smart model beat doing nothing" floor --
    zero free parameters, predicts no change (drift = 0), with Sigma
    fixed at the train split's constant residual covariance.
  - `ar1_univariate`: closed-form OLS AR(1) fit independently per state
    dimension (no cross-dimension coupling, disclosed) -- the simple-ML
    baseline, matching Q-MACRO's (PR-143) own AR(3)-baseline precedent.

Every candidate is scored on the SAME held-out split with the SAME two
metrics (`neural_sde.scoring.gaussian_log_score`,
`neural_sde.scoring.marginal_crps_report`) via `benchmark_report`. The
log score is disclosed as structurally biased toward Gaussian-increment
models (it IS the Gaussian likelihood, so a model whose true error
distribution is non-Gaussian is penalized by the metric itself, not
necessarily by being a worse model) -- CRPS is the partial independent
cross-check kept for exactly that reason, per NSD-08's "or justified
alternatives".

NSD-10 ("multi-seed, multi-solver sensitivity study -- error bands
across seeds and integration schemes documented") is
`multi_seed_multi_solver_sensitivity`: simulates the trained neural SDE
forward from the same starting point under several `torch.Generator`
seeds AND both `neural_sde.integration` schemes (Euler-Maruyama,
stochastic Heun), and reports the terminal-value mean/std BOTH within a
scheme (across seeds) and between schemes (at matched seeds) -- the
difference between those two spreads is the actual evidence for whether
discretization-scheme choice matters here, not just random-seed noise.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch
from scipy import optimize

from prometheus.neural_sde.dataset import FittedScaler, TransitionExample
from prometheus.neural_sde.integration import simulate_euler_maruyama, simulate_stochastic_heun
from prometheus.neural_sde.model import DriftDiffusionNet
from prometheus.neural_sde.scoring import gaussian_log_score, marginal_crps_report
from prometheus.neural_sde.training import DT_SCALED

CANDIDATE_NAMES: tuple[str, ...] = (
    "neural_sde",
    "gbm_constant",
    "garch_univariate",
    "persistence",
    "ar1_univariate",
)


def _examples_to_arrays(
    examples: list[TransitionExample],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    state = np.array([e.state for e in examples])
    next_state = np.array([e.next_state for e in examples])
    delta = next_state - state
    return state, next_state, delta


@dataclass(frozen=True, slots=True)
class CandidateFit:
    name: str
    mu: np.ndarray
    """(n_obs, state_dim) predicted mean for every held-out example."""
    sigma: np.ndarray
    """(n_obs, state_dim, state_dim) predicted covariance for every
    held-out example."""


def fit_gbm_constant(train_examples: list[TransitionExample]) -> tuple[np.ndarray, np.ndarray]:
    """Returns (mean_delta, covariance_delta), both constant across time
    and state -- the MLE of a multi-asset GBM-style constant-parameter
    model."""
    _, _, delta = _examples_to_arrays(train_examples)
    mean = delta.mean(axis=0)
    cov = np.cov(delta.T) if delta.shape[1] > 1 else np.array([[delta.var()]])
    cov = cov + 1e-8 * np.eye(cov.shape[0])
    return mean, cov


def _garch11_negative_log_likelihood(params: np.ndarray, returns: np.ndarray) -> float:
    mu, log_omega, raw_alpha, raw_beta = params
    omega = float(np.exp(log_omega))
    alpha = float(1 / (1 + np.exp(-raw_alpha)) * 0.98)
    beta = float(1 / (1 + np.exp(-raw_beta)) * (0.98 - alpha))
    residuals = returns - mu
    unconditional_var = omega / max(1e-8, (1 - alpha - beta))
    h = unconditional_var
    nll = 0.0
    for t in range(len(returns)):
        h = max(h, 1e-10)
        nll += 0.5 * (np.log(2 * np.pi * h) + residuals[t] ** 2 / h)
        h = omega + alpha * residuals[t] ** 2 + beta * h
    return float(nll)


@dataclass(frozen=True, slots=True)
class FittedGarch11:
    mu: float
    omega: float
    alpha: float
    beta: float

    def conditional_variances(self, returns: np.ndarray) -> np.ndarray:
        """One-step-ahead conditional variance h_t for every return in
        `returns`, given this fit -- h_0 is the unconditional variance,
        each subsequent h_t uses the REALIZED previous residual (this is
        in-sample filtering, appropriate for scoring a held-out sequence
        that is itself fed in chronological order, not for forecasting
        multiple steps ahead without new data)."""
        residuals = returns - self.mu
        unconditional_var = self.omega / max(1e-8, (1 - self.alpha - self.beta))
        h = unconditional_var
        variances = np.empty(len(returns))
        for t in range(len(returns)):
            variances[t] = h
            h = self.omega + self.alpha * residuals[t] ** 2 + self.beta * h
        return variances


def fit_garch11(train_returns: np.ndarray, seed: int = 0) -> FittedGarch11:
    """Gaussian QMLE fit of a univariate GARCH(1,1) via unconstrained
    optimization over a reparameterization (log for omega>0; sigmoids
    scaled to enforce alpha>=0, beta>=0, alpha+beta<0.98<1, Bollerslev's
    stationarity condition with headroom) -- avoids needing a constrained
    optimizer for what is otherwise a simple 4-parameter fit."""
    train_returns = np.asarray(train_returns, dtype=float)
    x0 = np.array([train_returns.mean(), np.log(max(train_returns.var(), 1e-6)), -1.0, 2.0])
    result = optimize.minimize(
        _garch11_negative_log_likelihood,
        x0,
        args=(train_returns,),
        method="Nelder-Mead",
        options={"maxiter": 2000, "xatol": 1e-6, "fatol": 1e-6},
    )
    mu, log_omega, raw_alpha, raw_beta = result.x
    omega = float(np.exp(log_omega))
    alpha = float(1 / (1 + np.exp(-raw_alpha)) * 0.98)
    beta = float(1 / (1 + np.exp(-raw_beta)) * (0.98 - alpha))
    return FittedGarch11(mu=float(mu), omega=omega, alpha=alpha, beta=beta)


def fit_ar1(train_examples: list[TransitionExample]) -> list[tuple[float, float, float]]:
    """Per-dimension closed-form OLS AR(1): x_{t+1} = a + b*x_t + eps.
    Returns [(a, b, residual_std), ...] one tuple per state dimension."""
    state, next_state, _ = _examples_to_arrays(train_examples)
    state_dim = state.shape[1]
    fits = []
    for d in range(state_dim):
        x = state[:, d]
        y = next_state[:, d]
        design = np.column_stack([np.ones_like(x), x])
        coeffs, *_ = np.linalg.lstsq(design, y, rcond=None)
        a, b = coeffs
        residuals = y - design @ coeffs
        fits.append((float(a), float(b), float(residuals.std() + 1e-8)))
    return fits


def predict_candidate(
    name: str,
    held_out: list[TransitionExample],
    train_examples: list[TransitionExample],
    *,
    neural_model: DriftDiffusionNet | None = None,
    state_scaler: FittedScaler | None = None,
    regime_scaler: FittedScaler | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    state, _next_state, _delta = _examples_to_arrays(held_out)
    n_obs, state_dim = state.shape

    if name == "neural_sde":
        assert neural_model is not None and state_scaler is not None and regime_scaler is not None
        t = torch.tensor([[e.t_scaled] for e in held_out], dtype=torch.float32)
        x = torch.tensor(
            state_scaler.transform(np.array([e.state for e in held_out])), dtype=torch.float32
        )
        r = torch.tensor(
            regime_scaler.transform(np.array([e.regime for e in held_out])), dtype=torch.float32
        )
        neural_model.eval()
        with torch.no_grad():
            drift, sigma = neural_model(t, x, r)
        # The network operates entirely in state_scaler-NORMALIZED space
        # (training scales both sides of the residual identically, see
        # `training._examples_to_tensors`); drift/sigma must be mapped
        # back through the scaler's std before comparing against the
        # other candidates, which all predict in raw (percent) units.
        # next_state_raw = mean + std*(state_norm + drift*dt)
        #                = state_raw + std*drift*dt   (since
        #                  mean + std*state_norm == state_raw exactly)
        # Var(std*X_norm) = std Sigma_norm std^T elementwise-outer.
        std = np.array(state_scaler.std)
        mu = state + std * drift.numpy() * DT_SCALED
        std_outer = np.outer(std, std)
        sigma = sigma.numpy() * DT_SCALED * std_outer[None, :, :]
        return mu, sigma

    if name == "gbm_constant":
        mean, cov = fit_gbm_constant(train_examples)
        mu = state + mean[None, :]
        sigma = np.tile(cov[None, :, :], (n_obs, 1, 1))
        return mu, sigma

    if name == "persistence":
        _, _, train_delta = _examples_to_arrays(train_examples)
        cov = np.cov(train_delta.T) if state_dim > 1 else np.array([[train_delta.var()]])
        cov = cov + 1e-8 * np.eye(state_dim)
        mu = state.copy()
        sigma = np.tile(cov[None, :, :], (n_obs, 1, 1))
        return mu, sigma

    if name == "ar1_univariate":
        fits = fit_ar1(train_examples)
        mu = np.empty_like(state)
        sigma = np.zeros((n_obs, state_dim, state_dim))
        for d, (a, b, resid_std) in enumerate(fits):
            mu[:, d] = a + b * state[:, d]
            sigma[:, d, d] = resid_std**2
        return mu, sigma

    if name == "garch_univariate":
        _, _, train_delta = _examples_to_arrays(train_examples)
        _, _, held_out_delta = _examples_to_arrays(held_out)
        garch = fit_garch11(train_delta[:, 0])
        # `held_out` is a chronologically contiguous continuation of
        # `train_examples` (both come from `chronological_split`), so the
        # concatenated delta sequence is the correct order to recursively
        # filter h_t through; only the held-out tail is scored.
        all_returns = np.concatenate([train_delta[:, 0], held_out_delta[:, 0]])
        variances = garch.conditional_variances(all_returns)[-n_obs:]
        mu = state.copy()
        mu[:, 0] = state[:, 0] + garch.mu
        sigma = np.zeros((n_obs, state_dim, state_dim))
        sigma[:, 0, 0] = np.clip(variances, 1e-8, None)
        if state_dim > 1:
            fallback_var = float(np.var(train_delta[:, 1:], axis=0).mean()) + 1e-8
            for d in range(1, state_dim):
                sigma[:, d, d] = fallback_var
        return mu, sigma

    raise ValueError(f"unknown candidate {name!r}")


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    candidate_names: tuple[str, ...]
    log_score: dict[str, float]
    crps: dict[str, dict[str, float]]
    n_held_out: int


def benchmark_report(
    held_out: list[TransitionExample],
    train_examples: list[TransitionExample],
    neural_model: DriftDiffusionNet,
    state_scaler: FittedScaler,
    regime_scaler: FittedScaler,
) -> BenchmarkReport:
    _state, next_state, _delta = _examples_to_arrays(held_out)
    log_scores: dict[str, float] = {}
    crps_reports: dict[str, dict[str, float]] = {}
    for name in CANDIDATE_NAMES:
        mu, sigma = predict_candidate(
            name,
            held_out,
            train_examples,
            neural_model=neural_model,
            state_scaler=state_scaler,
            regime_scaler=regime_scaler,
        )
        log_scores[name] = gaussian_log_score(mu, sigma, next_state)
        sigma_diag = np.stack([np.diag(sigma[i]) for i in range(sigma.shape[0])])
        crps_reports[name] = marginal_crps_report(mu, sigma_diag, next_state)
    return BenchmarkReport(
        candidate_names=CANDIDATE_NAMES,
        log_score=log_scores,
        crps=crps_reports,
        n_held_out=len(held_out),
    )


@dataclass(frozen=True, slots=True)
class SensitivityReport:
    seeds: tuple[int, ...]
    schemes: tuple[str, ...]
    terminal_mean_by_scheme: dict[str, float]
    terminal_std_across_seeds_by_scheme: dict[str, float]
    terminal_std_across_schemes_at_matched_seed: float


def multi_seed_multi_solver_sensitivity(
    model: DriftDiffusionNet,
    x0: torch.Tensor,
    regime_path: torch.Tensor,
    seeds: tuple[int, ...] = (0, 1, 2, 3, 4),
    dt_scaled: float = DT_SCALED,
) -> SensitivityReport:
    model.eval()
    schemes = {
        "euler_maruyama": simulate_euler_maruyama,
        "stochastic_heun": simulate_stochastic_heun,
    }
    terminal_values: dict[str, list[float]] = {name: [] for name in schemes}
    with torch.no_grad():
        for seed in seeds:
            for scheme_name, scheme_fn in schemes.items():
                generator = torch.Generator().manual_seed(seed)
                path = scheme_fn(model, x0, 0.0, dt_scaled, regime_path, generator)
                terminal_values[scheme_name].append(float(path[0, -1, 0].item()))

    terminal_mean_by_scheme = {name: float(np.mean(vals)) for name, vals in terminal_values.items()}
    terminal_std_by_scheme = {name: float(np.std(vals)) for name, vals in terminal_values.items()}
    matched_seed_diffs = [
        terminal_values["euler_maruyama"][i] - terminal_values["stochastic_heun"][i]
        for i in range(len(seeds))
    ]
    return SensitivityReport(
        seeds=seeds,
        schemes=tuple(schemes),
        terminal_mean_by_scheme=terminal_mean_by_scheme,
        terminal_std_across_seeds_by_scheme=terminal_std_by_scheme,
        terminal_std_across_schemes_at_matched_seed=float(np.std(matched_seed_diffs)),
    )
