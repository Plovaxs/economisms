"""NSD-02: "Implement differentiable stochastic integration path --
Autograd gradient finite and numerically consistent on toy cases."

Two independent Euler-Maruyama-family schemes are implemented (not one
scheme run at two step sizes) so NSD-10's "multi-seed, multi-solver
sensitivity study" has a genuine second solver to compare against, not
just a second random seed of the same one:

- `simulate_euler_maruyama`: the standard explicit scheme, X_{t+dt} =
  X_t + mu(t, X_t)*dt + L(t, X_t) @ sqrt(dt)*Z.
- `simulate_stochastic_heun`: a predictor-corrector (Heun/trapezoidal)
  scheme -- an Euler predictor step, then the DRIFT only is corrected by
  averaging mu evaluated at the start and predicted-end points (the
  diffusion increment is reused unchanged from the predictor, the usual
  simplification for a stochastic Heun scheme -- correcting the
  diffusion term too would require a second, correlated noise draw and
  is not attempted here).

Both are written entirely in differentiable torch ops (no `.detach()`,
no `.item()` inside the integration loop) so `loss.backward()` after
simulating a path propagates gradients all the way back through every
step to the network's parameters -- this is what "differentiable
stochastic integration path" means, and is exactly what
`test_neural_sde_integration.py` checks via `torch.autograd.gradcheck`
on a toy low-dimensional case (gradcheck requires float64, so the toy
check runs the model in double precision; the full package otherwise
uses float32 throughout, matching every other torch model in this
repository, e.g. `recessionnet`).
"""

from __future__ import annotations

import torch

from prometheus.neural_sde.model import DriftDiffusionNet


def _reject_non_finite(x: torch.Tensor, context: str) -> None:
    if not torch.all(torch.isfinite(x)):
        raise ValueError(f"{context}: produced a non-finite value")


def simulate_euler_maruyama(
    model: DriftDiffusionNet,
    x0: torch.Tensor,
    t0_scaled: float,
    dt_scaled: float,
    regime_path: torch.Tensor,
    generator: torch.Generator,
) -> torch.Tensor:
    """x0: (n_paths, state_dim). regime_path: (n_steps, regime_dim) --
    one exogenous regime-feature row per step, shared across paths (the
    regime process is observed/exogenous, not itself simulated). Returns
    (n_paths, n_steps + 1, state_dim); column 0 is x0."""
    n_paths, state_dim = x0.shape
    n_steps = regime_path.shape[0]
    if state_dim != model.state_dim:
        raise ValueError("x0's trailing dimension must match model.state_dim")
    if dt_scaled <= 0:
        raise ValueError("dt_scaled must be positive")

    path = [x0]
    x = x0
    t_scaled = t0_scaled
    sqrt_dt = dt_scaled**0.5
    for step in range(n_steps):
        t_tensor = torch.full((n_paths, 1), t_scaled, dtype=x.dtype)
        regime = regime_path[step].unsqueeze(0).expand(n_paths, -1).to(x.dtype)
        drift, sigma = model(t_tensor, x, regime)
        chol = torch.linalg.cholesky(sigma + 1e-12 * torch.eye(state_dim, dtype=x.dtype))
        z = torch.randn(n_paths, state_dim, generator=generator, dtype=x.dtype)
        noise = torch.einsum("bij,bj->bi", chol, z) * sqrt_dt
        x = x + drift * dt_scaled + noise
        path.append(x)
        t_scaled += dt_scaled

    result = torch.stack(path, dim=1)
    _reject_non_finite(result, "simulate_euler_maruyama")
    return result


def simulate_stochastic_heun(
    model: DriftDiffusionNet,
    x0: torch.Tensor,
    t0_scaled: float,
    dt_scaled: float,
    regime_path: torch.Tensor,
    generator: torch.Generator,
) -> torch.Tensor:
    """Predictor-corrector variant of `simulate_euler_maruyama`: drift is
    averaged between the start-of-step and predicted end-of-step
    evaluations; the diffusion increment is drawn once per step (from
    the predictor's Sigma) and reused for the corrector, not redrawn."""
    n_paths, state_dim = x0.shape
    n_steps = regime_path.shape[0]
    if state_dim != model.state_dim:
        raise ValueError("x0's trailing dimension must match model.state_dim")
    if dt_scaled <= 0:
        raise ValueError("dt_scaled must be positive")

    path = [x0]
    x = x0
    t_scaled = t0_scaled
    sqrt_dt = dt_scaled**0.5
    for step in range(n_steps):
        regime = regime_path[step].unsqueeze(0).expand(n_paths, -1).to(x.dtype)
        t_tensor = torch.full((n_paths, 1), t_scaled, dtype=x.dtype)
        drift0, sigma0 = model(t_tensor, x, regime)
        chol0 = torch.linalg.cholesky(sigma0 + 1e-12 * torch.eye(state_dim, dtype=x.dtype))
        z = torch.randn(n_paths, state_dim, generator=generator, dtype=x.dtype)
        noise = torch.einsum("bij,bj->bi", chol0, z) * sqrt_dt

        x_predict = x + drift0 * dt_scaled + noise
        t_next_tensor = torch.full((n_paths, 1), t_scaled + dt_scaled, dtype=x.dtype)
        drift1, _sigma1 = model(t_next_tensor, x_predict, regime)

        x = x + 0.5 * (drift0 + drift1) * dt_scaled + noise
        path.append(x)
        t_scaled += dt_scaled

    result = torch.stack(path, dim=1)
    _reject_non_finite(result, "simulate_stochastic_heun")
    return result
