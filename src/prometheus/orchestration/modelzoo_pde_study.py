"""Model zoo, tranche 1: operator learning, continuous dynamics and mesh-free PDE solvers.

Written down BEFORE the numbers were produced (the commit that adds this file has no results file).

What I had looked at before writing this: a smoke run of each family on development seeds
70000-70070 (never used for an evaluation below), to see that the code ran and that the settings
were
sane. It showed, for one seed each: an MLP matching the FNO on the pricing operator, energy drift
lower
for the HNN and the SympNet than for the Neural ODE, state error not lower, a DGM within a few
percent
of the closed form, a finite-difference solve far better than Deep Ritz, and Deep Kolmogorov not
beating a plain Monte Carlo of the same budget. Several hypotheses below are ones that smoke run
made
look likely to fail. They are kept because they are the claims the literature makes, and the
verdict is
recorded whichever way it falls.

Decision rules (`modelzoo.verdicts`): a claim about a paired difference is SUPPORTED only if the 95%
bootstrap interval of its mean over seeds lies wholly on the claimed side of zero, CONTRADICTED if
wholly
on the other side, INCONCLUSIVE otherwise. A claim about a size ("at most x") is judged on the
median.

OPERATORS (8 seeds, 1,500 training portfolios of 1 to 3 calls on a 64-point grid, 40 epochs;
`modelzoo.operators`):
  Z-O1  Every learned operator (FNO, DeepONet, MLP) has median relative error at most 0.2 times
  that of
        the trivial answer "the price is the payoff" (contradicted if above 0.5).
  Z-O2  Complexity extrapolation. On portfolios of 6 to 8 calls (never seen in training) the FNO
  has a
        lower relative error than the MLP.
  Z-O3  In distribution (1 to 3 calls) the FNO has a lower relative error than the DeepONet.
  Z-O4  Resolution transfer. The ratio of a model's error on a 128-point grid to its error on the
        64-point grid it was trained on is smaller for the FNO than for the MLP (whose input and
        output
        are interpolated).

DYNAMICS (8 seeds, 2 systems, 2,000 training states, 2,000 rollout steps of dt = 0.1, about 30
periods; `modelzoo.dynamics`):
  Z-D1  After the rollout the HNN and the SympNet each have a lower relative energy drift than the
        Neural ODE, on both the pendulum and the Goodwin cycle (all four comparisons must hold).
  Z-D2  The SympNet map is symplectic: the largest |det J - 1| over 50 test points is at most 1e-4.
  Z-D3  Structure has a price in accuracy: the Neural ODE has a lower mean state error after 500
        steps than the SympNet, on both systems.

MESH-FREE SOLVERS (5 seeds, 3,000 steps each; `modelzoo.variational`; K = 1, r = 5%, sigma = 20%):
  Z-V1  DGM on the European put: median relative L2 error against the closed form over S in [0.5,
  1.5]
        at most 5% (contradicted if above 10%).
  Z-V2  DGM on the American put: median relative error against a 1,000-step binomial tree at most
  10%
        (contradicted if above 20%).
  Z-V3  Deep Ritz on the 2-D Poisson problem is beaten by a classical five-point finite-difference
        solve (31 interior points per side): the finite-difference error is lower in the mean.
  Z-V4  Deep Kolmogorov beats a plain Monte Carlo that spends the same number of simulated paths, on
        the geometric-mean option in d = 100 (the claim is made for 100 dimensions; 5 and 20 are
        reported and not judged).

Every number is a real run. This is one training seed per cell and small networks; none of it says
what
the same method does at the scale of the paper it is named after. Seeds 71000-71204 are reserved for
this study.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import torch

from prometheus.modelzoo import dynamics as dyn
from prometheus.modelzoo import operators as ops
from prometheus.modelzoo import variational as var
from prometheus.modelzoo.verdicts import summarise_difference, threshold_verdict

OPERATOR_SEEDS = tuple(range(71000, 71008))
DYNAMICS_SEEDS = tuple(range(71100, 71108))
VARIATIONAL_SEEDS = tuple(range(71200, 71205))
OUTPUT_DIR = Path(__file__).resolve().parents[3] / "docs" / "numerics"

OPERATOR_EPOCHS = 40
OPERATOR_TRAIN = 1500
DYNAMICS_STEPS = 2000
DT = 0.1
SOLVER_STEPS = 3000
KOLMOGOROV_STEPS = 1500
KOLMOGOROV_DIMENSIONS = (5, 20, 100)
TEST_POINTS = 100


def _combine(verdicts: list[str]) -> str:
    if all(v == "SUPPORTED" for v in verdicts):
        return "SUPPORTED"
    if any(v == "CONTRADICTED" for v in verdicts):
        return "CONTRADICTED"
    return "INCONCLUSIVE"


# ----- operators ----------------------------------------------------------------------------------


def operator_study(
    seeds: tuple[int, ...] = OPERATOR_SEEDS,
    *,
    epochs: int = OPERATOR_EPOCHS,
    n_train: int = OPERATOR_TRAIN,
    n_test: int = 300,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for seed in seeds:
        train = ops.make_operator_data(n_train, 64, seed=seed)
        in_dist = ops.make_operator_data(n_test, 64, seed=seed + 1000)
        fine = ops.make_operator_data(n_test, 128, seed=seed + 2000)
        hard = ops.make_operator_data(n_test, 64, seed=seed + 3000, min_kinks=6, max_kinks=8)
        row: dict[str, Any] = {
            "seed": seed,
            "trivial_in_distribution": ops.relative_l2(in_dist.payoff, in_dist.price),
        }
        for name in ("fno", "deeponet", "mlp"):
            model = ops.build_model(name, 64)
            fit = ops.train_operator(model, train, epochs=epochs, seed=seed + 5)
            row[name] = {
                "in_distribution": ops.relative_l2(ops.predict(model, in_dist), in_dist.price),
                "grid_128": ops.relative_l2(ops.predict(model, fine), fine.price),
                "six_to_eight_kinks": ops.relative_l2(ops.predict(model, hard), hard.price),
                "train_seconds": fit.seconds,
                "parameters": fit.parameters,
            }
        rows.append(row)

    def col(model: str, key: str) -> np.ndarray:
        return np.array([r[model][key] for r in rows])

    trivial = np.array([r["trivial_in_distribution"] for r in rows])
    o1 = {
        m: {
            "median_ratio_to_trivial": float(np.median(col(m, "in_distribution") / trivial)),
            "verdict": threshold_verdict(
                float(np.median(col(m, "in_distribution") / trivial)), 0.2, 0.5
            ),
        }
        for m in ("fno", "deeponet", "mlp")
    }
    ratio = {m: col(m, "grid_128") / col(m, "in_distribution") for m in ("fno", "mlp")}
    return {
        "seeds": list(seeds),
        "rows": rows,
        "Z-O1": _combine([str(v["verdict"]) for v in o1.values()]),
        "Z-O1_detail": o1,
        "Z-O2": summarise_difference(
            col("mlp", "six_to_eight_kinks") - col("fno", "six_to_eight_kinks")
        ),
        "Z-O3": summarise_difference(
            col("deeponet", "in_distribution") - col("fno", "in_distribution")
        ),
        "Z-O4": summarise_difference(ratio["mlp"] - ratio["fno"]),
        "medians": {
            m: {
                k: float(np.median(col(m, k)))
                for k in ("in_distribution", "grid_128", "six_to_eight_kinks")
            }
            for m in ("fno", "deeponet", "mlp")
        },
        "trivial_median": float(np.median(trivial)),
    }


# ----- dynamics -----------------------------------------------------------------------------------


def dynamics_study(
    seeds: tuple[int, ...] = DYNAMICS_SEEDS, *, epochs: int = 1500, steps: int = DYNAMICS_STEPS
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    defects: list[float] = []
    check = min(500, steps)
    for seed in seeds:
        for name, system in dyn.SYSTEMS.items():
            data = dyn.make_dynamics_data(system, 2000, DT, seed=seed)
            scores: dict[str, Any] = {}
            for kind in ("mlp", "hnn", "sympnet"):
                torch.manual_seed(seed + 7)
                model: Any = {"mlp": dyn.MLPField, "hnn": dyn.HNN, "sympnet": dyn.SympNet}[kind]()
                if kind == "sympnet":
                    dyn.train_map(model, data, epochs=epochs, seed=seed + 8)
                    if name == "pendulum":
                        defects.append(dyn.symplectic_defect(model, data.states[:50]))
                else:
                    dyn.train_field(model, data, epochs=epochs, seed=seed + 8)
                s = dyn.score_rollout(system, model, DT, steps, (100, check, steps))
                scores[kind] = {
                    "energy_drift": s.energy_drift,
                    "max_energy_drift": s.max_energy_drift,
                    "state_error": {str(k): v for k, v in s.state_error_at.items()},
                }
            rows.append({"seed": seed, "system": name, **scores})

    def col(system: str, kind: str, key: str) -> np.ndarray:
        return np.array([r[kind][key] for r in rows if r["system"] == system])

    def state(system: str, kind: str) -> np.ndarray:
        return np.array([r[kind]["state_error"][str(check)] for r in rows if r["system"] == system])

    d1 = {
        f"{system}:{kind}": summarise_difference(
            col(system, "mlp", "energy_drift") - col(system, kind, "energy_drift")
        )
        for system in dyn.SYSTEMS
        for kind in ("hnn", "sympnet")
    }
    d3 = {
        system: summarise_difference(state(system, "sympnet") - state(system, "mlp"))
        for system in dyn.SYSTEMS
    }
    worst = float(max(defects))
    return {
        "seeds": list(seeds),
        "rows": rows,
        "Z-D1": _combine([str(v["verdict"]) for v in d1.values()]),
        "Z-D1_detail": d1,
        "Z-D2": "SUPPORTED" if worst <= 1e-4 else "CONTRADICTED",
        "Z-D2_worst_defect": worst,
        "Z-D3": _combine([str(v["verdict"]) for v in d3.values()]),
        "Z-D3_detail": d3,
        "median_energy_drift": {
            f"{s}:{k}": float(np.median(col(s, k, "energy_drift")))
            for s in dyn.SYSTEMS
            for k in ("mlp", "hnn", "sympnet")
        },
    }


# ----- mesh-free solvers --------------------------------------------------------------------------


def variational_study(
    seeds: tuple[int, ...] = VARIATIONAL_SEEDS,
    *,
    solver_steps: int = SOLVER_STEPS,
    kolmogorov_steps: int = KOLMOGOROV_STEPS,
    dimensions: tuple[int, ...] = KOLMOGOROV_DIMENSIONS,
) -> dict[str, Any]:
    spots = np.linspace(0.5, 1.5, 21)
    european = var.bs_put(spots)
    american = var.american_put_reference(spots, 1000)
    grid = np.stack(
        np.meshgrid(np.linspace(0.05, 0.95, 19), np.linspace(0.05, 0.95, 19), indexing="ij"), -1
    ).reshape(-1, 2)
    poisson_truth = var.poisson_exact(grid)
    fd_points, fd_solution = var.poisson_finite_difference(31)
    fd_error = var.relative_l2_error(fd_solution, var.poisson_exact(fd_points))
    rows: list[dict[str, Any]] = []
    for seed in seeds:
        eu = var.train_dgm(american=False, steps=solver_steps, seed=seed)
        am = var.train_dgm(american=True, steps=solver_steps, seed=seed + 1)
        ritz_fit = var.train_deep_ritz(steps=solver_steps, seed=seed + 2)
        with torch.no_grad():
            ritz_pred = ritz_fit.net(torch.as_tensor(grid, dtype=torch.float32)).numpy()
        row: dict[str, Any] = {
            "seed": seed,
            "dgm_european_error": var.relative_l2_error(var.dgm_value(eu.net, spots), european),
            "dgm_american_error": var.relative_l2_error(var.dgm_value(am.net, spots), american),
            "ritz_error": var.relative_l2_error(ritz_pred, poisson_truth),
            "fd_error": fd_error,
            "dgm_seconds": eu.seconds,
            "ritz_seconds": ritz_fit.seconds,
            "kolmogorov": {},
        }
        for d in dimensions:
            k = var.train_deep_kolmogorov(d, steps=kolmogorov_steps, seed=seed + 10 + d)
            x = var.kolmogorov_test_points(d, TEST_POINTS, seed + 20)
            exact = var.geometric_basket_price(x)
            net_rmse = float(np.sqrt(np.mean((var.kolmogorov_predict(k, x) - exact) ** 2)))
            per_point = max(k.samples_used // TEST_POINTS, 1)
            mc_rmse = float(
                np.sqrt(np.mean((var.monte_carlo_estimate(x, per_point, seed + 30) - exact) ** 2))
            )
            row["kolmogorov"][str(d)] = {
                "net_rmse": net_rmse,
                "mc_same_budget_rmse": mc_rmse,
                "mc_paths_per_point": per_point,
                "train_seconds": k.seconds,
            }
        rows.append(row)

    eu_med = float(np.median([r["dgm_european_error"] for r in rows]))
    am_med = float(np.median([r["dgm_american_error"] for r in rows]))
    ritz = np.array([r["ritz_error"] for r in rows])
    fd = np.array([r["fd_error"] for r in rows])
    top = str(max(dimensions))
    d100 = np.array(
        [
            r["kolmogorov"][top]["mc_same_budget_rmse"] - r["kolmogorov"][top]["net_rmse"]
            for r in rows
        ]
    )
    return {
        "seeds": list(seeds),
        "rows": rows,
        "Z-V1": threshold_verdict(eu_med, 0.05, 0.10),
        "Z-V1_median": eu_med,
        "Z-V2": threshold_verdict(am_med, 0.10, 0.20),
        "Z-V2_median": am_med,
        "Z-V3": summarise_difference(ritz - fd),
        "Z-V4": summarise_difference(d100),
        "Z-V4_dimension": int(top),
    }


STUDIES: dict[str, Callable[[], dict[str, Any]]] = {
    "operators": operator_study,
    "dynamics": dynamics_study,
    "variational": variational_study,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Model zoo tranche 1 study")
    parser.add_argument("family", choices=sorted(STUDIES))
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    torch.set_num_threads(args.threads)
    start = time.perf_counter()
    result = STUDIES[args.family]()
    result["family"] = args.family
    result["wall_seconds"] = time.perf_counter() - start
    path = OUTPUT_DIR / f"modelzoo_pde_{args.family}.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
