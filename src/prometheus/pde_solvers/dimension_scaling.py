"""Dimension scaling of the classical grid against Monte Carlo (audit item M-04).

`benchmark.grid_node_count` states the mechanism (M^d nodes); this module MEASURES it. The test
problem is chosen so that an exact answer exists in every dimension: a European call on the
GEOMETRIC average of d independent lognormal assets with equal volatility (the payoff is
max((prod S_i)^(1/d) - K, 0)). The geometric average of independent lognormals is itself lognormal,
so the price is Black-Scholes with forward E[G_T] = S0 exp((r - sigma^2/2) T + sigma^2 T / (2d)) and
volatility sigma / sqrt(d): an independent reference at any d, and a way to measure error rather
than assume it.

Two methods are run on it and measured at each d: runtime, memory, and error against that exact
price.

- GRID: a tensor-product finite-difference grid in log-price (independent assets make the operator a
  Kronecker sum of d one-dimensional operators, central differences, second order in space),
  Crank-Nicolson in time with Rannacher start-up (four implicit half-steps first, which restores the
  time order a kinked payoff otherwise loses), one sparse LU factorization reused for every step.
- MONTE CARLO: exact terminal sampling of all d assets, as many paths as a 95% interval of the
  requested half-width needs.

What the numbers mean and do not mean. The grid here uses a DIRECT sparse solver, whose fill-in
grows faster than the node count, so its memory and time at d >= 3 are those of this solver, not a
bound for every grid method (ADI splitting or multigrid would do better and are not tried). Peak
memory is
what `tracemalloc` sees (NumPy and SciPy array allocations); the LU factors are allocated inside
SuperLU, which it does not see, so the factors' size is reported separately as `factor_nnz`
(about 12 bytes per stored entry). No neural solver is run here: the repository's deep-BSDE and PINN
costs are in Finding 6 and are not repeated. The comparison that matters first is against plain
Monte Carlo, whose cost per unit error does not depend on d at all.
"""

from __future__ import annotations

import argparse
import json
import math
import time
import tracemalloc
from collections.abc import Sequence
from dataclasses import asdict, dataclass

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla
from scipy.stats import norm

from prometheus.numerics import require_finite

MAX_NODES = 150_000
"""A refusal, not a tuning knob: direct sparse factorization of more nodes than this has taken tens
of gigabytes in 3-4 dimensions, and a study that exhausts memory measures nothing."""
BYTES_PER_FACTOR_ENTRY = 12


@dataclass(frozen=True, slots=True)
class BasketProblem:
    dimension: int
    spot: float = 100.0
    strike: float = 100.0
    rate: float = 0.05
    volatility: float = 0.2
    maturity: float = 1.0

    def __post_init__(self) -> None:
        require_finite(
            spot=self.spot,
            strike=self.strike,
            rate=self.rate,
            volatility=self.volatility,
            maturity=self.maturity,
        )
        if self.dimension < 1:
            raise ValueError("dimension must be >= 1")
        if min(self.spot, self.strike, self.volatility, self.maturity) <= 0:
            raise ValueError("spot, strike, volatility and maturity must be positive")

    def exact_price(self) -> float:
        d, sigma, t = self.dimension, self.volatility, self.maturity
        forward = self.spot * math.exp((self.rate - 0.5 * sigma**2) * t + 0.5 * sigma**2 * t / d)
        total_vol = sigma * math.sqrt(t / d)
        d1 = (math.log(forward / self.strike) + 0.5 * total_vol**2) / total_vol
        d2 = d1 - total_vol
        discounted = forward * norm.cdf(d1) - self.strike * norm.cdf(d2)
        return float(math.exp(-self.rate * t) * discounted)


@dataclass(frozen=True, slots=True)
class ScalingPoint:
    method: str
    dimension: int
    resolution: int
    """Nodes per axis for the grid; number of paths for Monte Carlo."""
    unknowns: int
    """Grid nodes (resolution ** dimension); paths for Monte Carlo."""
    price: float
    exact_price: float
    error: float
    """price - exact_price (signed)."""
    standard_error: float | None
    seconds: float
    peak_traced_bytes: int
    factor_nnz: int | None


def solve_grid(
    problem: BasketProblem, nodes_per_axis: int, n_time: int, half_width: float = 6.0
) -> ScalingPoint:
    """Price the geometric basket on a `nodes_per_axis`^d grid. `nodes_per_axis` must be odd so the
    spot sits on a node; the box is +-`half_width` standard deviations of the log price."""
    d = problem.dimension
    if nodes_per_axis < 5 or nodes_per_axis % 2 == 0:
        raise ValueError("nodes_per_axis must be an odd number >= 5")
    if n_time < 3:
        raise ValueError("n_time must be >= 3 (two Crank-Nicolson steps follow the start-up)")
    if half_width <= 0:
        raise ValueError("half_width must be positive")
    total = nodes_per_axis**d
    if total > MAX_NODES:
        raise ValueError(
            f"{total} nodes exceeds the {MAX_NODES} cap: a direct sparse factorization this large "
            "can exhaust memory"
        )
    m, sigma, r = nodes_per_axis, problem.volatility, problem.rate
    started = time.perf_counter()
    tracemalloc.start()
    try:
        width = half_width * sigma * math.sqrt(problem.maturity)
        x = np.linspace(-width, width, m)
        h = float(x[1] - x[0])
        drift = r - 0.5 * sigma**2
        half_var = 0.5 * sigma**2
        tridiagonal = (
            np.diag(np.full(m, -2 * half_var / h**2))
            + np.diag(np.full(m - 1, half_var / h**2 - drift / (2 * h)), -1)
            + np.diag(np.full(m - 1, half_var / h**2 + drift / (2 * h)), 1)
        )
        one_d = sp.csr_matrix(tridiagonal)
        eye = sp.identity(m, format="csr")
        operator = sp.csr_matrix((total, total))
        for axis in range(d):
            term = sp.identity(1, format="csr")  # kron(1, A) = A: the start of the product
            for j in range(d):
                term = sp.kron(term, one_d if j == axis else eye, format="csr")
            operator = operator + term
        operator = operator - r * sp.identity(total, format="csr")

        mesh = np.meshgrid(*([x] * d), indexing="ij")
        log_mean = sum(mesh) / d
        payoff = np.maximum(problem.spot * np.exp(log_mean) - problem.strike, 0.0).ravel()
        edge = np.zeros((m,) * d, dtype=bool)
        for axis in range(d):
            for index in (0, -1):
                face: list[slice | int] = [slice(None)] * d
                face[axis] = index
                edge[tuple(face)] = True
        edge_flat = edge.ravel()
        inner = ~edge_flat
        a_ii = operator[inner][:, inner].tocsc()
        a_ie = operator[inner][:, edge_flat].tocsr()
        identity = sp.identity(a_ii.shape[0], format="csc")
        dt = problem.maturity / n_time
        factor_lu = spla.splu((identity - 0.5 * dt * a_ii).tocsc())
        edge_payoff = payoff[edge_flat]

        def boundary(tau: float) -> np.ndarray:
            return np.asarray(math.exp(-r * tau) * edge_payoff)

        v = payoff.copy()
        interior = v[inner]
        # Rannacher start-up: 4 implicit half-steps,
        # (I - dt/2 A) v_new = v_old + dt/2 A_ie b(tau_new)
        for j in range(1, 5):
            rhs = interior + 0.5 * dt * (a_ie @ boundary(j * 0.5 * dt))
            interior = factor_lu.solve(rhs)
        tau = 2.0 * dt
        for _ in range(n_time - 2):
            rhs = interior + 0.5 * dt * (a_ii @ interior)
            rhs = rhs + 0.5 * dt * (a_ie @ (boundary(tau) + boundary(tau + dt)))
            interior = factor_lu.solve(rhs)
            tau += dt
        v[inner] = interior
        price = float(v.reshape((m,) * d)[(m // 2,) * d])
        # read the peak BEFORE touching the factors: `.L` and `.U` copy them into SciPy matrices,
        # which would put a second copy of the factorization into the measured peak
        _, peak = tracemalloc.get_traced_memory()
        factor_nnz = int(factor_lu.L.nnz + factor_lu.U.nnz)
    finally:
        tracemalloc.stop()
    seconds = time.perf_counter() - started
    exact = problem.exact_price()
    return ScalingPoint(
        method="grid",
        dimension=d,
        resolution=m,
        unknowns=total,
        price=price,
        exact_price=exact,
        error=price - exact,
        standard_error=None,
        seconds=seconds,
        peak_traced_bytes=int(peak),
        factor_nnz=factor_nnz,
    )


def paths_for_half_width(
    problem: BasketProblem, half_width: float, rng: np.random.Generator
) -> int:
    """Paths so that the 95% interval half-width is `half_width`, from a 20,000-path pilot."""
    if half_width <= 0:
        raise ValueError("half_width must be positive")
    pilot = _discounted_payoffs(problem, 20_000, rng)
    return max(1_000, math.ceil((1.96 * float(pilot.std(ddof=1)) / half_width) ** 2))


def _discounted_payoffs(
    problem: BasketProblem, n_paths: int, rng: np.random.Generator
) -> np.ndarray:
    d, sigma, t = problem.dimension, problem.volatility, problem.maturity
    z = rng.standard_normal((n_paths, d))
    log_s = np.log(problem.spot) + (problem.rate - 0.5 * sigma**2) * t + sigma * math.sqrt(t) * z
    geometric = np.exp(log_s.mean(axis=1))
    return np.asarray(math.exp(-problem.rate * t) * np.maximum(geometric - problem.strike, 0.0))


def run_monte_carlo(
    problem: BasketProblem, n_paths: int, rng: np.random.Generator, batch: int = 100_000
) -> ScalingPoint:
    if n_paths < 2 or batch < 1:
        raise ValueError("n_paths must be >= 2 and batch >= 1")
    started = time.perf_counter()
    tracemalloc.start()
    try:
        total = total_sq = 0.0
        done = 0
        while done < n_paths:
            n = min(batch, n_paths - done)
            values = _discounted_payoffs(problem, n, rng)
            total += float(values.sum())
            total_sq += float((values**2).sum())
            done += n
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    seconds = time.perf_counter() - started
    price = total / n_paths
    variance = max(total_sq / n_paths - price**2, 0.0) * n_paths / (n_paths - 1)
    exact = problem.exact_price()
    return ScalingPoint(
        method="monte_carlo",
        dimension=problem.dimension,
        resolution=n_paths,
        unknowns=n_paths,
        price=price,
        exact_price=exact,
        error=price - exact,
        standard_error=math.sqrt(variance / n_paths),
        seconds=seconds,
        peak_traced_bytes=int(peak),
        factor_nnz=None,
    )


DEFAULT_LADDERS: dict[int, tuple[int, ...]] = {
    1: (21, 41, 81, 161, 321),
    2: (11, 21, 41, 81, 121),
    3: (9, 15, 21, 31, 41),
    4: (7, 9, 11),
}


def run_study(
    ladders: dict[int, tuple[int, ...]] | None = None,
    target_error: float = 0.02,
    seed: int = 0,
) -> dict[str, object]:
    """The grid ladder and a Monte Carlo run sized to `target_error` at every dimension, and for
    each dimension the cheapest grid whose absolute error is within `target_error` (or None)."""
    if target_error <= 0:
        raise ValueError("target_error must be positive")
    rng = np.random.default_rng(seed)
    rows: list[dict[str, object]] = []
    matched: list[dict[str, object]] = []
    for d, ladder in (ladders or DEFAULT_LADDERS).items():
        problem = BasketProblem(dimension=d)
        grid = [solve_grid(problem, m, max(m, 20)) for m in ladder]
        n_paths = paths_for_half_width(problem, target_error, rng)
        mc = run_monte_carlo(problem, n_paths, rng)
        rows += [asdict(p) for p in (*grid, mc)]
        within = [p for p in grid if abs(p.error) <= target_error]
        best = min(within, key=lambda p: p.seconds) if within else None
        matched.append(
            {
                "dimension": d,
                "target_abs_error": target_error,
                "grid": asdict(best) if best else None,
                "grid_best_error_reached": min(abs(p.error) for p in grid),
                "monte_carlo": asdict(mc),
            }
        )
    return {
        "problem": asdict(BasketProblem(dimension=1)) | {"dimension": "d"},
        "points": rows,
        "matched": matched,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--target-error", type=float, default=0.02)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    print(json.dumps(run_study(target_error=args.target_error, seed=args.seed), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
