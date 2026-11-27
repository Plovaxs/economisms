"""Deep Equilibrium Nets for a stochastic growth model, against the exact answer and a classical
solver.

The model is the workhorse of macroeconomics: a representative household chooses consumption to
maximise E sum beta^t u(c_t), output is y = z k^alpha + (1 - delta) k, and productivity follows
ln z' = rho ln z + sigma eps. The Euler equation

    u'(c) = beta E[ u'(c') (alpha z' k'^(alpha-1) + 1 - delta) ]

characterises the optimum. A **deep equilibrium net** (Maliar, Maliar and Winant 2021) parametrises
the policy (the savings rate as a function of capital and productivity) with a network and
minimises the
squared Euler residual over sampled states, with the expectation taken by Gauss-Hermite
quadrature. No
value function is needed.

Two cases:

* `closed_form` (log utility, full depreciation): the exact policy is a constant savings rate
alpha*beta,
  so the network's error is measured against the truth.
* `general` (CRRA gamma = 2, delta = 10%): no closed form; the classical competitor is
**value-function
  iteration** on a grid (Tauchen discretisation of the shock), and both policies are scored by their
  Euler-equation error, the standard accuracy measure in this literature (log10 of the relative
  residual; -3 is about a 0.1% mistake in consumption).
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Protocol

import numpy as np
import torch
from torch import nn

ALPHA = 0.36
BETA = 0.96
RHO = 0.9
SIGMA = 0.02


@dataclass(frozen=True, slots=True)
class Economy:
    gamma: float
    delta: float
    name: str

    @property
    def k_steady(self) -> float:
        return float(((1.0 / BETA - 1.0 + self.delta) / ALPHA) ** (1.0 / (ALPHA - 1.0)))

    @property
    def z_sd(self) -> float:
        return SIGMA / math.sqrt(1.0 - RHO**2)

    def utility_prime(self, c: torch.Tensor) -> torch.Tensor:
        return c ** (-self.gamma)

    def resources(self, k: torch.Tensor, z: torch.Tensor) -> torch.Tensor:
        return z * k**ALPHA + (1.0 - self.delta) * k


CLOSED_FORM = Economy(gamma=1.0, delta=1.0, name="closed_form")
GENERAL = Economy(gamma=2.0, delta=0.1, name="general")
ECONOMIES = {e.name: e for e in (CLOSED_FORM, GENERAL)}

_NODES, _WEIGHTS = np.polynomial.hermite.hermgauss(5)
HERMITE_NODES = torch.as_tensor(_NODES, dtype=torch.float32)
HERMITE_WEIGHTS = torch.as_tensor(_WEIGHTS / math.sqrt(math.pi), dtype=torch.float32)


class SavingsPolicy(Protocol):
    def savings_rate(self, k: torch.Tensor, log_z: torch.Tensor) -> torch.Tensor: ...


class PolicyNet(nn.Module):
    """Savings rate s(k, z) in (0, 1): next capital is s times resources."""

    def __init__(self, economy: Economy, width: int = 32) -> None:
        super().__init__()
        self.economy = economy
        self.net = nn.Sequential(
            nn.Linear(2, width), nn.Tanh(), nn.Linear(width, width), nn.Tanh(), nn.Linear(width, 1)
        )

    def savings_rate(self, k: torch.Tensor, log_z: torch.Tensor) -> torch.Tensor:
        features = torch.stack(
            [torch.log(k / self.economy.k_steady), log_z / self.economy.z_sd], -1
        )
        out: torch.Tensor = torch.sigmoid(self.net(features).squeeze(-1))
        return out


def euler_residual(
    economy: Economy, policy: SavingsPolicy, k: torch.Tensor, log_z: torch.Tensor
) -> torch.Tensor:
    """Relative Euler residual 1 - beta E[...] / u'(c) at the states (k, ln z)."""
    rate = policy.savings_rate
    z = torch.exp(log_z)
    resources = economy.resources(k, z)
    s = rate(k, log_z)
    c = (1.0 - s) * resources
    k_next = s * resources
    expectation = torch.zeros_like(k)
    for node, weight in zip(HERMITE_NODES, HERMITE_WEIGHTS, strict=True):
        log_z_next = RHO * log_z + SIGMA * math.sqrt(2.0) * node
        z_next = torch.exp(log_z_next)
        c_next = (1.0 - rate(k_next, log_z_next)) * economy.resources(k_next, z_next)
        gross = ALPHA * z_next * k_next ** (ALPHA - 1.0) + 1.0 - economy.delta
        expectation = expectation + weight * economy.utility_prime(c_next) * gross
    return 1.0 - BETA * expectation / economy.utility_prime(c)


@dataclass(frozen=True, slots=True)
class DEQResult:
    net: PolicyNet
    seconds: float
    final_loss: float


def sample_states(
    economy: Economy, n: int, generator: torch.Generator
) -> tuple[torch.Tensor, torch.Tensor]:
    k = economy.k_steady * (0.5 + torch.rand(n, generator=generator))
    log_z = (torch.rand(n, generator=generator) * 2.0 - 1.0) * 2.5 * economy.z_sd
    return k, log_z


def train_deq(
    economy: Economy, *, steps: int, seed: int, batch: int = 256, lr: float = 3e-3
) -> DEQResult:
    torch.manual_seed(seed)
    generator = torch.Generator().manual_seed(seed)
    net = PolicyNet(economy)
    optimiser = torch.optim.Adam(net.parameters(), lr=lr)
    schedule = torch.optim.lr_scheduler.CosineAnnealingLR(optimiser, T_max=steps)
    start = time.perf_counter()
    loss_value = float("nan")
    for _ in range(steps):
        k, log_z = sample_states(economy, batch, generator)
        loss = (euler_residual(economy, net, k, log_z) ** 2).mean()
        optimiser.zero_grad()
        loss.backward()  # type: ignore[no-untyped-call]
        optimiser.step()
        schedule.step()
        loss_value = float(loss.detach())
    return DEQResult(net, time.perf_counter() - start, loss_value)


# ----- the classical competitor: value-function iteration -----------------------------------------


@dataclass(frozen=True, slots=True)
class VFIPolicy:
    """A savings-rate policy read off a grid solution by bilinear interpolation (a classical
    solver)."""

    economy: Economy
    k_grid: np.ndarray
    z_grid: np.ndarray  # log-productivity states
    rate_table: np.ndarray  # (n_z, n_k)

    def savings_rate(self, k: torch.Tensor, log_z: torch.Tensor) -> torch.Tensor:
        kk = k.detach().numpy().astype(float)
        lz = log_z.detach().numpy().astype(float)
        out = np.empty_like(kk)
        for i in range(kk.size):
            j = np.interp(lz.flat[i], self.z_grid, np.arange(len(self.z_grid)))
            lo, hi = int(math.floor(j)), min(int(math.floor(j)) + 1, len(self.z_grid) - 1)
            frac = j - lo
            row_lo = np.interp(kk.flat[i], self.k_grid, self.rate_table[lo])
            row_hi = np.interp(kk.flat[i], self.k_grid, self.rate_table[hi])
            out.flat[i] = (1 - frac) * row_lo + frac * row_hi
        return torch.as_tensor(out, dtype=torch.float32)


def tauchen(n: int, span: float = 3.0) -> tuple[np.ndarray, np.ndarray]:
    from scipy.stats import norm

    sd = SIGMA / math.sqrt(1.0 - RHO**2)
    grid = np.linspace(-span * sd, span * sd, n)
    step = grid[1] - grid[0]
    trans = np.zeros((n, n))
    for i in range(n):
        mean = RHO * grid[i]
        trans[i, 0] = norm.cdf((grid[0] + step / 2 - mean) / SIGMA)
        trans[i, -1] = 1.0 - norm.cdf((grid[-1] - step / 2 - mean) / SIGMA)
        for j in range(1, n - 1):
            trans[i, j] = norm.cdf((grid[j] + step / 2 - mean) / SIGMA) - norm.cdf(
                (grid[j] - step / 2 - mean) / SIGMA
            )
    return grid, trans


def solve_vfi(
    economy: Economy, *, n_k: int = 200, n_z: int = 7, tolerance: float = 1e-8
) -> VFIPolicy:
    k_grid = np.linspace(0.3 * economy.k_steady, 1.8 * economy.k_steady, n_k)
    log_z, trans = tauchen(n_z)
    z = np.exp(log_z)
    resources = (
        z[:, None] * k_grid[None, :] ** ALPHA + (1 - economy.delta) * k_grid[None, :]
    )  # (z, k)
    gamma = economy.gamma

    def u(c: np.ndarray) -> np.ndarray:
        c = np.maximum(c, 1e-10)
        return np.log(c) if gamma == 1.0 else (c ** (1 - gamma) - 1) / (1 - gamma)

    value = np.zeros((n_z, n_k))
    choice = np.zeros((n_z, n_k), dtype=int)
    for _ in range(3000):
        expected = trans @ value  # (z, k') expected continuation value
        new_value = np.empty_like(value)
        for iz in range(n_z):
            consumption = resources[iz][:, None] - k_grid[None, :]  # (k, k')
            total = np.where(consumption > 0, u(consumption) + BETA * expected[iz][None, :], -1e10)
            choice[iz] = total.argmax(axis=1)
            new_value[iz] = total.max(axis=1)
        gap = float(np.abs(new_value - value).max())
        value = new_value
        if gap < tolerance:
            break
    rate = np.empty((n_z, n_k))
    for iz in range(n_z):
        rate[iz] = k_grid[choice[iz]] / resources[iz]
    return VFIPolicy(economy, k_grid, log_z, rate)


# ----- scoring ------------------------------------------------------------------------------------


def evaluation_states(economy: Economy, n: int, seed: int) -> tuple[torch.Tensor, torch.Tensor]:
    generator = torch.Generator().manual_seed(seed)
    k = economy.k_steady * (0.7 + 0.6 * torch.rand(n, generator=generator))
    log_z = (torch.rand(n, generator=generator) * 2.0 - 1.0) * 2.0 * economy.z_sd
    return k, log_z


def mean_log10_euler_error(
    economy: Economy, policy: SavingsPolicy, k: torch.Tensor, log_z: torch.Tensor
) -> float:
    with torch.no_grad():
        residual = euler_residual(economy, policy, k, log_z).abs().clamp(min=1e-12)
    return float(torch.log10(residual).mean())


def policy_values(policy: SavingsPolicy, k: torch.Tensor, log_z: torch.Tensor) -> np.ndarray:
    with torch.no_grad():
        return np.asarray(policy.savings_rate(k, log_z).numpy(), dtype=float)


def exact_savings_rate() -> float:
    """The closed-form policy of the log-utility, full-depreciation economy."""
    return ALPHA * BETA
