"""PDE-02: classical finite-difference reference solver.

Crank-Nicolson on a uniform S-grid, integrated backward from the
terminal condition at t=T to t=0 (equivalently, forward in
tau = T - t). Second-order accurate in both space and time, and
unconditionally stable (unlike explicit Euler, which needs
dt <= ds^2/(sigma^2*s_max^2) to avoid blowing up) -- standard textbook
choice for this exact problem (Wilmott/Howison/Dewynne; Tavella &
Randall), used here because it is the honest "reliable numerical
method" PDE-12 asks the neural solvers to be compared against, not a
deliberately weak strawman.

Interior node i (S_i = i*ds) semi-discretizes to
    dV_i/dtau = a_i*V_{i-1} + b_i*V_i + c_i*V_{i+1}
    a_i = 0.5*sigma^2*i^2 - 0.5*r*i
    b_i = -sigma^2*i^2 - r
    c_i = 0.5*sigma^2*i^2 + 0.5*r*i
via central differences on V_S and V_SS. Crank-Nicolson averages the
explicit and implicit discretizations of this ODE system:
    (I - 0.5*dtau*A) V^{n+1} = (I + 0.5*dtau*A) V^n
solved as a tridiagonal system with `scipy.linalg.solve_banded`
(O(M) per step, not O(M^3)) -- `grid_node_count` in `benchmark.py` is
what shows this becomes impractical once extended past 1 spatial
dimension, which this module deliberately does NOT attempt.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.linalg import solve_banded

from prometheus.pde_solvers.problem import BlackScholesPDESpec


@dataclass(frozen=True, slots=True)
class GridSolution:
    spec: BlackScholesPDESpec
    n_space: int
    n_time: int
    s_grid: np.ndarray
    prices_at_t0: np.ndarray
    """V(S_i, t=0) for every grid node i -- today's price as a function
    of spot, read off the finished backward sweep."""

    def price_at(self, spot: float) -> float:
        """Linear interpolation of `prices_at_t0` onto an arbitrary
        spot -- the grid is evaluated at discrete nodes, this is the
        standard way to read a price off it at a spot that doesn't
        land exactly on one."""
        if not (0.0 <= spot <= self.spec.s_max):
            raise ValueError(
                f"spot={spot} is outside the solved grid domain [0, {self.spec.s_max}]"
            )
        return float(np.interp(spot, self.s_grid, self.prices_at_t0))

    def delta_at(self, spot: float) -> float:
        """Central finite difference of `prices_at_t0` w.r.t. S."""
        ds = float(self.s_grid[1] - self.s_grid[0])
        return (self.price_at(spot + ds) - self.price_at(spot - ds)) / (2 * ds)

    def gamma_at(self, spot: float) -> float:
        ds = float(self.s_grid[1] - self.s_grid[0])
        return (self.price_at(spot + ds) - 2 * self.price_at(spot) + self.price_at(spot - ds)) / (
            ds**2
        )


def solve_crank_nicolson(spec: BlackScholesPDESpec, *, n_space: int, n_time: int) -> GridSolution:
    if n_space < 3:
        raise ValueError("n_space must be >= 3 to have at least one interior node")
    if n_time < 1:
        raise ValueError("n_time must be >= 1")

    dt = spec.maturity / n_time
    s_grid = np.linspace(0.0, spec.s_max, n_space + 1)
    i = np.arange(1, n_space, dtype=float)
    sigma2 = spec.volatility**2
    r = spec.risk_free_rate

    a = 0.5 * sigma2 * i**2 - 0.5 * r * i
    b = -sigma2 * i**2 - r
    c = 0.5 * sigma2 * i**2 + 0.5 * r * i

    n_interior = n_space - 1
    implicit_diag = 1.0 - 0.5 * dt * b
    implicit_lower = -0.5 * dt * a
    implicit_upper = -0.5 * dt * c
    explicit_diag = 1.0 + 0.5 * dt * b
    explicit_lower = 0.5 * dt * a
    explicit_upper = 0.5 * dt * c

    ab = np.zeros((3, n_interior))
    ab[0, 1:] = implicit_upper[:-1]
    ab[1, :] = implicit_diag
    ab[2, :-1] = implicit_lower[1:]

    v = spec.payoff(s_grid)
    for step in range(n_time):
        tau_old = step * dt
        tau_new = (step + 1) * dt
        v_lower_old = spec.boundary_lower(np.array([tau_old]))[0]
        v_upper_old = spec.boundary_upper(np.array([tau_old]))[0]
        v_lower_new = spec.boundary_lower(np.array([tau_new]))[0]
        v_upper_new = spec.boundary_upper(np.array([tau_new]))[0]

        interior = v[1:-1]
        rhs = explicit_diag * interior
        rhs[1:] += explicit_lower[1:] * interior[:-1]
        rhs[:-1] += explicit_upper[:-1] * interior[1:]
        rhs[0] += explicit_lower[0] * v_lower_old
        rhs[-1] += explicit_upper[-1] * v_upper_old
        rhs[0] -= implicit_lower[0] * v_lower_new
        rhs[-1] -= implicit_upper[-1] * v_upper_new

        new_interior = solve_banded((1, 1), ab, rhs)
        v = np.empty(n_space + 1)
        v[0] = v_lower_new
        v[-1] = v_upper_new
        v[1:-1] = new_interior

    return GridSolution(spec=spec, n_space=n_space, n_time=n_time, s_grid=s_grid, prices_at_t0=v)
