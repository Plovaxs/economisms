"""Run the real PDE-solver cost/accuracy comparison end to end: the
closed-form Black-Scholes price, the classical Crank-Nicolson grid
solver, a PINN, and a deep-BSDE net all price the SAME option spec,
with real wall-clock cost reported for each -- the classical-vs-neural
comparison this project's other engines each make, for the one
subsystem that previously had no orchestration/CLI layer at all.

This calls `pde_solvers.grid.solve_crank_nicolson`/`pde_solvers.pinn.
train_pinn`/`pde_solvers.deep_bsde.train_deep_bsde`/`volterra.
black_scholes.black_scholes_price` directly -- every one of them
REUSED UNCHANGED -- rather than going through `pde_solvers.benchmark.
compute_cost_comparison`, which exists already but hardcodes its PINN/
deep-BSDE epoch counts (1500/400) at `seed=0`: measured directly in
this environment, those fixed counts take roughly 8 minutes combined,
well past this job system's own 300-second default wall-clock budget
(`jobs.store.ResourcePolicy.max_wall_seconds`). Calling the lower-level
functions directly, with `pinn_epochs`/`bsde_epochs`/`seed` exposed as
real config fields, keeps every primitive reused and unmodified while
making both epoch counts AND the seed genuinely controllable --
`compute_cost_comparison` itself accepts neither. The chosen defaults
(100 PINN epochs, 20 deep-BSDE epochs) complete in well under a minute
in this environment; a real, more thorough run is one job-config
change away, at the cost of more wall time, the same tradeoff every
other `*_epochs` field in this project already exposes.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, fields
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from prometheus.evidence.contracts import CONVENTIONS
from prometheus.evidence.export import build_evidence_bundle
from prometheus.evidence.repository_status import current_repository_gate_report
from prometheus.experiments.manifest import RunManifest, compute_result_hash, new_run_id, now_iso
from prometheus.pde_solvers.benchmark import ComputeCostRow, grid_node_count
from prometheus.pde_solvers.deep_bsde import train_deep_bsde
from prometheus.pde_solvers.grid import solve_crank_nicolson
from prometheus.pde_solvers.pinn import train_pinn
from prometheus.pde_solvers.problem import BasketOptionPDESpec, BlackScholesPDESpec
from prometheus.volterra.black_scholes import black_scholes_price
from prometheus.volterra.instruments import EuropeanOption
from prometheus.volterra.market import MarketSnapshot

_ARBITRARY_AS_OF = date(2024, 1, 1)
"""Same reasoning as `pde_solvers.benchmark`'s own module-level
constant: Black-Scholes is time-homogeneous, so which calendar date is
used for `MarketSnapshot.as_of` does not affect the reported price."""


@dataclass(frozen=True, slots=True)
class PdeSolverRunConfig:
    seed: int = 0
    risk_free_rate: float = 0.05
    volatility: float = 0.2
    maturity: float = 1.0
    strike: float = 100.0
    n_space_grid_1d: int = 400
    pinn_epochs: int = 100
    bsde_epochs: int = 20

    def __post_init__(self) -> None:
        if self.seed < 0:
            raise ValueError("seed must be non-negative")
        if self.volatility <= 0:
            raise ValueError("volatility must be positive")
        if self.maturity <= 0:
            raise ValueError("maturity must be positive")
        if self.strike <= 0:
            raise ValueError("strike must be positive")
        if self.n_space_grid_1d < 2:
            raise ValueError("n_space_grid_1d must be at least 2")
        if self.pinn_epochs < 1:
            raise ValueError("pinn_epochs must be a positive integer")
        if self.bsde_epochs < 1:
            raise ValueError("bsde_epochs must be a positive integer")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> PdeSolverRunConfig:
        if set(payload) != {item.name for item in fields(cls)}:
            raise ValueError("pde_solver recipe requires exactly the complete configuration fields")
        try:
            return cls(**dict(payload))
        except TypeError as exc:
            raise ValueError(f"invalid pde_solver recipe: {exc}") from exc


@dataclass(frozen=True, slots=True)
class PdeSolverRunResult:
    rows: tuple[ComputeCostRow, ...]
    manifest: RunManifest
    evidence_bundle: dict[str, Any]


def run_pde_solver(config: PdeSolverRunConfig) -> PdeSolverRunResult:
    spec = BlackScholesPDESpec(
        risk_free_rate=config.risk_free_rate,
        volatility=config.volatility,
        maturity=config.maturity,
        strike=config.strike,
        option_type="call",
    )
    basket_spec = BasketOptionPDESpec(
        risk_free_rate=config.risk_free_rate,
        volatilities=(config.volatility,),
        correlation=((1.0,),),
        maturity=config.maturity,
        strike=config.strike,
        option_type="call",
    )

    rows: list[ComputeCostRow] = []

    start = time.perf_counter()
    closed_price = black_scholes_price(
        MarketSnapshot(
            as_of=_ARBITRARY_AS_OF,
            spot=config.strike,
            risk_free_rate=config.risk_free_rate,
            volatility=config.volatility,
        ),
        EuropeanOption(config.strike, config.maturity, "call"),
    )
    rows.append(
        ComputeCostRow(
            method="black_scholes_closed_form",
            n_dimensions=1,
            wall_seconds=time.perf_counter() - start,
            grid_nodes=None,
            price=closed_price,
        )
    )

    start = time.perf_counter()
    grid_solution = solve_crank_nicolson(
        spec, n_space=config.n_space_grid_1d, n_time=config.n_space_grid_1d
    )
    rows.append(
        ComputeCostRow(
            method="crank_nicolson_grid",
            n_dimensions=1,
            wall_seconds=time.perf_counter() - start,
            grid_nodes=grid_node_count(config.n_space_grid_1d, 1),
            price=grid_solution.price_at(config.strike),
        )
    )

    pinn_solver, pinn_diag = train_pinn(
        spec, seed=config.seed, n_epochs=config.pinn_epochs, residual_tolerance=1e9
    )
    rows.append(
        ComputeCostRow(
            method="pinn",
            n_dimensions=1,
            wall_seconds=pinn_diag.train_seconds,
            grid_nodes=None,
            price=pinn_solver.price_at(config.strike),
        )
    )

    bsde_result = train_deep_bsde(
        basket_spec,
        np.array([config.strike]),
        seed=config.seed,
        n_time=20,
        n_paths=512,
        n_epochs=config.bsde_epochs,
        learning_rate=0.03,
    )
    rows.append(
        ComputeCostRow(
            method="deep_bsde",
            n_dimensions=1,
            wall_seconds=bsde_result.diagnostics.train_seconds,
            grid_nodes=None,
            price=bsde_result.price,
        )
    )

    payload: dict[str, Any] = {
        "schema_version": 1,
        "accounting_convention": CONVENTIONS["pde_solver"],
        "config": asdict(config),
        "rows": [asdict(row) for row in rows],
    }
    manifest = RunManifest(
        new_run_id("pmth-pde-solver"),
        now_iso(),
        config.seed,
        asdict(config),
        compute_result_hash(payload),
    )
    bundle = build_evidence_bundle(manifest, [], current_repository_gate_report())
    bundle["pde_solver"] = payload
    return PdeSolverRunResult(rows=tuple(rows), manifest=manifest, evidence_bundle=bundle)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--risk-free-rate", type=float, default=0.05)
    parser.add_argument("--volatility", type=float, default=0.2)
    parser.add_argument("--maturity", type=float, default=1.0)
    parser.add_argument("--strike", type=float, default=100.0)
    parser.add_argument("--n-space-grid-1d", type=int, default=400)
    parser.add_argument("--pinn-epochs", type=int, default=100)
    parser.add_argument("--bsde-epochs", type=int, default=20)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        config = PdeSolverRunConfig(
            seed=args.seed,
            risk_free_rate=args.risk_free_rate,
            volatility=args.volatility,
            maturity=args.maturity,
            strike=args.strike,
            n_space_grid_1d=args.n_space_grid_1d,
            pinn_epochs=args.pinn_epochs,
            bsde_epochs=args.bsde_epochs,
        )
    except ValueError as exc:
        parser.error(str(exc))

    result = run_pde_solver(config)
    payload = result.evidence_bundle["pde_solver"]
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
