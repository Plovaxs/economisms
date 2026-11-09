"""PDE-06: deep BSDE solver (Han/E/Jentzen 2017/2018 scheme), with a
genuine multi-asset extension (`BasketOptionPDESpec`) that `grid.py`
cannot reach at all -- the actual point of this method.

By Feynman-Kac, V(t, X_t) solving

    V_t + L V - r*V = 0,   V(T, x) = payoff(x)

(L the generator of the risk-neutral diffusion X_t, i.e. the same
correlated-GBM process `stochastica.gbm.simulate_correlated_gbm_paths`
draws) equals Y_t in the backward SDE

    dY_t = r*Y_t*dt + Z_t . dW_t,   Y_T = payoff(X_T)

(substituting f(t,x,y,z) = -r*y into the general BSDE
V_t + L V + f = 0 form). This module represents Y_0 as a trainable
scalar and Z_t at each discrete time step as the output of a SEPARATE
small subnetwork for that step -- "causal" in the literal sense that
step n's subnetwork never sees X at any step > n, matching the
original paper's architecture (one subnetwork per time step, not one
recurrent network reused across steps) -- then rolls the BSDE forward
along simulated paths of X_t and trains both Y_0 and every Z-subnetwork
jointly by minimizing (Y_T - payoff(X_T))^2, the terminal condition.
No PDE residual, no grid: the entire PDE is encoded in how the forward
simulation and backward recursion are built.

For d=1 this reduces to the SAME scalar BS PDE `grid.py` and `pinn.py`
solve, and `Y_0` is checked against the closed-form price. For d>=2 it
runs on a basket option where NEITHER a closed form NOR `grid.py`'s
finite-difference method (see `benchmark.grid_node_count`) is
available -- `_basket_monte_carlo_price` (plain, un-learned Monte Carlo
averaging of the discounted basket payoff) is the independent ground
truth used instead, the same kind of "simulate many paths and average"
check that `volterra.monte_carlo` already uses for single-asset
options.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
import torch
from torch import nn

from prometheus.pde_solvers.problem import BasketOptionPDESpec
from prometheus.quantum.models import count_parameters
from prometheus.stochastica.correlated import correlated_normal_draws


def _simulate_risk_neutral_paths(
    spec: BasketOptionPDESpec,
    s0: np.ndarray,
    *,
    n_time: int,
    n_paths: int,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray]:
    """Exact lognormal stepping (no Euler discretization bias) of the
    SAME correlated-GBM process `stochastica.gbm.simulate_correlated_
    gbm_paths` draws, reimplemented here (rather than called directly)
    because the BSDE recursion needs the raw per-step Brownian
    increments `dW` alongside the paths, which that function does not
    return. Returns (paths, dW) with paths.shape == (n_paths,
    n_time+1, n_assets) and dW.shape == (n_paths, n_time, n_assets)."""
    n_assets = spec.n_assets
    dt = spec.maturity / n_time
    sigma = np.asarray(spec.volatilities, dtype=float)
    corr = np.asarray(spec.correlation, dtype=float)

    paths = np.empty((n_paths, n_time + 1, n_assets))
    dw = np.empty((n_paths, n_time, n_assets))
    paths[:, 0, :] = s0
    log_s = np.log(s0) * np.ones((n_paths, n_assets))
    for step in range(n_time):
        z = correlated_normal_draws(rng, n_paths, corr)
        increment = sigma * np.sqrt(dt) * z
        dw[:, step, :] = increment
        log_s = log_s + (spec.risk_free_rate - 0.5 * sigma**2) * dt + increment
        paths[:, step + 1, :] = np.exp(log_s)
    if not np.all(np.isfinite(paths)):
        raise ValueError(
            f"risk-neutral path simulation overflowed for spec={spec} -- "
            "this parameter combination has no computable answer under float64"
        )
    return paths, dw


def _basket_monte_carlo_price(
    spec: BasketOptionPDESpec, s0: np.ndarray, *, n_time: int, n_paths: int, seed: int
) -> float:
    """Independent ground truth for d>=2: plain (un-learned) Monte
    Carlo -- simulate, average the discounted payoff -- with no neural
    network anywhere in the estimate."""
    rng = np.random.default_rng(seed)
    paths, _ = _simulate_risk_neutral_paths(spec, s0, n_time=n_time, n_paths=n_paths, rng=rng)
    payoff = spec.payoff(paths[:, -1, :])
    discounted = np.exp(-spec.risk_free_rate * spec.maturity) * payoff
    return float(discounted.mean())


class _ZNet(nn.Module):
    """One per time step -- this step's subnetwork never sees X at any
    other step, which is what makes the rollout below causal."""

    def __init__(self, n_assets: int, hidden: int) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(n_assets, hidden),
            nn.ReLU(),
            nn.Linear(hidden, hidden),
            nn.ReLU(),
            nn.Linear(hidden, n_assets),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out: torch.Tensor = self.net(x)
        return out


class DeepBSDENet(nn.Module):
    def __init__(self, n_assets: int, n_time: int, hidden: int = 16) -> None:
        super().__init__()
        self.y0 = nn.Parameter(torch.tensor(1.0))
        self.z_nets = nn.ModuleList([_ZNet(n_assets, hidden) for _ in range(n_time)])
        self.n_assets = n_assets
        self.n_time = n_time

    def rollout(
        self, paths_normalized: torch.Tensor, dw: torch.Tensor, dt: float, risk_free_rate: float
    ) -> torch.Tensor:
        """paths_normalized: (n_paths, n_time+1, n_assets), already
        scaled to O(1) for subnetwork input stability. dw: (n_paths,
        n_time, n_assets), the RAW (unnormalized) Brownian increments
        the BSDE recursion itself needs. Returns Y_T, shape
        (n_paths,)."""
        n_paths = paths_normalized.shape[0]
        y = self.y0.expand(n_paths).clone()
        for step in range(self.n_time):
            z = self.z_nets[step](paths_normalized[:, step, :])
            y = y + risk_free_rate * y * dt + (z * dw[:, step, :]).sum(dim=-1)
        return y


@dataclass(frozen=True, slots=True)
class DeepBSDEEpochLog:
    epoch: int
    terminal_loss: float


@dataclass(frozen=True, slots=True)
class DeepBSDEDiagnostics:
    epoch_log: tuple[DeepBSDEEpochLog, ...]
    seed: int
    n_parameters: int
    train_seconds: float
    final_terminal_rmse: float


@dataclass(frozen=True, slots=True)
class DeepBSDEResult:
    price: float
    """The trained Y_0 -- the model's estimate of V(0, s0)."""
    delta_estimate: float | None
    """Only populated for a single-asset spec. The known Deep-BSDE
    identity is Z_t = sigma*S_t*Delta(t,S_t) for constant scalar
    volatility (Z_t being the coefficient of the TRUE driving Brownian
    motion dW_t, where dW_t = sqrt(dt)*N(0,1)). This module's `dw`
    array is sigma*dW_t, not dW_t itself (see
    `_simulate_risk_neutral_paths`'s docstring) -- the z-subnetwork's
    raw output is therefore already Z_t/sigma, so recovering Delta
    only needs dividing by S_0, NOT by sigma*S_0 (confirmed directly:
    an earlier version of this formula divided by sigma*S_0 too, and
    was off by exactly the expected factor of 1/sigma on every test
    case). Deliberately None for a basket spec -- generalizing this
    identity to a correlated multi-asset diffusion is not something
    this module claims to have validated, so it is not reported rather
    than guessed at."""
    diagnostics: DeepBSDEDiagnostics


def train_deep_bsde(
    spec: BasketOptionPDESpec,
    s0: np.ndarray,
    *,
    seed: int,
    n_time: int,
    n_paths: int,
    n_epochs: int,
    hidden: int = 16,
    learning_rate: float = 5e-2,
) -> DeepBSDEResult:
    s0 = np.asarray(s0, dtype=float)
    if s0.shape != (spec.n_assets,):
        raise ValueError(f"s0 must have shape ({spec.n_assets},), got {s0.shape}")
    if n_time < 1:
        raise ValueError("n_time must be >= 1")
    if n_paths < 1:
        raise ValueError("n_paths must be >= 1")
    if n_epochs < 1:
        raise ValueError("n_epochs must be >= 1")

    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    net = DeepBSDENet(spec.n_assets, n_time, hidden=hidden)
    optimizer = torch.optim.Adam(net.parameters(), lr=learning_rate)
    dt = spec.maturity / n_time

    epoch_log: list[DeepBSDEEpochLog] = []
    start = time.perf_counter()
    for epoch in range(n_epochs):
        paths, dw = _simulate_risk_neutral_paths(spec, s0, n_time=n_time, n_paths=n_paths, rng=rng)
        paths_t = torch.as_tensor(paths, dtype=torch.float32)
        paths_normalized = paths_t / torch.as_tensor(s0, dtype=torch.float32)
        dw_t = torch.as_tensor(dw, dtype=torch.float32)

        optimizer.zero_grad()
        y_terminal = net.rollout(paths_normalized, dw_t, dt, spec.risk_free_rate)
        target = torch.as_tensor(spec.payoff(paths[:, -1, :]), dtype=torch.float32)
        loss = torch.mean((y_terminal - target) ** 2)
        loss.backward()  # type: ignore[no-untyped-call]
        optimizer.step()

        epoch_log.append(DeepBSDEEpochLog(epoch=epoch, terminal_loss=float(loss.item())))
    train_seconds = time.perf_counter() - start

    with torch.no_grad():
        final_paths, final_dw = _simulate_risk_neutral_paths(
            spec, s0, n_time=n_time, n_paths=max(n_paths, 2000), rng=rng
        )
        final_paths_t = torch.as_tensor(final_paths, dtype=torch.float32)
        final_paths_normalized = final_paths_t / torch.as_tensor(s0, dtype=torch.float32)
        final_dw_t = torch.as_tensor(final_dw, dtype=torch.float32)
        final_y_terminal = net.rollout(final_paths_normalized, final_dw_t, dt, spec.risk_free_rate)
        final_target = torch.as_tensor(spec.payoff(final_paths[:, -1, :]), dtype=torch.float32)
        final_rmse = float(torch.sqrt(torch.mean((final_y_terminal - final_target) ** 2)).item())

        price = float(net.y0.item())
        delta_estimate: float | None = None
        if spec.n_assets == 1:
            s0_normalized = torch.as_tensor(s0, dtype=torch.float32) / torch.as_tensor(
                s0, dtype=torch.float32
            )
            z0 = net.z_nets[0](s0_normalized.unsqueeze(0)).squeeze(0)
            delta_estimate = float(z0.item()) / s0[0]

    diagnostics = DeepBSDEDiagnostics(
        epoch_log=tuple(epoch_log),
        seed=seed,
        n_parameters=count_parameters(net),
        train_seconds=train_seconds,
        final_terminal_rmse=final_rmse,
    )
    return DeepBSDEResult(price=price, delta_estimate=delta_estimate, diagnostics=diagnostics)
