"""Firms, a government, a foreign sector and bail-outs in the volatile world (PR-224).

Finding 25 left four things out of WORLDSIM: firms' balance sheets, fiscal policy, a foreign sector
and bail-outs. They are now in (switched on by `full_scenario`; with them off the world is the same
world as the one Finding 25 used, which a test pins). Seven questions and their decision rule were
written BEFORE the final run, each with its prediction, so a null or a surprise cannot be reframed
afterwards. All comparisons are paired across seeds (the random draws are the same in both arms) in
the `stressed_full` scenario unless noted:

  E-A  Does recapitalising failing banks reduce the number of failed banks? (predicted: yes)
  E-B  Does it raise public debt at the end of the run? (predicted: yes, it is paid for by the
         state)
  E-C  Does a counter-cyclical spending rule raise the worst output gap, against a balanced rule?
  E-D  Does foreign-currency bank debt raise the number of failed banks?
  E-E  In `volatile_full`, do firms (leverage builds in booms) raise the number of failed banks?
  E-F  Does a logistic early-warning model trained on 100 worlds beat the equal-weight composite on
         100 worlds it has not seen (AUC for "a crisis begins within 6 months")?
  E-G  Does the moral hazard of bail-outs (looser lending after injections) raise the total
         injected?

Decision rule: SUPPORTED if the whole 95% interval lies on the predicted side of zero, CONTRADICTED
if wholly on the other side, INCONCLUSIVE otherwise. Whatever comes out is reported, including the
oracle ceiling for
E-F (the AUC of knowing the true regime), the one-at-a-time sensitivity table and the calibration
       check.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from prometheus.confirmatory.intervals import t_interval
from prometheus.orchestration.worldsim_study import run_scenario, verdict
from prometheus.worldsim import calibration, learned_warning, monitor, sensitivity
from prometheus.worldsim.config import CRISIS, WorldConfig, full_scenario, scenario
from prometheus.worldsim.households import simulate_households
from prometheus.worldsim.world import simulate_world

N_SEEDS = 200
TRAIN_SEEDS = 100


def _row(args: tuple[WorldConfig, int]) -> dict[str, float]:
    config, seed = args
    path = simulate_world(config, seed)
    households = simulate_households(path, "equal_weight", config.households, seed)
    return {
        "failed_banks": float(path.bank_failed[-1].sum()),
        "min_output_gap": float(path.output_gap.min()),
        "debt_end": float(path.debt_ratio[-1]),
        "debt_max": float(path.debt_ratio.max()),
        "injection_total": float(path.injection.sum()),
        "peak_unemployment": float(path.unemployment.max()),
        "peak_inflation": float(path.inflation.max()),
        "crisis_share": float((path.regime == CRISIS).mean()),
        "gini_start": float(households.gini[0]),
        "gini_end": float(households.gini[-1]),
        "top10_end": float(households.top10_share[-1]),
    }


def run_arm(config: WorldConfig, seeds: Sequence[int], workers: int) -> dict[str, np.ndarray]:
    jobs = [(config, seed) for seed in seeds]
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            rows = list(pool.map(_row, jobs, chunksize=8))
    else:
        rows = [_row(job) for job in jobs]
    return {key: np.array([r[key] for r in rows]) for key in rows[0]}


def _paired(a: np.ndarray, b: np.ndarray, sign: float = 1.0) -> dict[str, Any]:
    """Interval for mean(a - b); `sign` = -1 flips it so positive means 'as predicted'."""
    interval = t_interval(sign * (a - b), 0.95).as_dict()
    return {**interval, "verdict": verdict(interval["low"], interval["high"])}


def _auc_difference(
    learned: list[np.ndarray],
    composite: list[np.ndarray],
    labels: list[np.ndarray],
    n_resamples: int = 500,
) -> dict[str, float]:
    rng = np.random.default_rng(11)
    n = len(labels)

    def difference(pick: np.ndarray) -> float:
        y = np.concatenate([labels[i] for i in pick])
        return monitor.auc(np.concatenate([learned[i] for i in pick]), y) - monitor.auc(
            np.concatenate([composite[i] for i in pick]), y
        )

    point = difference(np.arange(n))
    draws = [difference(rng.integers(0, n, size=n)) for _ in range(n_resamples)]
    finite = [d for d in draws if not np.isnan(d)]
    low, high = np.quantile(finite, [0.025, 0.975]) if finite else (np.nan, np.nan)
    return {"estimate": point, "low": float(low), "high": float(high), "confidence": 0.95}


def _sample_task(args: tuple[WorldConfig, int]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    config, seed = args
    path = simulate_world(config, seed)
    features, labels = learned_warning.sample_matrix(path)
    composite = monitor.indicators(path).composite
    months = [
        t
        for t in range(monitor.BURN_IN, path.n_months - monitor.HORIZON)
        if path.regime[t] != CRISIS and not np.isnan(composite[t])
    ]
    # the oracle knows the true regime: the ceiling for any monitor of these indicators
    oracle = np.array([float(path.regime[t] == 1) for t in months])
    return features, labels, oracle


def _samples(
    config: WorldConfig, seeds: Sequence[int], workers: int
) -> list[tuple[np.ndarray, np.ndarray, np.ndarray]]:
    jobs = [(config, seed) for seed in seeds]
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(_sample_task, jobs, chunksize=4))
    return [_sample_task(job) for job in jobs]


def warning_experiment(workers: int = 1, train_seeds: int = TRAIN_SEEDS) -> dict[str, Any]:
    config = full_scenario("volatile_full")
    train = _samples(config, range(train_seeds), workers)
    model = learned_warning.fit_logistic(
        np.vstack([x for x, _, _ in train]), np.concatenate([y for _, y, _ in train])
    )
    test = [
        sample
        for sample in _samples(config, range(train_seeds, 2 * train_seeds), workers)
        if sample[1].size
    ]
    composite_column = learned_warning.FEATURES.index("composite")
    learned = [model.score(x) for x, _, _ in test]
    composite = [x[:, composite_column] for x, _, _ in test]
    oracle = [o for _, _, o in test]
    labels = [y for _, y, _ in test]
    pooled_y = np.concatenate(labels)
    difference = _auc_difference(learned, composite, labels)
    return {
        "n_train_samples": int(sum(x.shape[0] for x, _, _ in train)),
        "n_test_samples": int(pooled_y.size),
        "test_samples_before_a_crisis": int(pooled_y.sum()),
        "auc_learned": monitor.auc(np.concatenate(learned), pooled_y),
        "auc_composite": monitor.auc(np.concatenate(composite), pooled_y),
        "auc_oracle_knows_the_regime": monitor.auc(np.concatenate(oracle), pooled_y),
        "learned_minus_composite": difference,
        "verdict": verdict(difference["low"], difference["high"]),
        "weights": dict(
            zip(learned_warning.FEATURES, (float(w) for w in model.weights), strict=True)
        ),
    }


def run_study(
    n_seeds: int = N_SEEDS,
    workers: int = 1,
    sensitivity_seeds: int = 40,
    train_seeds: int = TRAIN_SEEDS,
) -> dict[str, Any]:
    seeds = list(range(n_seeds))
    stressed = {
        mode: full_scenario("stressed_full", mode=mode)
        for mode in ("none", "liquidity", "recapitalise")
    }
    arms = {
        "stressed_full/none": run_arm(stressed["none"], seeds, workers),
        "stressed_full/liquidity": run_arm(stressed["liquidity"], seeds, workers),
        "stressed_full/recapitalise": run_arm(stressed["recapitalise"], seeds, workers),
    }
    base = stressed["none"]
    no_cc = replace(base, fiscal=replace(base.fiscal, countercyclical=0.0))
    no_fx = replace(base, foreign=replace(base.foreign, bank_fx_debt_share=0.0))
    recap = stressed["recapitalise"]
    no_mh = replace(recap, policy=replace(recap.policy, moral_hazard=0.0))
    volatile_full = full_scenario("volatile_full")
    no_firms = replace(volatile_full, firms=replace(volatile_full.firms, enabled=False))
    arms["stressed_full/none, no counter-cyclical rule"] = run_arm(no_cc, seeds, workers)
    arms["stressed_full/none, no FX debt"] = run_arm(no_fx, seeds, workers)
    arms["stressed_full/recapitalise, no moral hazard"] = run_arm(no_mh, seeds, workers)
    arms["volatile_full/none"] = run_arm(volatile_full, seeds, workers)
    arms["volatile_full/none, no firms"] = run_arm(no_firms, seeds, workers)
    arms["volatile (Finding 25 world)"] = run_arm(scenario("volatile"), seeds, workers)

    none, recap_arm = arms["stressed_full/none"], arms["stressed_full/recapitalise"]
    vol, vol_nf = arms["volatile_full/none"], arms["volatile_full/none, no firms"]
    hypotheses = {
        "E-A_recapitalisation_reduces_failed_banks": _paired(
            none["failed_banks"], recap_arm["failed_banks"]
        ),
        "E-B_recapitalisation_raises_public_debt_at_the_end": _paired(
            recap_arm["debt_end"], none["debt_end"]
        ),
        "E-C_counter_cyclical_rule_raises_the_worst_output_gap": _paired(
            none["min_output_gap"],
            arms["stressed_full/none, no counter-cyclical rule"]["min_output_gap"],
        ),
        "E-D_foreign_currency_bank_debt_raises_failed_banks": _paired(
            none["failed_banks"], arms["stressed_full/none, no FX debt"]["failed_banks"]
        ),
        "E-E_firm_leverage_raises_failed_banks_volatile_full": _paired(
            vol["failed_banks"], vol_nf["failed_banks"]
        ),
        "E-G_moral_hazard_raises_the_total_injected": _paired(
            recap_arm["injection_total"],
            arms["stressed_full/recapitalise, no moral hazard"]["injection_total"],
        ),
    }
    warning = warning_experiment(workers, train_seeds)
    hypotheses["E-F_learned_warning_beats_the_composite_out_of_sample"] = {
        "verdict": warning["verdict"],
        "learned_minus_composite": warning["learned_minus_composite"],
    }

    summary = {
        name: {
            "mean_failed_banks": float(a["failed_banks"].mean()),
            "share_of_runs_with_failure": float((a["failed_banks"] > 0).mean()),
            "mean_min_output_gap": float(a["min_output_gap"].mean()),
            "mean_peak_unemployment": float(a["peak_unemployment"].mean()),
            "mean_peak_inflation": float(a["peak_inflation"].mean()),
            "mean_debt_end": float(a["debt_end"].mean()),
            "mean_debt_max": float(a["debt_max"].mean()),
            "mean_injection": float(a["injection_total"].mean()),
            "mean_crisis_share": float(a["crisis_share"].mean()),
            "mean_gini_start": float(a["gini_start"].mean()),
            "mean_gini_end": float(a["gini_end"].mean()),
            "mean_top10_share_end": float(a["top10_end"].mean()),
        }
        for name, a in arms.items()
    }
    facts = run_scenario(scenario("volatile"), seeds[:100])["stylised_facts"]
    return {
        "study": "worldsim_extended_study (PR-224)",
        "n_seeds": n_seeds,
        "arms": summary,
        "hypotheses": hypotheses,
        "early_warning": warning,
        "calibration_of_the_volatile_scenario": calibration.check(facts),
        "sensitivity_stressed_full_25_percent_moves": sensitivity.tornado(
            base, seeds[:sensitivity_seeds], workers=workers
        ),
        "caveats": [
            "A simulation with chosen, not estimated, parameters: results describe the simulator.",
            "The crisis regime is an exogenous random switch; bail-outs cannot change how often "
            "crises start, only what they do to banks and output.",
            "Firms are one aggregate leverage ratio, the government one budget, the foreign sector "
            "one "
            "exchange rate; no sectoral detail, no trade partners, no default on sovereign debt.",
            "Bank rescue is mechanical (inject up to a target ratio); real rescues involve "
            "negotiation, conditionality and political limits.",
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--seeds", type=int, default=N_SEEDS)
    parser.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 1))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.seeds < 4 or args.workers < 1:
        parser.error("--seeds must be at least 4 and --workers at least 1")
    report = run_study(args.seeds, args.workers)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
