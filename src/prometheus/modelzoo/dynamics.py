"""Learning continuous dynamics: a Neural ODE, a Hamiltonian Neural Network (HNN) and a Symplectic
Network (SympNet), tested on two systems whose motion conserves an energy.

* the **pendulum**, H(q, p) = p^2/2 + 1 - cos q;
* the **Goodwin growth cycle**, the classic macroeconomic predator-prey model (employment against
  the wage share), written in log coordinates where it is exactly Hamiltonian:
  H(q, p) = d*e^p - c*p + b*e^q - a*q, with q' = dH/dp and p' = -dH/dq.
  (q is the log of one variable and p the log of the other; a, b, c, d are the model's rates.)

What each model assumes:

* `MLPField` (Neural ODE, Chen et al. 2018): learns the vector field dy/dt = f(y) with a plain
network
  and is integrated with a fixed-step Runge-Kutta 4 solver written here. No structure is built in.
* `HNN` (Greydanus et al. 2019): learns a scalar H(y) and takes the field to be J grad H, so that
H is
  conserved by the *continuous* flow whatever the network learned. The numerical integrator may
  still
  drift.
* `SympNet` (Jin et al. 2020): learns the one-step *map* as a composition of shears, each the
gradient
  of a learned potential of one coordinate, so the map is exactly symplectic for any parameters.

The Neural CDE (Kidger et al. 2020) is here too, as `NeuralCDE`: a controlled differential equation
dz = f(z) dX driven by an interpolated input path X, for series observed at irregular times.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import torch
from torch import nn

Field = Callable[[torch.Tensor], torch.Tensor]


# ----- the two true systems -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class System:
    name: str
    field: Field
    energy: Field
    start: tuple[float, float]
    box: tuple[
        float, float, float, float
    ]  # q_lo, q_hi, p_lo, p_hi: where training states are drawn


def _pendulum_field(y: torch.Tensor) -> torch.Tensor:
    return torch.stack([y[..., 1], -torch.sin(y[..., 0])], dim=-1)


def _pendulum_energy(y: torch.Tensor) -> torch.Tensor:
    return 0.5 * y[..., 1] ** 2 + 1.0 - torch.cos(y[..., 0])


_A = _B = _C = _D = 1.0


def _goodwin_field(y: torch.Tensor) -> torch.Tensor:
    q, p = y[..., 0], y[..., 1]
    return torch.stack([_D * torch.exp(p) - _C, -(_B * torch.exp(q) - _A)], dim=-1)


def _goodwin_energy(y: torch.Tensor) -> torch.Tensor:
    q, p = y[..., 0], y[..., 1]
    return _D * torch.exp(p) - _C * p + _B * torch.exp(q) - _A * q


SYSTEMS: dict[str, System] = {
    "pendulum": System(
        "pendulum", _pendulum_field, _pendulum_energy, (1.0, 0.0), (-1.5, 1.5, -1.5, 1.5)
    ),
    "goodwin": System(
        "goodwin", _goodwin_field, _goodwin_energy, (0.6, 0.0), (-0.8, 0.8, -0.8, 0.8)
    ),
}


def rk4_step(field: Field, y: torch.Tensor, dt: float) -> torch.Tensor:
    k1 = field(y)
    k2 = field(y + 0.5 * dt * k1)
    k3 = field(y + 0.5 * dt * k2)
    k4 = field(y + dt * k3)
    return y + dt / 6.0 * (k1 + 2 * k2 + 2 * k3 + k4)


def rollout(field: Field, y0: torch.Tensor, dt: float, steps: int) -> torch.Tensor:
    """RK4 trajectory, shape (steps + 1, ..., 2). Gradients flow through it if y0 or the field
    needs them."""
    states = [y0]
    y = y0
    for _ in range(steps):
        y = rk4_step(field, y, dt)
        states.append(y)
    return torch.stack(states)


# ----- the three models ---------------------------------------------------------------------------


class MLPField(nn.Module):
    def __init__(self, width: int = 64) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(2, width), nn.Tanh(), nn.Linear(width, width), nn.Tanh(), nn.Linear(width, 2)
        )

    def forward(self, y: torch.Tensor) -> torch.Tensor:
        out: torch.Tensor = self.net(y)
        return out


class HNN(nn.Module):
    def __init__(self, width: int = 64) -> None:
        super().__init__()
        self.hamiltonian = nn.Sequential(
            nn.Linear(2, width), nn.Tanh(), nn.Linear(width, width), nn.Tanh(), nn.Linear(width, 1)
        )

    def energy(self, y: torch.Tensor) -> torch.Tensor:
        out: torch.Tensor = self.hamiltonian(y).squeeze(-1)
        return out

    def forward(self, y: torch.Tensor) -> torch.Tensor:
        with torch.enable_grad():
            if not y.requires_grad:
                y = y.detach().requires_grad_(True)
            (grad,) = torch.autograd.grad(self.energy(y).sum(), y, create_graph=self.training)
        return torch.stack([grad[..., 1], -grad[..., 0]], dim=-1)


class SympNet(nn.Module):
    """Alternating shears p += grad V(q), q += grad T(p), each potential a one-hidden-layer
    network."""

    def __init__(self, layers: int = 6, width: int = 24) -> None:
        super().__init__()
        self.layers = layers
        self.k = nn.ParameterList(nn.Parameter(0.5 * torch.randn(width)) for _ in range(layers))
        self.b = nn.ParameterList(nn.Parameter(0.1 * torch.randn(width)) for _ in range(layers))
        self.a = nn.ParameterList(nn.Parameter(0.1 * torch.randn(width)) for _ in range(layers))

    def _shear(self, i: int, x: torch.Tensor) -> torch.Tensor:
        # sum_j a_j tanh(k_j x + b_j) is the derivative of sum_j (a_j / k_j) log cosh(k_j x + b_j)
        shear: torch.Tensor = (self.a[i] * torch.tanh(x.unsqueeze(-1) * self.k[i] + self.b[i])).sum(
            -1
        )
        return shear

    def forward(self, y: torch.Tensor) -> torch.Tensor:
        q, p = y[..., 0], y[..., 1]
        for i in range(self.layers):
            if i % 2 == 0:
                p = p + self._shear(i, q)
            else:
                q = q + self._shear(i, p)
        return torch.stack([q, p], dim=-1)


class NeuralCDE(nn.Module):
    """dz = f_theta(z) dX with X the linear interpolation of the observed (time, value) path."""

    def __init__(self, input_channels: int, hidden: int = 32, width: int = 64) -> None:
        super().__init__()
        self.input_channels = input_channels
        self.hidden = hidden
        self.embed = nn.Linear(input_channels, hidden)
        self.f = nn.Sequential(
            nn.Linear(hidden, width), nn.Tanh(), nn.Linear(width, hidden * input_channels)
        )
        self.readout = nn.Linear(hidden, 1)

    def forward(self, times: torch.Tensor, values: torch.Tensor) -> torch.Tensor:
        """times (B, T) increasing; values (B, T, C - 1). The control is (time, value): C
        channels."""
        path = torch.cat([times.unsqueeze(-1), values], dim=-1)  # (B, T, C)
        z = self.embed(path[:, 0])
        for i in range(path.shape[1] - 1):
            dx = path[:, i + 1] - path[:, i]  # linear interpolation: dX is constant on the interval
            fz = self.f(z).view(-1, self.hidden, self.input_channels)
            z = z + torch.einsum(
                "bhc,bc->bh", fz, dx
            )  # an Euler step on each linear piece of X, first-order accurate
        out: torch.Tensor = self.readout(z).squeeze(-1)
        return out


# ----- training and evaluation --------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DynamicsData:
    states: torch.Tensor  # (n, 2)
    derivatives: torch.Tensor  # (n, 2) the true field at those states
    next_states: torch.Tensor  # (n, 2) one RK4 step (the finest-step truth) later
    dt: float


def make_dynamics_data(system: System, n: int, dt: float, *, seed: int) -> DynamicsData:
    generator = torch.Generator().manual_seed(seed)
    q_lo, q_hi, p_lo, p_hi = system.box
    q = q_lo + (q_hi - q_lo) * torch.rand(n, generator=generator)
    p = p_lo + (p_hi - p_lo) * torch.rand(n, generator=generator)
    y = torch.stack([q, p], dim=-1).double()
    nxt = y
    for _ in range(10):  # ten substeps per data step: the "truth" map
        nxt = rk4_step(system.field, nxt, dt / 10.0)
    return DynamicsData(y.float(), system.field(y).float(), nxt.float(), dt)


def train_field(
    model: nn.Module, data: DynamicsData, *, epochs: int, seed: int, lr: float = 3e-3
) -> float:
    """Derivative regression for MLPField and HNN: fit the field at sampled states."""
    torch.manual_seed(seed)
    optimiser = torch.optim.Adam(model.parameters(), lr=lr)
    schedule = torch.optim.lr_scheduler.CosineAnnealingLR(optimiser, T_max=epochs)
    model.train()
    loss_value = float("nan")
    for _ in range(epochs):
        loss = ((model(data.states) - data.derivatives) ** 2).mean()
        optimiser.zero_grad()
        loss.backward()
        optimiser.step()
        schedule.step()
        loss_value = float(loss.detach())
    return loss_value


def train_map(
    model: SympNet, data: DynamicsData, *, epochs: int, seed: int, lr: float = 3e-3
) -> float:
    """One-step regression for the SympNet: fit the map y -> y(dt)."""
    torch.manual_seed(seed)
    optimiser = torch.optim.Adam(model.parameters(), lr=lr)
    schedule = torch.optim.lr_scheduler.CosineAnnealingLR(optimiser, T_max=epochs)
    loss_value = float("nan")
    for _ in range(epochs):
        loss = ((model(data.states) - data.next_states) ** 2).mean()
        optimiser.zero_grad()
        loss.backward()
        optimiser.step()
        schedule.step()
        loss_value = float(loss.detach())
    return loss_value


def long_rollout(model: nn.Module, y0: torch.Tensor, dt: float, steps: int) -> torch.Tensor:
    """States at every step of a long trajectory: a map is iterated, a field is integrated by
    RK4."""
    model.eval()
    if isinstance(model, SympNet):
        states = [y0]
        y = y0
        with torch.no_grad():
            for _ in range(steps):
                y = model(y)
                states.append(y)
        return torch.stack(states)
    if isinstance(model, HNN):
        states = [y0]
        y = y0
        for _ in range(steps):
            y = rk4_step(model, y, dt).detach()
            states.append(y)
        return torch.stack(states)
    with torch.no_grad():
        return rollout(model, y0, dt, steps)


def true_rollout(system: System, y0: torch.Tensor, dt: float, steps: int) -> torch.Tensor:
    y = y0.double()
    states = [y.float()]
    for _ in range(steps):
        for _ in range(10):
            y = rk4_step(system.field, y, dt / 10.0)
        states.append(y.float())
    return torch.stack(states)


@dataclass(frozen=True, slots=True)
class RolloutScore:
    energy_drift: float  # |H(y_T) - H(y_0)| / spread of H over the data box, at the final step
    max_energy_drift: float
    state_error_at: dict[int, float]  # steps -> mean |y - y_true|


def score_rollout(
    system: System, model: nn.Module, dt: float, steps: int, checkpoints: tuple[int, ...]
) -> RolloutScore:
    y0 = torch.tensor([system.start], dtype=torch.float32)
    learned = long_rollout(model, y0, dt, steps)[:, 0]
    truth = true_rollout(system, y0, dt, steps)[:, 0]
    energy0 = float(system.energy(truth[0].double()))
    axis_q = torch.linspace(system.box[0], system.box[1], 25, dtype=torch.float64)
    axis_p = torch.linspace(system.box[2], system.box[3], 25, dtype=torch.float64)
    cloud = torch.cartesian_prod(axis_q, axis_p)
    energies = system.energy(cloud)
    spread = float(energies.max() - energies.min())
    drift = (system.energy(learned.double()) - energy0).abs() / spread
    err = (learned - truth).abs().mean(dim=-1)
    return RolloutScore(
        energy_drift=float(drift[-1]),
        max_energy_drift=float(drift.max()),
        state_error_at={c: float(err[c]) for c in checkpoints if c <= steps},
    )


def symplectic_defect(model: SympNet, points: torch.Tensor) -> float:
    """Largest |det J - 1| of the learned map over the points (zero for a symplectic map in 2-D)."""
    worst = 0.0
    for point in points:
        jac = torch.autograd.functional.jacobian(model, point)  # type: ignore[no-untyped-call]
        worst = max(worst, abs(float(torch.det(jac)) - 1.0))
    return worst


def period_of(system: System, dt: float, steps: int = 4000) -> float:
    """Period of the true orbit from the start state: the first time p comes back down through
    its start value."""
    y0 = torch.tensor([system.start], dtype=torch.float32)
    p = true_rollout(system, y0, dt, steps)[:, 0, 1].numpy()
    crossings = np.flatnonzero((p[:-1] > p[0]) & (p[1:] <= p[0]))
    return float(crossings[0] * dt) if crossings.size else math.nan
