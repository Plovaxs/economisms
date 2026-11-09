"""PDE-03/04/05/11: a physics-informed neural network (PINN) solving
the same Black-Scholes PDE as `grid.py`, trained with NO labeled price
data at all -- only the PDE residual (PDE-03), the terminal payoff
condition (PDE-04) and the boundary conditions (PDE-05), each evaluated
at randomly sampled "collocation" points and driven to zero by
backpropagating through `torch.autograd.grad` (the PDE's own
derivatives, not a finite-difference approximation of them).

PDE-05's "applicable boundary and arbitrage constraints" turned out to
be two genuinely different things, found directly: training only the
TRUE domain-edge boundary conditions (S=0, S=s_max) leaves the network
free to violate the model-free no-arbitrage envelope (max(S -
K*exp(-r*tau), 0) <= call price <= S, and the put analogue -- these
hold under ANY arbitrage-free model, not just Black-Scholes) at
INTERIOR points; a first version of this module with no interior
penalty for that measured a 58% violation rate under
`PINNSolver.arbitrage_violation_rate`'s stress test. `train_pinn` now
adds an explicit hinge-loss `arbitrage_loss` term, evaluated at the
SAME interior collocation points already sampled for the PDE residual,
penalizing exactly the amount by which the envelope is violated. This
measurably trades off against price/Greeks accuracy (confirmed
directly: `arbitrage_weight=100` pushes the violation rate below 13%
but the price error past this package's own disclosed PDE-04/08
tolerance) -- `arbitrage_weight=50` is the point on that tradeoff this
module ships with, reducing the violation rate from 58% (no penalty)
to ~17-20% while keeping price/Delta/Gamma error within the SAME
tolerances already disclosed for the no-penalty case, not a loosened
bar. See test_pde_pinn.py::test_arbitrage_violation_rate_is_reduced_by_training
for the measured rate.

Inputs are normalized (t/T, S/strike) and the net's raw output is
rescaled by `strike` before use -- an unnormalized net sees S values up
to `s_max` (hundreds) and must learn curvature on that scale directly,
which trains far less reliably than learning an O(1) function (standard
PINN practice, e.g. Raissi/Perdikaris/Karniadakis 2019 section 3.1).

PDE-11 ("solver refuses false precision when residuals remain high"):
after training, `train_pinn` re-samples a FRESH, independent set of
interior collocation points (never seen during training) and computes
the residual RMS on them; if it exceeds `residual_tolerance`, this
raises `PDEResidualError` instead of returning a solver whose quoted
price nobody should trust -- see `test_pde_pinn.py::
test_too_few_epochs_raises_residual_error` for the deliberately
under-trained case that exercises this path, and
test_well_trained_model_does_not_raise for the normal path.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
import torch
from torch import nn

from prometheus.pde_solvers.problem import BlackScholesPDESpec
from prometheus.quantum.models import count_parameters


class PDEResidualError(RuntimeError):
    """Raised by `train_pinn` when the trained network's PDE residual,
    measured on FRESH collocation points, is still above
    `residual_tolerance` -- this project does not return a solver that
    claims precision it has not earned (PDE-11)."""


@dataclass(frozen=True, slots=True)
class PINNEpochLog:
    epoch: int
    interior_loss: float
    terminal_loss: float
    boundary_loss: float
    arbitrage_loss: float
    total_loss: float


@dataclass(frozen=True, slots=True)
class PINNDiagnostics:
    epoch_log: tuple[PINNEpochLog, ...]
    seed: int
    n_parameters: int
    train_seconds: float
    final_interior_residual_rms: float
    """RMS of the PDE residual on a FRESH, held-out set of collocation
    points -- not the training set -- the number `residual_tolerance`
    is checked against."""
    interior_points_sample: np.ndarray
    """The (t, s) collocation points sampled for the FIRST training
    epoch, shape (n_interior, 2) -- fixed by `seed`, so re-running
    `train_pinn` with the same seed reproduces this array exactly
    (PDE-03's "sampling distribution reproducible")."""


class _PINNNet(nn.Module):
    def __init__(self, *, hidden: int = 50, n_layers: int = 3) -> None:
        super().__init__()
        layers: list[nn.Module] = [nn.Linear(2, hidden), nn.Tanh()]
        for _ in range(n_layers - 1):
            layers += [nn.Linear(hidden, hidden), nn.Tanh()]
        layers += [nn.Linear(hidden, 1)]
        self.net = nn.Sequential(*layers)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out: torch.Tensor = self.net(x)
        return out.squeeze(-1)


def _price_from_net(
    net: _PINNNet, spec: BlackScholesPDESpec, t: torch.Tensor, s: torch.Tensor
) -> torch.Tensor:
    """Normalizes both inputs to roughly [0, 1] (t/T, S/s_max) before
    the net sees them, and rescales its raw output by `strike` back to
    price units -- an unnormalized net that has to learn curvature on
    S values in the hundreds trains far less reliably (confirmed
    directly: an earlier S/strike normalization, which still leaves S
    up to `s_max_multiple`, converged to a ~5x larger price error than
    S/s_max at an identical epoch budget)."""
    t_n = t / spec.maturity
    s_n = s / spec.s_max
    x = torch.stack([t_n, s_n], dim=-1)
    raw: torch.Tensor = net(x)
    return raw * spec.strike


def _pde_residual(
    net: _PINNNet, spec: BlackScholesPDESpec, t: torch.Tensor, s: torch.Tensor
) -> torch.Tensor:
    t = t.clone().requires_grad_(True)
    s = s.clone().requires_grad_(True)
    v = _price_from_net(net, spec, t, s)
    v_t = torch.autograd.grad(v.sum(), t, create_graph=True)[0]
    v_s = torch.autograd.grad(v.sum(), s, create_graph=True)[0]
    v_ss = torch.autograd.grad(v_s.sum(), s, create_graph=True)[0]
    sigma2 = spec.volatility**2
    residual: torch.Tensor = (
        v_t + 0.5 * sigma2 * s**2 * v_ss + spec.risk_free_rate * s * v_s - spec.risk_free_rate * v
    )
    return residual


class PINNSolver:
    """A trained PINN, exposing price/Delta/Gamma the same way
    `grid.GridSolution` does -- Delta and Gamma come from
    `torch.autograd`'s exact derivatives of the trained network, not a
    finite difference on it."""

    def __init__(self, net: _PINNNet, spec: BlackScholesPDESpec) -> None:
        self._net = net
        self.spec = spec

    def price_at(self, spot: float, *, time_to_maturity: float | None = None) -> float:
        tau = self.spec.maturity if time_to_maturity is None else time_to_maturity
        t = torch.tensor([self.spec.maturity - tau], dtype=torch.float32)
        s = torch.tensor([spot], dtype=torch.float32)
        with torch.no_grad():
            price = _price_from_net(self._net, self.spec, t, s)
        return float(price.item())

    def delta_at(self, spot: float, *, time_to_maturity: float | None = None) -> float:
        tau = self.spec.maturity if time_to_maturity is None else time_to_maturity
        t = torch.tensor([self.spec.maturity - tau], dtype=torch.float32)
        s = torch.tensor([spot], dtype=torch.float32, requires_grad=True)
        price = _price_from_net(self._net, self.spec, t, s)
        (grad_s,) = torch.autograd.grad(price.sum(), s)
        return float(grad_s.item())

    def gamma_at(self, spot: float, *, time_to_maturity: float | None = None) -> float:
        tau = self.spec.maturity if time_to_maturity is None else time_to_maturity
        t = torch.tensor([self.spec.maturity - tau], dtype=torch.float32)
        s = torch.tensor([spot], dtype=torch.float32, requires_grad=True)
        price = _price_from_net(self._net, self.spec, t, s)
        (grad_s,) = torch.autograd.grad(price.sum(), s, create_graph=True)
        (grad_ss,) = torch.autograd.grad(grad_s.sum(), s)
        return float(grad_ss.item())

    def residual_rms(self, rng: torch.Generator, n_points: int) -> float:
        t = torch.rand(n_points, generator=rng) * self.spec.maturity
        s = torch.rand(n_points, generator=rng) * self.spec.s_max
        residual = _pde_residual(self._net, self.spec, t, s)
        return float(torch.sqrt(torch.mean(residual.detach() ** 2)).item())

    def arbitrage_violation_rate(
        self, rng: torch.Generator, n_points: int, *, slack: float = 1e-3
    ) -> float:
        """PDE-05: the model-free no-arbitrage bounds for a European
        option (not Black-Scholes-specific -- these hold under ANY
        arbitrage-free model): a call is worth at least its intrinsic
        discounted-forward value and at most the spot itself; a put is
        worth at least its intrinsic value and at most the discounted
        strike. Samples `n_points` random (t, S) stress points over the
        FULL domain (including near S=0 and S=s_max, where a
        residual-only-trained net has the least incentive to respect
        these bounds) and reports the fraction that violate either
        bound by more than `slack` (a small numerical-tolerance
        allowance, not a loosening of the economic bound itself)."""
        t = torch.rand(n_points, generator=rng) * self.spec.maturity
        s = torch.rand(n_points, generator=rng) * self.spec.s_max
        tau = self.spec.maturity - t
        with torch.no_grad():
            price = _price_from_net(self._net, self.spec, t, s)
        discounted_strike = self.spec.strike * torch.exp(-self.spec.risk_free_rate * tau)
        if self.spec.option_type == "call":
            lower = torch.clamp(s - discounted_strike, min=0.0)
            upper = s
        else:
            lower = torch.clamp(discounted_strike - s, min=0.0)
            upper = discounted_strike
        violates = (price < lower - slack) | (price > upper + slack)
        return float(violates.float().mean().item())


def train_pinn(
    spec: BlackScholesPDESpec,
    *,
    seed: int,
    n_epochs: int,
    n_interior: int = 192,
    n_boundary: int = 48,
    hidden: int = 48,
    n_layers: int = 3,
    learning_rate: float = 3e-3,
    interior_weight: float = 1.0,
    terminal_weight: float = 10.0,
    boundary_weight: float = 10.0,
    arbitrage_weight: float = 50.0,
    residual_tolerance: float = 4.0,
    optimizer_name: str = "adam",
) -> tuple[PINNSolver, PINNDiagnostics]:
    """`residual_tolerance` default (4.0) is calibrated empirically: a
    well-trained run of this exact configuration (seed=0, n_epochs=1500
    on the strike=100/vol=0.2/r=0.05/T=1 benchmark problem) measures a
    held-out residual RMS of ~2.5 -- see test_pde_pinn.py::
    test_well_trained_model_does_not_raise. 4.0 leaves headroom for
    seed variation while still rejecting a badly under-trained model
    (n_epochs=50 measures RMS in the hundreds)."""
    if n_epochs < 1:
        raise ValueError("n_epochs must be a positive integer")

    torch.manual_seed(seed)
    gen = torch.Generator().manual_seed(seed)
    net = _PINNNet(hidden=hidden, n_layers=n_layers)
    if optimizer_name == "adam":
        optimizer: torch.optim.Optimizer = torch.optim.Adam(net.parameters(), lr=learning_rate)
    elif optimizer_name == "sgd":
        optimizer = torch.optim.SGD(net.parameters(), lr=learning_rate, momentum=0.9)
    else:
        raise ValueError(f"unknown optimizer_name={optimizer_name!r}, expected 'adam' or 'sgd'")
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=n_epochs)

    epoch_log: list[PINNEpochLog] = []
    first_interior_points: np.ndarray | None = None

    start = time.perf_counter()
    for epoch in range(n_epochs):
        t_int = torch.rand(n_interior, generator=gen) * spec.maturity
        s_int = torch.rand(n_interior, generator=gen) * spec.s_max
        if first_interior_points is None:
            first_interior_points = np.stack([t_int.numpy().copy(), s_int.numpy().copy()], axis=1)

        t_term = torch.full((n_boundary,), spec.maturity)
        s_term = torch.rand(n_boundary, generator=gen) * spec.s_max

        t_bd = torch.rand(n_boundary, generator=gen) * spec.maturity
        tau_bd = spec.maturity - t_bd
        s_lower = torch.zeros(n_boundary)
        s_upper = torch.full((n_boundary,), spec.s_max)

        optimizer.zero_grad()
        residual = _pde_residual(net, spec, t_int, s_int)
        interior_loss = torch.mean(residual**2)

        v_int = _price_from_net(net, spec, t_int, s_int)
        tau_int = spec.maturity - t_int
        discounted_strike_int = spec.strike * torch.exp(-spec.risk_free_rate * tau_int)
        if spec.option_type == "call":
            lower_int = torch.clamp(s_int - discounted_strike_int, min=0.0)
            upper_int = s_int
        else:
            lower_int = torch.clamp(discounted_strike_int - s_int, min=0.0)
            upper_int = discounted_strike_int
        arbitrage_loss = torch.mean(torch.clamp(lower_int - v_int, min=0.0) ** 2) + torch.mean(
            torch.clamp(v_int - upper_int, min=0.0) ** 2
        )

        v_term = _price_from_net(net, spec, t_term, s_term)
        payoff_term = torch.as_tensor(spec.payoff(s_term.numpy()), dtype=torch.float32)
        terminal_loss = torch.mean((v_term - payoff_term) ** 2)

        v_lower = _price_from_net(net, spec, t_bd, s_lower)
        bd_lower_target = torch.as_tensor(
            spec.boundary_lower(tau_bd.detach().numpy()), dtype=torch.float32
        )
        v_upper = _price_from_net(net, spec, t_bd, s_upper)
        bd_upper_target = torch.as_tensor(
            spec.boundary_upper(tau_bd.detach().numpy()), dtype=torch.float32
        )
        boundary_loss = torch.mean((v_lower - bd_lower_target) ** 2) + torch.mean(
            (v_upper - bd_upper_target) ** 2
        )

        total_loss = (
            interior_weight * interior_loss
            + terminal_weight * terminal_loss
            + boundary_weight * boundary_loss
            + arbitrage_weight * arbitrage_loss
        )
        total_loss.backward()  # type: ignore[no-untyped-call]
        torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
        optimizer.step()
        scheduler.step()

        epoch_log.append(
            PINNEpochLog(
                epoch=epoch,
                interior_loss=float(interior_loss.item()),
                terminal_loss=float(terminal_loss.item()),
                boundary_loss=float(boundary_loss.item()),
                arbitrage_loss=float(arbitrage_loss.item()),
                total_loss=float(total_loss.item()),
            )
        )
    train_seconds = time.perf_counter() - start

    solver = PINNSolver(net, spec)
    assert first_interior_points is not None
    held_out_rms = solver.residual_rms(gen, n_points=512)

    diagnostics = PINNDiagnostics(
        epoch_log=tuple(epoch_log),
        seed=seed,
        n_parameters=count_parameters(net),
        train_seconds=train_seconds,
        final_interior_residual_rms=held_out_rms,
        interior_points_sample=first_interior_points,
    )

    if held_out_rms > residual_tolerance:
        raise PDEResidualError(
            f"PINN training did not converge: held-out PDE residual RMS "
            f"{held_out_rms:.4f} exceeds residual_tolerance={residual_tolerance} "
            f"after {n_epochs} epochs -- refusing to return a solver whose "
            "quoted price/Greeks have not earned this precision"
        )

    return solver, diagnostics
