"""Mesh-free neural solvers for PDEs and variational problems, each checked against an answer that
is
known exactly or computed by a classical method.

* **DGM**, the Deep Galerkin Method (Sirignano and Spiliopoulos 2018): a recurrent-gate network
  trained so that the PDE residual, the terminal condition and the boundary conditions all vanish at
  randomly drawn points. Used here for the Black-Scholes put, where the closed form is the truth,
  and
  for the *American* put, a free-boundary problem written as the variational inequality
  `min(-(V_t + L V), V - payoff) = 0`, where a binomial tree is the reference.
* **Deep Ritz** (E and Yu 2018): minimise the energy functional of an elliptic problem directly,
  `integral of 0.5 |grad u|^2 - f u`, with the boundary condition as a penalty. Used on the Poisson
  problem on the unit square with the exact solution sin(pi x) sin(pi y); a five-point
  finite-difference
  solve is the classical competitor.
* **Deep Kolmogorov** (Beck, Jentzen and E 2019): the value `u(x) = E[payoff(X_T^x)]` of a linear
  Kolmogorov PDE is the regression of the payoff on the start point, so a network fitted to
  simulated
  `(x, payoff)` pairs over a box of start points solves the PDE for all of them at once. Used on an
  option on the geometric mean of `d` assets, which has an exact price in every dimension; a plain
  Monte Carlo is the competitor.

All three use K = 1 (prices are in units of the strike), r = 5% and sigma = 20%.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
import torch
from scipy.sparse import diags, identity, kron
from scipy.sparse.linalg import spsolve
from scipy.stats import norm
from torch import nn

from prometheus.volterra.american_options import american_binomial_price
from prometheus.volterra.instruments import AmericanOption
from prometheus.volterra.market import MarketSnapshot

RATE = 0.05
SIGMA = 0.2
MATURITY = 1.0
STRIKE = 1.0
S_MAX = 3.0


def bs_put(spot: np.ndarray, tau: float = MATURITY) -> np.ndarray:
    spot = np.asarray(spot, float)
    vol = SIGMA * math.sqrt(tau)
    d1 = (np.log(spot / STRIKE) + (RATE + 0.5 * SIGMA**2) * tau) / vol
    d2 = d1 - vol
    return np.asarray(
        STRIKE * math.exp(-RATE * tau) * norm.cdf(-d2) - spot * norm.cdf(-d1), dtype=float
    )


# ----- DGM ----------------------------------------------------------------------------------------


class _DGMLayer(nn.Module):
    """One DGM block: update, transform, reset and candidate gates on the input and the state."""

    def __init__(self, in_dim: int, width: int) -> None:
        super().__init__()
        self.uz = nn.Linear(in_dim, width, bias=False)
        self.ug = nn.Linear(in_dim, width, bias=False)
        self.ur = nn.Linear(in_dim, width, bias=False)
        self.uh = nn.Linear(in_dim, width, bias=False)
        self.wz = nn.Linear(width, width)
        self.wg = nn.Linear(width, width)
        self.wr = nn.Linear(width, width)
        self.wh = nn.Linear(width, width)

    def forward(self, x: torch.Tensor, first: torch.Tensor, state: torch.Tensor) -> torch.Tensor:
        z = torch.tanh(self.uz(x) + self.wz(state))
        g = torch.tanh(self.ug(x) + self.wg(first))
        r = torch.tanh(self.ur(x) + self.wr(state))
        h = torch.tanh(self.uh(x) + self.wh(state * r))
        out: torch.Tensor = (1.0 - g) * h + z * state
        return out


class DGMNet(nn.Module):
    def __init__(self, in_dim: int = 2, width: int = 32, layers: int = 3) -> None:
        super().__init__()
        self.first = nn.Linear(in_dim, width)
        self.blocks = nn.ModuleList(_DGMLayer(in_dim, width) for _ in range(layers))
        self.out = nn.Linear(width, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        first = torch.tanh(self.first(x))
        state = first
        for block in self.blocks:
            state = block(x, first, state)
        out: torch.Tensor = self.out(state).squeeze(-1)
        return out


def _bs_operator(
    net: nn.Module, t: torch.Tensor, s: torch.Tensor
) -> tuple[torch.Tensor, torch.Tensor]:
    """Return V and V_t + 0.5 sigma^2 S^2 V_SS + r S V_S - r V at the points (t, S)."""
    t = t.clone().requires_grad_(True)
    s = s.clone().requires_grad_(True)
    v = net(torch.stack([t, s], dim=-1))
    v_t, v_s = torch.autograd.grad(v.sum(), (t, s), create_graph=True)
    (v_ss,) = torch.autograd.grad(v_s.sum(), s, create_graph=True)
    return v, v_t + 0.5 * SIGMA**2 * s**2 * v_ss + RATE * s * v_s - RATE * v


@dataclass(frozen=True, slots=True)
class DGMResult:
    net: DGMNet
    seconds: float
    final_loss: float


def train_dgm(
    *, american: bool, steps: int, seed: int, batch: int = 512, lr: float = 2e-3
) -> DGMResult:
    torch.manual_seed(seed)
    generator = torch.Generator().manual_seed(seed)
    net = DGMNet()
    optimiser = torch.optim.Adam(net.parameters(), lr=lr)
    schedule = torch.optim.lr_scheduler.CosineAnnealingLR(optimiser, T_max=steps)
    start = time.perf_counter()
    loss_value = float("nan")
    for _ in range(steps):
        t = MATURITY * torch.rand(batch, generator=generator)
        s = S_MAX * torch.rand(batch, generator=generator)
        v, residual = _bs_operator(net, t, s)
        payoff = torch.clamp(STRIKE - s, min=0.0)
        if american:
            interior = torch.minimum(-residual, v - payoff)
        else:
            interior = residual
        s_term = S_MAX * torch.rand(batch // 2, generator=generator)
        terminal = net(
            torch.stack([torch.full_like(s_term, MATURITY), s_term], dim=-1)
        ) - torch.clamp(STRIKE - s_term, min=0.0)
        t_edge = MATURITY * torch.rand(batch // 4, generator=generator)
        lower = net(torch.stack([t_edge, torch.zeros_like(t_edge)], dim=-1))
        lower_true = (
            torch.full_like(t_edge, STRIKE)
            if american
            else STRIKE * torch.exp(-RATE * (MATURITY - t_edge))
        )
        upper = net(torch.stack([t_edge, torch.full_like(t_edge, S_MAX)], dim=-1))
        loss = (
            (interior**2).mean()
            + 10.0 * (terminal**2).mean()
            + 10.0 * ((lower - lower_true) ** 2).mean()
            + 10.0 * (upper**2).mean()
        )
        optimiser.zero_grad()
        loss.backward()
        optimiser.step()
        schedule.step()
        loss_value = float(loss.detach())
    return DGMResult(net, time.perf_counter() - start, loss_value)


def dgm_value(net: DGMNet, spots: np.ndarray) -> np.ndarray:
    """Value at t = 0 (full maturity remaining)."""
    with torch.no_grad():
        x = torch.stack(
            [torch.zeros(len(spots)), torch.as_tensor(spots, dtype=torch.float32)], dim=-1
        )
        return np.asarray(net(x).numpy(), dtype=float)


def american_put_reference(spots: np.ndarray, steps: int = 1000) -> np.ndarray:
    option = AmericanOption(strike=STRIKE, maturity=MATURITY, option_type="put")
    return np.array(
        [
            american_binomial_price(
                MarketSnapshot(
                    as_of=date(2024, 1, 1), spot=float(s), risk_free_rate=RATE, volatility=SIGMA
                ),
                option,
                steps,
            )
            for s in spots
        ]
    )


# ----- Deep Ritz ----------------------------------------------------------------------------------


class RitzNet(nn.Module):
    def __init__(self, width: int = 32, blocks: int = 3) -> None:
        super().__init__()
        self.inp = nn.Linear(2, width)
        self.blocks = nn.ModuleList(
            nn.Sequential(nn.Linear(width, width), nn.Tanh(), nn.Linear(width, width), nn.Tanh())
            for _ in range(blocks)
        )
        self.out = nn.Linear(width, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        h = torch.tanh(self.inp(x))
        for block in self.blocks:
            h = h + block(h)
        out: torch.Tensor = self.out(h).squeeze(-1)
        return out


def _poisson_source(x: torch.Tensor) -> torch.Tensor:
    return 2.0 * math.pi**2 * torch.sin(math.pi * x[:, 0]) * torch.sin(math.pi * x[:, 1])


@dataclass(frozen=True, slots=True)
class RitzResult:
    net: RitzNet
    seconds: float
    final_energy: float


def train_deep_ritz(
    *, steps: int, seed: int, batch: int = 1024, penalty: float = 500.0, lr: float = 2e-3
) -> RitzResult:
    torch.manual_seed(seed)
    generator = torch.Generator().manual_seed(seed)
    net = RitzNet()
    optimiser = torch.optim.Adam(net.parameters(), lr=lr)
    schedule = torch.optim.lr_scheduler.CosineAnnealingLR(optimiser, T_max=steps)
    start = time.perf_counter()
    energy_value = float("nan")
    for _ in range(steps):
        x = torch.rand(batch, 2, generator=generator).requires_grad_(True)
        u = net(x)
        (grad,) = torch.autograd.grad(u.sum(), x, create_graph=True)
        energy = (0.5 * (grad**2).sum(-1) - _poisson_source(x) * u).mean()
        side = torch.rand(batch // 4, generator=generator)
        zeros, ones = torch.zeros_like(side), torch.ones_like(side)
        edge = torch.cat(
            [
                torch.stack([side, zeros], -1),
                torch.stack([side, ones], -1),
                torch.stack([zeros, side], -1),
                torch.stack([ones, side], -1),
            ]
        )
        loss = energy + penalty * (net(edge) ** 2).mean()
        optimiser.zero_grad()
        loss.backward()
        optimiser.step()
        schedule.step()
        energy_value = float(energy.detach())
    return RitzResult(net, time.perf_counter() - start, energy_value)


def poisson_exact(x: np.ndarray) -> np.ndarray:
    return np.asarray(np.sin(math.pi * x[:, 0]) * np.sin(math.pi * x[:, 1]), dtype=float)


def poisson_finite_difference(n: int) -> tuple[np.ndarray, np.ndarray]:
    """Five-point solve of -Laplacian u = f on the unit square with n interior points per side."""
    h = 1.0 / (n + 1)
    lap_1d = diags([-1.0, 2.0, -1.0], [-1, 0, 1], shape=(n, n)) / h**2
    lap: Any = kron(lap_1d, identity(n)) + kron(identity(n), lap_1d)
    grid = np.arange(1, n + 1) * h
    gx, gy = np.meshgrid(grid, grid, indexing="ij")
    f = 2.0 * math.pi**2 * np.sin(math.pi * gx) * np.sin(math.pi * gy)
    u = spsolve(lap.tocsc(), f.ravel())
    points = np.stack([gx.ravel(), gy.ravel()], axis=1)
    return points, np.asarray(u, dtype=float)


def relative_l2_error(pred: np.ndarray, truth: np.ndarray) -> float:
    return float(np.linalg.norm(pred - truth) / np.linalg.norm(truth))


# ----- Deep Kolmogorov ----------------------------------------------------------------------------


def geometric_basket_price(x: np.ndarray) -> np.ndarray:
    """Exact price of exp(-rT) (G_T - K)+ with G the geometric mean of d independent GBMs
    started at x."""
    d = x.shape[1]
    vol_g = SIGMA / math.sqrt(d)
    mu = np.log(x).mean(axis=1) + (RATE - 0.5 * SIGMA**2) * MATURITY
    forward = np.exp(mu + 0.5 * vol_g**2 * MATURITY)
    sd = vol_g * math.sqrt(MATURITY)
    d1 = (np.log(forward / STRIKE) + 0.5 * sd**2) / sd
    d2 = d1 - sd
    return np.asarray(
        math.exp(-RATE * MATURITY) * (forward * norm.cdf(d1) - STRIKE * norm.cdf(d2)), dtype=float
    )


def simulate_payoff(x: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    d = x.shape[1]
    z = rng.standard_normal(x.shape)
    log_g = (
        np.log(x).mean(axis=1)
        + (RATE - 0.5 * SIGMA**2) * MATURITY
        + SIGMA * math.sqrt(MATURITY) * z.mean(axis=1)
    )
    del d
    return np.asarray(
        math.exp(-RATE * MATURITY) * np.maximum(np.exp(log_g) - STRIKE, 0.0), dtype=float
    )


@dataclass(frozen=True, slots=True)
class KolmogorovResult:
    net: nn.Module
    seconds: float
    samples_used: int


def train_deep_kolmogorov(
    dimension: int, *, steps: int, seed: int, batch: int = 512, width: int = 64, lr: float = 2e-3
) -> KolmogorovResult:
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    net = nn.Sequential(
        nn.Linear(dimension, width),
        nn.GELU(),
        nn.Linear(width, width),
        nn.GELU(),
        nn.Linear(width, width),
        nn.GELU(),
        nn.Linear(width, 1),
    )
    optimiser = torch.optim.Adam(net.parameters(), lr=lr)
    schedule = torch.optim.lr_scheduler.CosineAnnealingLR(optimiser, T_max=steps)
    start = time.perf_counter()
    for _ in range(steps):
        x = rng.uniform(0.7, 1.3, size=(batch, dimension))
        y = simulate_payoff(x, rng)
        pred = net(torch.as_tensor(x, dtype=torch.float32)).squeeze(-1)
        loss = ((pred - torch.as_tensor(y, dtype=torch.float32)) ** 2).mean()
        optimiser.zero_grad()
        loss.backward()
        optimiser.step()
        schedule.step()
    return KolmogorovResult(net, time.perf_counter() - start, steps * batch)


def kolmogorov_test_points(dimension: int, n: int, seed: int) -> np.ndarray:
    return np.random.default_rng(seed).uniform(0.85, 1.15, size=(n, dimension))


def kolmogorov_predict(result: KolmogorovResult, x: np.ndarray) -> np.ndarray:
    with torch.no_grad():
        return np.asarray(
            result.net(torch.as_tensor(x, dtype=torch.float32)).squeeze(-1).numpy(), dtype=float
        )


def monte_carlo_estimate(x: np.ndarray, samples_per_point: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    out = np.empty(len(x))
    for i, point in enumerate(x):
        out[i] = simulate_payoff(np.tile(point, (samples_per_point, 1)), rng).mean()
    return out
