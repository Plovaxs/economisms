"""Model zoo, tranche 5: two pipelines in which one model feeds the next.

Written down BEFORE the numbers were produced (the commit that adds this file has no results file).

The pipelines are in `modelzoo.pipelines`: (1) a neural-operator price surrogate, differentiated
into a
delta, run as a hedge along simulated stock paths, scored by `titan.risk_metrics`; (2) the simulated
`calibrated_banks` world's annual loss rates, whose Expected Shortfall is estimated by quantum
amplitude
estimation and by `titan.risk_metrics` from the same samples. Everything upstream is simulated.

What I had looked at before writing this: one run of each pipeline on development seeds
75900-75930. It
showed the surrogate price curve within about 4% in relative L2 on a 128-point grid it was not
trained on;
the surrogate-hedged profit-and-loss with about twice the standard deviation of the exact-delta
hedge
(1.86 against 0.91 on one seed of 1,000 paths) and a tail far below not hedging (expected
shortfall 4.1
against 45.7); a mean absolute delta error near 0.03; and the amplitude route and the direct route
to the
bank-loss Expected Shortfall agreeing to under 0.1% (1.4884 against 1.4889). Some claims below are
ones
that smoke run made look likely to fail (Z-I1).

Decision rules (`modelzoo.verdicts`): a size claim is judged on the median over seeds (SUPPORTED
at or
below the first threshold, CONTRADICTED above the second); a paired difference is SUPPORTED if its
95%
bootstrap interval lies wholly on the claimed side of zero.

SURROGATE HEDGE (5 seeds; a 3,000-sample, 40-epoch surrogate per seed; 2,000 paths, weekly
rebalancing, a
short at-the-money 1-year call, drift 5%, volatility 20%):
  Z-I1  The standard deviation of the hedging error with the surrogate's delta is at most 1.5
  times that of
        the exact Black-Scholes delta (contradicted above 3).
  Z-I2  The 95% Expected Shortfall of the surrogate-hedged loss is at most a quarter of the
  unhedged one
        (contradicted above a half).
  Z-I3  The surrogate's delta differs from the exact delta by at most 0.05 on average over the
  states
        visited (contradicted above 0.10).

BANK LOSSES TO QUANTUM RISK (40 simulated `calibrated_banks` paths, 720 annual loss rates; 64
bins; alpha
95%; 300 repetitions with 20 shots and Grover powers up to 2^6):
  Z-I4  The amplitude-based Expected Shortfall is within 2% of `titan.risk_metrics`' on the same
  samples
        (median over the repetitions of the relative gap; contradicted above 5%).
  Z-I5  At equal calls to the state preparation the amplitude route has a lower squared error than a
        plain Monte Carlo of the same bin distribution.
  Z-I6  The discretisation into 64 bins costs under 1% of the Expected Shortfall: the exact
  amplitude of
        the binned distribution, converted, is within 1% of the direct estimate.

Everything is simulated (stock paths, banks, an ideal quantum machine). Seeds 75000-75899 are
reserved for
this study.
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
import torch

from prometheus.modelzoo import pipelines as pl
from prometheus.modelzoo import quantum as qm
from prometheus.modelzoo.verdicts import summarise_difference, threshold_verdict
from prometheus.titan.risk_metrics import historical_expected_shortfall

OUTPUT = Path(__file__).resolve().parents[3] / "docs" / "numerics" / "modelzoo_pipelines.json"
HEDGE_SEEDS = tuple(range(75000, 75005))
BANK_SEEDS = tuple(range(75100, 75140))
REPETITIONS = 300


def hedge_study(
    seeds: tuple[int, ...] = HEDGE_SEEDS,
    *,
    samples: int = 3000,
    epochs: int = 40,
    paths: int = 2000,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for seed in seeds:
        model = pl.train_surface(
            pl.make_surface_data(samples, 64, seed=seed), epochs=epochs, seed=seed + 1
        )
        result = pl.run_hedge(model, seed=seed + 2, paths=paths)
        risk = {name: pl.hedge_risk(err) for name, err in result.errors.items()}
        rows.append(
            {"seed": seed, "risk": risk, "mean_abs_delta_error": result.mean_abs_delta_error}
        )
    ratio = float(
        np.median([r["risk"]["surrogate"]["std"] / r["risk"]["exact"]["std"] for r in rows])
    )
    tail = float(
        np.median(
            [
                r["risk"]["surrogate"]["expected_shortfall"]
                / r["risk"]["unhedged"]["expected_shortfall"]
                for r in rows
            ]
        )
    )
    gap = float(np.median([r["mean_abs_delta_error"] for r in rows]))
    return {
        "seeds": list(seeds),
        "rows": rows,
        "median_std_ratio_surrogate_to_exact": ratio,
        "median_tail_ratio_surrogate_to_unhedged": tail,
        "median_delta_gap": gap,
        "Z-I1": threshold_verdict(ratio, 1.5, 3.0),
        "Z-I2": threshold_verdict(tail, 0.25, 0.5),
        "Z-I3": threshold_verdict(gap, 0.05, 0.10),
    }


def bank_risk_study(
    seeds: tuple[int, ...] = BANK_SEEDS, *, repetitions: int = REPETITIONS, alpha: float = 0.95
) -> dict[str, Any]:
    samples = pl.bank_loss_samples(seeds)
    info = pl.loss_amplitude(samples, alpha)
    direct = float(historical_expected_shortfall(samples, alpha))
    exact_binned = info.expected_shortfall(info.distribution.amplitude)
    schedule = qm.mlae_schedule(6)
    rng = np.random.default_rng(75800)
    quantum, classical, calls = [], [], 0
    for _ in range(repetitions):
        q, calls = pl.quantum_expected_shortfall(info, schedule, 20, rng)
        quantum.append(q)
        classical.append(pl.monte_carlo_expected_shortfall(info, calls, rng))
    q_err = (np.array(quantum) - exact_binned) ** 2
    c_err = (np.array(classical) - exact_binned) ** 2
    relative_gap = float(np.median(np.abs(np.array(quantum) - direct) / direct))
    discretisation = abs(exact_binned - direct) / direct
    return {
        "samples": int(len(samples)),
        "alpha": alpha,
        "value_at_risk": info.value_at_risk,
        "direct_expected_shortfall": direct,
        "binned_expected_shortfall": exact_binned,
        "calls": calls,
        "rmse_quantum": math.sqrt(float(q_err.mean())),
        "rmse_monte_carlo": math.sqrt(float(c_err.mean())),
        "median_relative_gap_to_direct": relative_gap,
        "Z-I4": threshold_verdict(relative_gap, 0.02, 0.05),
        "Z-I5": summarise_difference(c_err - q_err),
        "Z-I6": "SUPPORTED" if discretisation < 0.01 else "CONTRADICTED",
        "Z-I6_discretisation_error": discretisation,
    }


STUDIES: dict[str, Callable[[], dict[str, Any]]] = {"hedge": hedge_study, "banks": bank_risk_study}


def main() -> int:
    parser = argparse.ArgumentParser(description="Model zoo tranche 5 (pipelines) study")
    parser.add_argument("family", choices=sorted(STUDIES))
    parser.add_argument("--threads", type=int, default=6)
    args = parser.parse_args()
    torch.set_num_threads(args.threads)
    start = time.perf_counter()
    result = STUDIES[args.family]()
    result["family"] = args.family
    result["wall_seconds"] = time.perf_counter() - start
    path = OUTPUT.with_name(f"modelzoo_pipelines_{args.family}.json")
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
