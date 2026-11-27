"""Model zoo, tranche 4: quantum algorithms and tensor trains, on ideal simulators.

Written down BEFORE the numbers were produced (the commit that adds this file has no results file).

Nothing here uses quantum hardware. `modelzoo.quantum` is a state-vector simulator of at most eight
qubits (the reservoir uses a five-qubit density matrix); the only noise is the depolarising model
of Z-Q3.
The claims are about algorithms measured against the resource they are charged for, not about
devices.

What I had looked at before writing this: one run of each component on development seeds
74900-74910, to
see that the code ran. It showed: the Grover iteration matching sin^2((2k+1) theta) exactly;
maximum-
likelihood amplitude estimation with a lower error than Monte Carlo at equal calls (about 0.0007
against
0.0023 at 10,000 calls); QAOA reaching an approximation ratio near 0.96 at every depth with the
optimal
bitstring carrying under 1% of the probability; the parameter-shift gradient matching finite
differences
to 1e-9; a four-layer VQE within 0.01% of the exact ground energy on one seed; and, for the tensor
train,
the kinked arithmetic-basket payoff NOT low-rank (maximum rank 36 at d = 4, 143 at d = 7) while its
softplus-smoothed version saturated (21 and 23). Some claims below are ones that smoke run made look
likely to fail.

Decision rules (`modelzoo.verdicts`): a paired difference is SUPPORTED if its 95% bootstrap
interval lies
wholly on the claimed side of zero, CONTRADICTED if wholly on the other, INCONCLUSIVE otherwise; a
size
claim is judged on the median.

AMPLITUDE ESTIMATION (option on a 64-point lognormal; schedules with powers up to 2^3 .. 2^7, 20
shots
each, 300 repetitions per size; charged per call to the state preparation; `modelzoo.quantum`):
  Z-Q1  The log-log slope of the ideal estimator's RMSE against calls is steeper than -0.75 (a
  quadratic
        speed-up would be -1; plain Monte Carlo is -0.5).
  Z-Q2  The Monte Carlo slope lies between -0.6 and -0.4.
  Z-Q3  With a 1% chance per call that the qubits are scrambled (which the estimator is not told
  about),
        the quantum estimator's mean squared error at the largest budget is higher than Monte
        Carlo's:
        the advantage is gone.

QAOA (20 simulated 8-asset, choose-4 portfolio QUBOs; depth 1 to 3; 4 restarts):
  Z-Q4  At depth 3 the median approximation ratio, (worst - achieved) / (worst - optimum), is at
  least
        0.95 (contradicted below 0.85).
  Z-Q5  At depth 3 the median probability of measuring the optimal bitstring is at least 10 times
  the
        uniform probability 1/256.
  Z-Q6  Depth 3 has a higher approximation ratio than depth 1 (paired over the 20 instances).

VQE (6-qubit transverse-field Ising chain at the critical field; 10 initialisations):
  Z-Q7  With 4 layers the median relative energy error is at most 1% (contradicted above 5%).
  Z-Q8  The parameter-shift gradient equals a central finite difference to within 1e-6.
  Z-Q9  Four layers reach a lower energy error than one layer (paired over initialisations).

QUANTUM RESERVOIR (5 seeds; Mackey-Glass, forecast 10 steps ahead; 1,500 training and 1,000 test
points;
20 measured observables plus a constant):
  Z-Q10 The quantum reservoir's NRMSE is lower than a linear autoregression on the last 5 values.
  Z-Q11 The quantum reservoir's NRMSE is lower than an echo-state network with 20 nodes.

TENSOR TRAIN (9 Gauss-Hermite nodes per axis, d = 3 .. 7, tolerance 1e-8; `modelzoo.tensornet`):
  Z-T1  Rank saturation: for the smoothed basket payoff the maximum TT rank at d = 7 is at most
  1.5 times
        that at d = 4, while for the kinked payoff it is at least 2 times. Both halves must hold.
  Z-T2  The TT integral equals the full-table quadrature to a relative 1e-6 for both payoffs at
  every d.
  Z-T3  For the kinked payoff at d = 7 the tensor train has at most 20% of the parameters of the
  full table.

Everything is simulated or synthetic: option on a model distribution, random portfolios, an Ising
chain,
a chaotic equation, a payoff grid. Seeds 74000-74999 are reserved for this study.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from prometheus.modelzoo import quantum as qm
from prometheus.modelzoo import tensornet as tn
from prometheus.modelzoo.verdicts import summarise_difference, threshold_verdict

OUTPUT_DIR = Path(__file__).resolve().parents[3] / "docs" / "numerics"
AMPLITUDE_SIZES = (3, 4, 5, 6, 7)
SHOTS = 20
REPETITIONS = 300
DEPOLARISING = 0.01


def _slope(calls: list[float], errors: list[float]) -> float:
    return float(np.polyfit(np.log(calls), np.log(errors), 1)[0])


def amplitude_study(
    *, repetitions: int = REPETITIONS, sizes: tuple[int, ...] = AMPLITUDE_SIZES, seed: int = 74000
) -> dict[str, Any]:
    dist = qm.option_distribution(6)
    truth = dist.amplitude
    rng = np.random.default_rng(seed)
    rows: list[dict[str, Any]] = []
    for m in sizes:
        schedule = qm.mlae_schedule(m)
        ideal, noisy, mc = [], [], []
        calls = 0
        for _ in range(repetitions):
            est, calls = qm.mlae_estimate(truth, schedule, SHOTS, rng)
            ideal.append((est - truth) ** 2)
            est_n, _ = qm.mlae_estimate(truth, schedule, SHOTS, rng, depolarising=DEPOLARISING)
            noisy.append((est_n - truth) ** 2)
            mc.append((qm.monte_carlo_amplitude(dist, calls, rng) - truth) ** 2)
        rows.append(
            {
                "max_power": m,
                "calls": calls,
                "rmse_ideal": math.sqrt(float(np.mean(ideal))),
                "rmse_noisy": math.sqrt(float(np.mean(noisy))),
                "rmse_monte_carlo": math.sqrt(float(np.mean(mc))),
                "squared_error_noisy_minus_mc": [n - c for n, c in zip(noisy, mc, strict=True)],
            }
        )
    calls_list = [float(r["calls"]) for r in rows]
    slope_ideal = _slope(calls_list, [r["rmse_ideal"] for r in rows])
    slope_mc = _slope(calls_list, [r["rmse_monte_carlo"] for r in rows])
    last = rows[-1]["squared_error_noisy_minus_mc"]
    z3 = summarise_difference(np.array(last))
    for r in rows:
        del r["squared_error_noisy_minus_mc"]
    return {
        "amplitude": truth,
        "rows": rows,
        "slope_ideal": slope_ideal,
        "slope_monte_carlo": slope_mc,
        "slope_noisy": _slope(calls_list, [r["rmse_noisy"] for r in rows]),
        "Z-Q1": "SUPPORTED" if slope_ideal < -0.75 else "CONTRADICTED",
        "Z-Q2": "SUPPORTED" if -0.6 <= slope_mc <= -0.4 else "CONTRADICTED",
        "Z-Q3": z3,
    }


def qaoa_study(*, instances: int = 20, seed: int = 74100) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for i in range(instances):
        qubo = qm.make_portfolio_qubo(8, 4, seed=seed + i)
        row: dict[str, Any] = {"instance": seed + i}
        for depth in (1, 2, 3):
            r = qm.run_qaoa(qubo, depth, seed=seed + 500 + i)
            row[f"p{depth}"] = {
                "approximation_ratio": r.approximation_ratio,
                "optimum_probability": r.optimum_probability,
            }
        rows.append(row)
    ratio3 = float(np.median([r["p3"]["approximation_ratio"] for r in rows]))
    prob3 = float(np.median([r["p3"]["optimum_probability"] for r in rows]))
    uniform = 1.0 / 256.0
    return {
        "rows": rows,
        "median_ratio_depth3": ratio3,
        "median_optimum_probability_depth3": prob3,
        "Z-Q4": threshold_verdict(-ratio3, -0.95, -0.85),
        "Z-Q5": "SUPPORTED" if prob3 >= 10 * uniform else "CONTRADICTED",
        "Z-Q6": summarise_difference(
            [r["p3"]["approximation_ratio"] - r["p1"]["approximation_ratio"] for r in rows]
        ),
    }


def vqe_study(*, seeds: int = 10, seed: int = 74200, n: int = 6) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for i in range(seeds):
        row: dict[str, Any] = {"seed": seed + i}
        for layers in (1, 4):
            energy, exact = qm.run_vqe(n, layers, seed=seed + i)
            row[f"layers{layers}"] = abs(energy - exact) / abs(exact)
        rows.append(row)
    hamiltonian = qm.ising_hamiltonian(n)
    params = np.random.default_rng(seed + 99).uniform(-1, 1, 5 * n)
    grad = qm.parameter_shift_gradient(params, hamiltonian, n, 4)
    eye = np.eye(len(params))
    fd = np.array(
        [
            (
                qm.vqe_energy(params + 1e-6 * eye[j], hamiltonian, n, 4)
                - qm.vqe_energy(params - 1e-6 * eye[j], hamiltonian, n, 4)
            )
            / 2e-6
            for j in range(len(params))
        ]
    )
    worst = float(np.abs(grad - fd).max())
    median4 = float(np.median([r["layers4"] for r in rows]))
    return {
        "rows": rows,
        "median_relative_error_4_layers": median4,
        "Z-Q7": threshold_verdict(median4, 0.01, 0.05),
        "Z-Q8": "SUPPORTED" if worst <= 1e-6 else "CONTRADICTED",
        "Z-Q8_worst_gradient_difference": worst,
        "Z-Q9": summarise_difference([r["layers1"] - r["layers4"] for r in rows]),
    }


def _best_penalty(feat: np.ndarray, target: np.ndarray, fit: slice, val: slice) -> float:
    """Ridge penalty with the lowest error on the validation rows (the test rows are never used)."""

    def error(lam: float) -> float:
        weights = qm.ridge_readout(feat[fit], target[fit], lam)
        return float(np.mean((feat[val] @ weights - target[val]) ** 2))

    return min((1e-8, 1e-6, 1e-4, 1e-2, 1.0), key=error)


def reservoir_study(
    *, seeds: int = 5, seed: int = 74300, horizon: int = 10, length: int = 3000
) -> dict[str, Any]:
    washout, train_end, test_end = 100, 1600, 2600
    rows: list[dict[str, Any]] = []
    for i in range(seeds):
        series = qm.mackey_glass(length, seed=seed + i)
        u = (series - series.min()) / (series.max() - series.min())
        target = np.roll(u, -horizon)  # value `horizon` steps ahead
        features = {
            "quantum": qm.QuantumReservoir(seed=seed + i).run(u),
            "esn": qm.echo_state_features(u, 20, seed=seed + 50 + i),
            "ar5": qm.autoregressive_features(u, 5),
        }
        scores = {}
        for name, feat in features.items():
            fit_rows = slice(washout, train_end - 300)
            val_rows = slice(train_end - 300, train_end)
            best = _best_penalty(feat, target, fit_rows, val_rows)
            weights = qm.ridge_readout(feat[washout:train_end], target[washout:train_end], best)
            scores[name] = qm.nrmse(feat[train_end:test_end] @ weights, target[train_end:test_end])
        rows.append({"seed": seed + i, **scores})

    def col(key: str) -> list[float]:
        return [float(r[key]) for r in rows]

    return {
        "rows": rows,
        "mean_nrmse": {k: float(np.mean(col(k))) for k in ("quantum", "esn", "ar5")},
        "Z-Q10": summarise_difference(
            [a - q for a, q in zip(col("ar5"), col("quantum"), strict=True)]
        ),
        "Z-Q11": summarise_difference(
            [e - q for e, q in zip(col("esn"), col("quantum"), strict=True)]
        ),
    }


def tensor_study(
    *, dimensions: tuple[int, ...] = (3, 4, 5, 6, 7), nodes: int = 9
) -> dict[str, Any]:
    out: dict[str, Any] = {"rows": []}
    worst_integral_error = 0.0
    for d in dimensions:
        row: dict[str, Any] = {"d": d, "full_size": nodes**d}
        for label, smoothing in (("kinked", 0.0), ("smooth", 0.2)):
            tensor, weights = tn.basket_payoff_tensor(d, nodes, smoothing=smoothing)
            cores = tn.tt_svd(tensor, 1e-8)
            full = _full_integral(tensor, weights)
            tt = tn.tt_integrate(cores, weights)
            error = abs(tt - full) / abs(full)
            worst_integral_error = max(worst_integral_error, error)
            row[label] = {
                "max_rank": max(tn.tt_ranks(cores)),
                "ranks": tn.tt_ranks(cores),
                "parameters": tn.tt_parameters(cores),
                "integral_tt": tt,
                "integral_full": full,
                "relative_integral_error": error,
            }
        out["rows"].append(row)
    by_d = {r["d"]: r for r in out["rows"]}
    smooth_growth = by_d[7]["smooth"]["max_rank"] / by_d[4]["smooth"]["max_rank"]
    kinked_growth = by_d[7]["kinked"]["max_rank"] / by_d[4]["kinked"]["max_rank"]
    share = by_d[7]["kinked"]["parameters"] / by_d[7]["full_size"]
    out.update(
        {
            "smooth_rank_growth_4_to_7": smooth_growth,
            "kinked_rank_growth_4_to_7": kinked_growth,
            "Z-T1": "SUPPORTED"
            if smooth_growth <= 1.5 and kinked_growth >= 2.0
            else "CONTRADICTED",
            "Z-T2": "SUPPORTED" if worst_integral_error <= 1e-6 else "CONTRADICTED",
            "Z-T2_worst_relative_error": worst_integral_error,
            "Z-T3": "SUPPORTED" if share <= 0.20 else "CONTRADICTED",
            "Z-T3_parameter_share": share,
        }
    )
    return out


def _full_integral(tensor: np.ndarray, weights: np.ndarray) -> float:
    value = tensor
    for _ in range(tensor.ndim):
        value = np.tensordot(value, weights, axes=([0], [0]))
    return float(value)


STUDIES: dict[str, Callable[[], dict[str, Any]]] = {
    "amplitude": amplitude_study,
    "qaoa": qaoa_study,
    "vqe": vqe_study,
    "reservoir": reservoir_study,
    "tensor": tensor_study,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Model zoo tranche 4 study")
    parser.add_argument("family", choices=sorted(STUDIES))
    args = parser.parse_args()
    start = time.perf_counter()
    result = STUDIES[args.family]()
    result["family"] = args.family
    result["wall_seconds"] = time.perf_counter() - start
    path = OUTPUT_DIR / f"modelzoo_quantum_{args.family}.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
