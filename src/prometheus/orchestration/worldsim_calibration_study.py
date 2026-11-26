"""Finding 28: WORLDSIM with parameters estimated from real data (study).

Real data (all in `data_cache/`, Kaggle sources already used elsewhere in the repository): S&P 500
monthly price returns 1928-2023, and monthly US unemployment, CPI inflation, the federal funds rate
and bank credit 1960-2023, plus quarterly real GDP growth for Okun's coefficient.

The design is fixed before the numbers are read:

1. Estimate every calibratable parameter on 1960-1999 only (`real_calibration`: a hidden Markov
   model for equity regimes, Okun's coefficient, indirect inference for the macro block and for
   bank lending).
2. Hypothesis K-A (out of sample): on the held-out months 2000-2023, the calibrated world is closer
   to the real data than the chosen `volatile` scenario, in the sum of squared standardised moment
   gaps (19 moments); SUPPORTED if the 95% interval of the paired difference over block bootstraps
   of the real data lies above zero, CONTRADICTED if below, otherwise INCONCLUSIVE.
3. Hypothesis K-B (untargeted statistics): of seven statistics no stage targeted (volatility
   clustering, worst month, recession depth, tail of the unemployment gap, equity/unemployment
   co-movement, rate-change volatility, inflation skew), the calibrated world's value lies inside
   the 95% bootstrap interval of the real 2000-2023 value for at least five (SUPPORTED), at most two
   (CONTRADICTED), otherwise INCONCLUSIVE.
4. Re-estimate on all months (this is the set of constants shipped as `calibrated`) and ask
   Hypothesis K-C (robustness of Finding 27): in the calibrated connected world the share of
   shock-to-outcome cells whose 95% interval excludes zero exceeds the share in the same world
   with the links off by at least 0.20 (SUPPORTED); is not larger (CONTRADICTED); otherwise
   INCONCLUSIVE.

Both runs measure Finding 27's robustness (K-C) on 240-month worlds, the length every WORLDSIM
scenario has; the estimation worlds are as long as the real sample (about 750 months) and the
first version of this script ran the robustness check on those by mistake, which let public debt in
the links-off world run away in a few paths (see the results document).

Revision 2 (written after the first run's results were read, before the second run's): the first
run (`--output-gap-anchor` off) answered K-A with CONTRADICTED and produced an output gap with a
standard deviation of about 4 points and a minimum of about -20, because nothing in the data
pinned down the size of the model's output gap: Okun's coefficient came from a regression of the
quarterly change in unemployment on annualised growth, which is attenuated, so the unemployment
moments could be matched with an output gap several times too large. The revision gives the gap a
data anchor: the real output gap is the Hodrick-Prescott cycle (smoothing 1600) of cumulated
quarterly real GDP growth (1954-2016), Okun's coefficient is the slope of the quarterly
unemployment gap on it, and its standard deviation joins the targeted moments (`ygap_sd`, the
simulated gap seen through the same quarterly filter). The three hypotheses are re-asked, with the
same rules, as K-A2, K-B2 and K-C2, together with a sanity rule:

- K-S (sanity): in both the plain and the connected world built from the final estimates, the
  mean standard deviation of the output gap over 20 paths lies in [1.0, 4.0] points, no path
  fails numerically, and no macro parameter sits within 1% of the width of its bounds of either
  bound. SUPPORTED if all three hold, otherwise CONTRADICTED.

The simulated side uses common random numbers (the same seeds for every candidate), so differences
between candidates are not simulation noise. Standard errors of the real moments come from 200
moving-block bootstraps (block 24 months) of the table of monthly rows.
"""

from __future__ import annotations

import argparse
import json
import math
import pickle
import sys
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import minimize

from prometheus.confirmatory.intervals import t_interval
from prometheus.data_ingestion.kaggle_sp500 import load_sp500_closes
from prometheus.data_ingestion.snapshot_integrity import verified_dict_reader
from prometheus.recessionnet.labels import is_recession_month
from prometheus.titan.contagion import ContagionError
from prometheus.worldsim.config import (
    WorldConfig,
    connected,
    scenario,
)
from prometheus.worldsim.impulse import impulse_matrix
from prometheus.worldsim.real_calibration import (
    BURN_IN,
    CREDIT_MOMENTS,
    CREDIT_PARAMETERS,
    EQUITY_MOMENTS,
    MACRO_MOMENTS,
    MACRO_PARAMETERS,
    UNTARGETED_MOMENTS,
    HmmFit,
    all_moments,
    apply_credit,
    apply_direct,
    apply_macro,
    block_bootstrap_indices,
    bootstrap_moments,
    build_table,
    distance,
    fit_gaussian_hmm,
    hp_gap,
    okun_coefficient,
    okun_gap_coefficient,
    quarterly_output_gap,
    simulated_moments,
    standard_errors,
)
from prometheus.worldsim.world import simulate_world

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data_cache"
OUTPUT = ROOT / "docs" / "numerics" / "worldsim_calibration_study.json"
OUTPUT_V2 = ROOT / "docs" / "numerics" / "worldsim_calibration_study_v2.json"
GDP_BLOCK = 8

TRAIN_END = (1999, 12)
TEST_START = (2000, 1)
DATA_END = (2023, 1)
SCENARIO_MONTHS = 240
NUMERIC_ERRORS = (ValueError, ArithmeticError, ContagionError)
CREDIT_START = (1974, 2)
EQUITY_SEEDS = tuple(range(51_000, 51_018))
TEST_SEEDS = tuple(range(52_000, 52_040))
ROBUST_SEEDS = tuple(range(53_000, 53_040))
BLOCK = 24
SIGNIFICANCE_GAP = 0.20
HYPOTHESIS_UNTARGETED_SUPPORT = 5
HYPOTHESIS_UNTARGETED_CONTRADICT = 2
OOS_MOMENTS = MACRO_MOMENTS + EQUITY_MOMENTS + CREDIT_MOMENTS


# --------------------------------------------------------------------------- real data


def _month_key(code: str) -> tuple[int, int]:
    return int(code[:4]), int(code[4:6])


def load_real_data(root: Path = DATA) -> dict[str, Any]:
    """Aligned monthly arrays 1960-01 .. 2023-01 and the longer equity series."""
    keys: list[tuple[int, int]] = []
    columns: dict[str, list[float]] = {"UNRATE": [], "CPI_YOY_SA": [], "FEDFUNDS": [], "CREDIT": []}
    path = root / "kaggle_us_macro_extended_monthly.csv"
    required = ("date", "UNRATE", "CPI_YOY_SA", "FEDFUNDS", "BANK_CREDIT_YOY")
    for row in verified_dict_reader(path, required=required):
        keys.append(_month_key(row["date"]))
        columns["UNRATE"].append(float(row["UNRATE"]))
        columns["CPI_YOY_SA"].append(float(row["CPI_YOY_SA"]))
        columns["FEDFUNDS"].append(float(row["FEDFUNDS"]))
        credit = row["BANK_CREDIT_YOY"]
        columns["CREDIT"].append(float(credit) if credit != "" else math.nan)

    dates, closes = load_sp500_closes(root / "kaggle_sp500_spliced_daily_close.csv")
    month_end: dict[tuple[int, int], float] = {}
    for d, c in zip(dates, closes, strict=True):
        month_end[(d.year, d.month)] = float(c)
    ordered = sorted(month_end)
    equity_keys = ordered[1:]
    equity = {
        ordered[i]: month_end[ordered[i]] / month_end[ordered[i - 1]] - 1.0
        for i in range(1, len(ordered))
    }

    gdp_keys: list[tuple[int, int]] = []
    gdp_growth: list[float] = []
    unemployment_by_month: dict[tuple[int, int], float] = {}
    policy = root / "kaggle_fed_policy_monthly.csv"
    for row in verified_dict_reader(policy, required=("date", "UNRATE", "REAL_GDP_GROWTH")):
        key = _month_key(row["date"])
        unemployment_by_month[key] = float(row["UNRATE"])
        if row["REAL_GDP_GROWTH"] != "":
            gdp_keys.append(key)
            gdp_growth.append(float(row["REAL_GDP_GROWTH"]))
    quarter_changes: list[float] = []
    quarter_growth: list[float] = []
    for key, growth in zip(gdp_keys, gdp_growth, strict=True):
        year, month = key
        later = (year + (month + 2) // 12, (month + 2) % 12 + 1)
        if later in unemployment_by_month:
            quarter_changes.append(unemployment_by_month[later] - unemployment_by_month[key])
            quarter_growth.append(growth)

    return {
        "keys": keys,
        "unemployment": np.array(columns["UNRATE"]),
        "inflation": np.array(columns["CPI_YOY_SA"]),
        "fed_funds": np.array(columns["FEDFUNDS"]),
        "credit": np.array(columns["CREDIT"]),
        "equity_keys": equity_keys,
        "equity": equity,
        "gdp_keys": gdp_keys,
        "gdp_growth": np.array(gdp_growth),
        "gdp_unemployment": np.array([unemployment_by_month[k] for k in gdp_keys]),
        "okun_delta_u": np.array(quarter_changes),
        "okun_growth": np.array(quarter_growth),
    }


def slice_data(
    data: dict[str, Any], start: tuple[int, int], end: tuple[int, int]
) -> dict[str, Any]:
    keys = data["keys"]
    keep = [i for i, k in enumerate(keys) if start <= k <= end]
    lo, hi = keep[0], keep[-1] + 1
    chosen = keys[lo:hi]
    return {
        "keys": chosen,
        "unemployment": data["unemployment"][lo:hi],
        "inflation": data["inflation"][lo:hi],
        "fed_funds": data["fed_funds"][lo:hi],
        "credit": data["credit"][lo:hi],
        "equity": np.array([data["equity"][k] for k in chosen]),
    }


def real_table(piece: dict[str, Any]) -> dict[str, np.ndarray]:
    return build_table(
        piece["unemployment"],
        piece["inflation"],
        piece["fed_funds"],
        piece["equity"],
        piece["credit"],
    )


def equity_history(data: dict[str, Any], end: tuple[int, int]) -> np.ndarray:
    return np.array([data["equity"][k] for k in data["equity_keys"] if k <= end])


def nber_share(keys: list[tuple[int, int]]) -> float:
    flags = [is_recession_month(date(y, m, 1)) for y, m in keys]
    return float(np.mean(flags))


# --------------------------------------------------------------------------- simulation helpers


def _moments_task(args: tuple[WorldConfig, int]) -> dict[str, float]:
    config, seed = args
    with np.errstate(all="ignore"):
        return simulated_moments(simulate_world(config, seed))


class Simulator:
    """Average simulated moments over a fixed set of seeds, in parallel when given a pool."""

    def __init__(self, pool: ProcessPoolExecutor | None) -> None:
        self.pool = pool

    def moments(self, config: WorldConfig, seeds: Sequence[int]) -> dict[str, float]:
        jobs = [(config, seed) for seed in seeds]
        rows = (
            list(self.pool.map(_moments_task, jobs))
            if self.pool
            else list(map(_moments_task, jobs))
        )
        names = rows[0].keys()
        return {
            name: float(
                np.nanmean([row[name] for row in rows if math.isfinite(row[name])] or [np.nan])
            )
            for name in names
        }


def _with_length(config: WorldConfig, real_months: int) -> WorldConfig:
    return replace(config, n_months=real_months + BURN_IN)


# --------------------------------------------------------------------------- estimation


def _unit(values: dict[str, float], spec: tuple[tuple[str, float, float], ...]) -> np.ndarray:
    return np.array([(values[n] - lo) / (hi - lo) for n, lo, hi in spec])


def _from_unit(x: np.ndarray, spec: tuple[tuple[str, float, float], ...]) -> dict[str, float]:
    return {
        n: float(lo + np.clip(v, 0.0, 1.0) * (hi - lo))
        for (n, lo, hi), v in zip(spec, x, strict=True)
    }


def _chosen_values(config: WorldConfig) -> dict[str, float]:
    m = config.macro
    return {
        "output_persistence": m.output_persistence,
        "inflation_persistence": m.inflation_persistence,
        "phillips_slope": m.phillips_slope,
        "inflation_vol": m.inflation_vol,
        "taylor_phi_pi": m.taylor_phi_pi,
        "taylor_phi_y": m.taylor_phi_y,
        "rate_smoothing": m.rate_smoothing,
        "output_vol_scale": 1.0,
        "output_shift_scale": 1.0,
    }


def _credit_start(config: WorldConfig) -> dict[str, float]:
    return {
        "loan_growth_base": config.banks.loan_growth_base,
        "loan_growth_slope": config.banks.loan_growth_slope,
    }


def gdp_cycles(
    data: dict[str, Any], end: tuple[int, int]
) -> tuple[list[tuple[int, int]], np.ndarray, np.ndarray]:
    """Quarters up to `end`: their keys, the real output gap and the unemployment gap (both from a
    quarterly Hodrick-Prescott filter over those quarters only)."""
    chosen = [i for i, k in enumerate(data["gdp_keys"]) if k <= end]
    keys = [data["gdp_keys"][i] for i in chosen]
    growth = data["gdp_growth"][chosen]
    unemployment = data["gdp_unemployment"][chosen]
    return keys, quarterly_output_gap(growth), hp_gap(unemployment, 1600.0)


def _sd_with_error(series: np.ndarray, seed: int, replications: int = 200) -> tuple[float, float]:
    """The standard deviation of `series` and its block-bootstrap standard error."""
    rng = np.random.default_rng(seed)
    values = [
        float(np.std(series[block_bootstrap_indices(series.size, GDP_BLOCK, rng)]))
        for _ in range(replications)
    ]
    return float(np.std(series)), float(max(np.std(values, ddof=1), 1e-9))


def estimate(
    data: dict[str, Any],
    end: tuple[int, int],
    simulator: Simulator,
    *,
    fits: int = 3,
    max_evaluations: int = 700,
    replications: int = 200,
    anchor: bool = False,
    credit_evaluations: int = 200,
) -> dict[str, Any]:
    """Run the three estimation stages on months up to `end`. With `anchor`, the output gap is tied
    to real GDP (see the module docstring, revision 2)."""
    piece = slice_data(data, (1960, 1), end)
    table = real_table(piece)
    months = int(table["gap"].size)
    replicates = bootstrap_moments(table, replications=replications, block=BLOCK, seed=1)
    real = all_moments(table)
    se = standard_errors(replicates, tuple(real))

    hmm = fit_gaussian_hmm(
        equity_history(data, end), n_states=3, n_starts=12, iterations=600, tolerance=1e-7, seed=3
    )
    okun = okun_coefficient(data["okun_delta_u"], data["okun_growth"])
    macro_names: tuple[str, ...] = MACRO_MOMENTS
    if anchor:
        _, y_cycle, u_cycle = gdp_cycles(data, end)
        okun = okun_gap_coefficient(u_cycle, y_cycle)
        real["ygap_sd"], se["ygap_sd"] = _sd_with_error(y_cycle, seed=5)
        macro_names = MACRO_MOMENTS + ("ygap_sd",)
    base = apply_direct(
        _with_length(scenario("volatile"), months),
        hmm=hmm,
        okun=okun,
        base_unemployment=float(np.mean(piece["unemployment"])),
        inflation_target=float(np.mean(piece["inflation"])),
        neutral_real_rate=float(np.mean(piece["fed_funds"] - piece["inflation"])),
    )

    counter = {"n": 0}

    def macro_objective(x: np.ndarray) -> float:
        counter["n"] += 1
        config = apply_macro(base, _from_unit(x, MACRO_PARAMETERS))
        try:
            simulated = simulator.moments(config, EQUITY_SEEDS)
        except (np.linalg.LinAlgError, ValueError, FloatingPointError):
            return 1e9
        if not all(math.isfinite(simulated[n]) for n in macro_names):
            return 1e9
        return distance(simulated, real, se, macro_names)

    start = _unit(_chosen_values(base), MACRO_PARAMETERS)
    rng = np.random.default_rng(11)
    runs: list[dict[str, Any]] = []
    for index in range(fits):
        x0 = (
            start
            if index == 0
            else np.clip(start + rng.normal(0.0, 0.12, size=start.size), 0.02, 0.98)
        )
        counter["n"] = 0
        result = minimize(
            macro_objective,
            x0,
            method="Nelder-Mead",
            bounds=[(0.0, 1.0)] * len(MACRO_PARAMETERS),
            options={"maxfev": max_evaluations, "xatol": 2e-3, "fatol": 1e-2},
        )
        runs.append(
            {
                "start": "chosen" if index == 0 else f"perturbed_{index}",
                "distance": float(result.fun),
                "evaluations": int(counter["n"]),
                "values": _from_unit(np.asarray(result.x), MACRO_PARAMETERS),
            }
        )
    best = min(runs, key=lambda r: float(r["distance"]))
    macro_values = best["values"]
    calibrated = apply_macro(base, macro_values)

    credit_real = {n: real[n] for n in CREDIT_MOMENTS}

    def credit_objective(x: np.ndarray) -> float:
        config = apply_credit(calibrated, _from_unit(x, CREDIT_PARAMETERS))
        simulated = simulator.moments(config, EQUITY_SEEDS)
        if not all(math.isfinite(simulated[n]) for n in CREDIT_MOMENTS):
            return 1e9
        return distance(simulated, credit_real, se, CREDIT_MOMENTS)

    credit_start = _unit(_credit_start(calibrated), CREDIT_PARAMETERS)
    credit_result = minimize(
        credit_objective,
        credit_start,
        method="Nelder-Mead",
        bounds=[(0.0, 1.0)] * len(CREDIT_PARAMETERS),
        options={"maxfev": credit_evaluations, "xatol": 2e-3, "fatol": 1e-2},
    )
    credit_values = _from_unit(np.asarray(credit_result.x), CREDIT_PARAMETERS)
    calibrated = apply_credit(calibrated, credit_values)
    return {
        "months": months,
        "real_moments": real,
        "moment_se": se,
        "bootstrap_replications": len(replicates),
        "hmm": _hmm_dict(hmm),
        "direct": {
            "okun": float(max(okun, 0.05)),
            "okun_raw": float(okun),
            "base_unemployment": float(np.mean(piece["unemployment"])),
            "inflation_target": float(np.mean(piece["inflation"])),
            "neutral_real_rate": float(np.mean(piece["fed_funds"] - piece["inflation"])),
        },
        "anchor": anchor,
        "macro_names": macro_names,
        "macro_fits": runs,
        "macro_values": macro_values,
        "macro_distance": float(best["distance"]),
        "credit_values": credit_values,
        "credit_distance": float(credit_result.fun),
        "config": calibrated,
        "base": base,
        "table": table,
        "replicates": replicates,
    }


def _hmm_dict(fit: HmmFit) -> dict[str, Any]:
    return {
        "mean": fit.mean.tolist(),
        "sigma": fit.sigma.tolist(),
        "transition": fit.transition.tolist(),
        "share": fit.share.tolist(),
        "log_likelihood": fit.log_likelihood,
        "converged": fit.converged,
    }


# --------------------------------------------------------------------------- evaluation


def verdict_a(low: float, high: float) -> str:
    if low > 0.0:
        return "SUPPORTED"
    if high < 0.0:
        return "CONTRADICTED"
    return "INCONCLUSIVE"


def verdict_b(inside: int, total: int) -> str:
    if inside >= HYPOTHESIS_UNTARGETED_SUPPORT:
        return "SUPPORTED"
    if inside <= HYPOTHESIS_UNTARGETED_CONTRADICT:
        return "CONTRADICTED"
    del total
    return "INCONCLUSIVE"


def verdict_c(connected_share: float, plain_share: float) -> str:
    if connected_share >= plain_share + SIGNIFICANCE_GAP:
        return "SUPPORTED"
    if connected_share <= plain_share:
        return "CONTRADICTED"
    return "INCONCLUSIVE"


def verdict_s(sanity: dict[str, Any], macro_values: dict[str, float]) -> str:
    """K-S: a sane output gap, no numerical failures, no parameter pinned at a bound."""
    for label in ("plain", "connected"):
        row = sanity[label]
        sd = row["output_gap_sd"]
        if row["failed_paths"] > 0 or sd is None or not 1.0 <= sd <= 4.0:
            return "CONTRADICTED"
    for name, lo, hi in MACRO_PARAMETERS:
        margin = 0.01 * (hi - lo)
        if macro_values[name] <= lo + margin or macro_values[name] >= hi - margin:
            return "CONTRADICTED"
    return "SUPPORTED"


def out_of_sample(
    data: dict[str, Any], trained: dict[str, Any], simulator: Simulator
) -> dict[str, Any]:
    test_piece = slice_data(data, TEST_START, DATA_END)
    test_table = real_table(test_piece)
    months = int(test_table["gap"].size)
    replicates = bootstrap_moments(test_table, replications=200, block=BLOCK, seed=2)
    anchor = bool(trained["anchor"])
    oos = OOS_MOMENTS + (("ygap_sd",) if anchor else ())
    names = oos + UNTARGETED_MOMENTS
    real = all_moments(test_table)
    if anchor:
        keys, y_all, _ = gdp_cycles(data, DATA_END)
        y_test = y_all[[k >= TEST_START for k in keys]]
        rng = np.random.default_rng(6)
        boot = [
            float(np.std(y_test[block_bootstrap_indices(y_test.size, GDP_BLOCK, rng)]))
            for _ in range(len(replicates))
        ]
        real["ygap_sd"] = float(np.std(y_test))
        for rep, value in zip(replicates, boot, strict=True):
            rep["ygap_sd"] = value
    se = standard_errors(replicates, names)

    chosen = _with_length(scenario("volatile"), months)
    calibrated = _with_length(trained["config"], months)
    chosen_moments = simulator.moments(chosen, TEST_SEEDS)
    calibrated_moments = simulator.moments(calibrated, TEST_SEEDS)

    table: dict[str, Any] = {}
    for name in names:
        table[name] = {
            "real": real[name],
            "real_se": se[name],
            "chosen": chosen_moments[name],
            "calibrated": calibrated_moments[name],
            "z_chosen": (chosen_moments[name] - real[name]) / se[name],
            "z_calibrated": (calibrated_moments[name] - real[name]) / se[name],
        }
    d_chosen = distance(chosen_moments, real, se, oos)
    d_calibrated = distance(calibrated_moments, real, se, oos)
    differences = [
        distance(chosen_moments, rep, se, oos) - distance(calibrated_moments, rep, se, oos)
        for rep in replicates
    ]
    low, high = (float(v) for v in np.percentile(differences, [2.5, 97.5]))

    inside = 0
    untargeted: dict[str, Any] = {}
    for name in UNTARGETED_MOMENTS:
        values = [rep[name] for rep in replicates]
        lo, hi = (float(v) for v in np.percentile(values, [2.5, 97.5]))
        ok = lo <= calibrated_moments[name] <= hi
        inside += int(ok)
        untargeted[name] = {
            "real": real[name],
            "interval_low": lo,
            "interval_high": hi,
            "calibrated": calibrated_moments[name],
            "chosen": chosen_moments[name],
            "calibrated_inside": bool(ok),
            "chosen_inside": bool(lo <= chosen_moments[name] <= hi),
        }
    return {
        "test_months": months,
        "moments": table,
        "distance_chosen": d_chosen,
        "distance_calibrated": d_calibrated,
        "distance_difference": {"estimate": d_chosen - d_calibrated, "low": low, "high": high},
        "K-A": verdict_a(low, high),
        "untargeted": untargeted,
        "untargeted_inside": inside,
        "K-B": verdict_b(inside, len(UNTARGETED_MOMENTS)),
        "moments_closer": int(
            sum(abs(table[n]["z_calibrated"]) < abs(table[n]["z_chosen"]) for n in oos)
        ),
        "moments_total": len(oos),
    }


def identification(estimate_result: dict[str, Any], simulator: Simulator) -> dict[str, Any]:
    """The objective when each parameter is moved 20% either way with the rest fixed."""
    values = estimate_result["macro_values"]
    base = estimate_result["base"]
    real, se = estimate_result["real_moments"], estimate_result["moment_se"]

    def at(v: dict[str, float]) -> float:
        simulated = simulator.moments(apply_macro(base, v), EQUITY_SEEDS)
        return distance(simulated, real, se, estimate_result["macro_names"])

    centre = at(values)
    rows: dict[str, Any] = {}
    for name, lo, hi in MACRO_PARAMETERS:
        down = dict(values)
        up = dict(values)
        down[name] = float(np.clip(values[name] * 0.8, lo, hi))
        up[name] = float(np.clip(values[name] * 1.2, lo, hi))
        d_down, d_up = at(down) - centre, at(up) - centre
        rows[name] = {
            "value": values[name],
            "distance_at_estimate": centre,
            "increase_at_minus_20pct": d_down,
            "increase_at_plus_20pct": d_up,
            "identified": bool(min(d_down, d_up) > 3.84),
        }
    return rows


def robustness(config: WorldConfig, seeds: Sequence[int], workers: int) -> dict[str, Any]:
    """Finding 27's headline on the calibrated world: do the links make shocks travel?"""
    linked = connected(config)
    plain = replace(linked, links=replace(linked.links, enabled=False))
    linked_matrix = impulse_matrix(linked, seeds, workers=workers)
    plain_matrix = impulse_matrix(plain, seeds, workers=workers)
    worst: list[float] = []
    for seed in seeds:
        a = simulate_world(linked, seed).output_gap.min()
        b = simulate_world(plain, seed).output_gap.min()
        worst.append(float(a - b))
    interval = t_interval(np.asarray(worst), 0.95).as_dict()
    return {
        "connected_share_excluding_zero": linked_matrix["share_excluding_zero"],
        "plain_share_excluding_zero": plain_matrix["share_excluding_zero"],
        "connected_cells": linked_matrix["cells_excluding_zero"],
        "plain_cells": plain_matrix["cells_excluding_zero"],
        "cells": linked_matrix["cells"],
        "worst_output_gap_connected_minus_plain": interval,
        "K-C": verdict_c(
            float(linked_matrix["share_excluding_zero"]),
            float(plain_matrix["share_excluding_zero"]),
        ),
    }


def configuration_summary(estimate_result: dict[str, Any]) -> dict[str, Any]:
    cfg: WorldConfig = estimate_result["config"]
    return {
        "transition": cfg.transition.tolist(),
        "equity_mu": cfg.market.mu[:, 0].tolist(),
        "equity_sigma": cfg.market.sigma[:, 0].tolist(),
        "macro": {
            "output_persistence": cfg.macro.output_persistence,
            "inflation_persistence": cfg.macro.inflation_persistence,
            "phillips_slope": cfg.macro.phillips_slope,
            "inflation_vol": cfg.macro.inflation_vol,
            "taylor_phi_pi": cfg.macro.taylor_phi_pi,
            "taylor_phi_y": cfg.macro.taylor_phi_y,
            "rate_smoothing": cfg.macro.rate_smoothing,
            "regime_output_vol": list(cfg.macro.regime_output_vol),
            "regime_output_shift": list(cfg.macro.regime_output_shift),
            "inflation_target": cfg.macro.inflation_target,
            "neutral_real_rate": cfg.macro.neutral_real_rate,
        },
        "households": {
            "okun": cfg.households.okun,
            "base_unemployment": cfg.households.base_unemployment,
        },
        "banks": {
            "loan_growth_base": cfg.banks.loan_growth_base,
            "loan_growth_slope": cfg.banks.loan_growth_slope,
        },
    }


def _cached(directory: Path | None, name: str, compute: Callable[[], Any]) -> Any:
    """Compute a stage, or load it if a checkpoint from an earlier (interrupted) run exists. The
    checkpoint is the stage's own output, so a resumed run gives the same numbers."""
    if directory is None:
        return compute()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{name}.pkl"
    if target.exists():
        return pickle.loads(target.read_bytes())  # noqa: S301 - our own checkpoint, same machine
    value = compute()
    target.write_bytes(pickle.dumps(value))
    return value


def world_sanity(config: WorldConfig, seeds: Sequence[int]) -> dict[str, Any]:
    """Is the world numerically sane? Spread of the output gap, the worst public-debt ratio and how
    many paths blow up, for the plain world and for the fully connected one."""
    out: dict[str, Any] = {}
    for label, candidate in (("plain", config), ("connected", connected(config))):
        gaps_sd: list[float] = []
        gaps_min: list[float] = []
        debt_max: list[float] = []
        failures: list[str] = []
        for seed in seeds:
            try:
                with np.errstate(all="ignore"):
                    path = simulate_world(candidate, seed)
            except NUMERIC_ERRORS as exc:
                failures.append(f"seed {seed}: {type(exc).__name__}")
                continue
            if not (np.isfinite(path.output_gap).all() and np.isfinite(path.debt_ratio).all()):
                failures.append(f"seed {seed}: non-finite path")
                continue
            gaps_sd.append(float(path.output_gap.std()))
            gaps_min.append(float(path.output_gap.min()))
            debt_max.append(float(path.debt_ratio.max()))
        out[label] = {
            "paths": len(seeds),
            "failed_paths": len(failures),
            "failures": failures[:5],
            "output_gap_sd": float(np.mean(gaps_sd)) if gaps_sd else None,
            "output_gap_min_mean": float(np.mean(gaps_min)) if gaps_min else None,
            "output_gap_min_worst": float(np.min(gaps_min)) if gaps_min else None,
            "max_debt_ratio_median": float(np.median(debt_max)) if debt_max else None,
            "max_debt_ratio_worst": float(np.max(debt_max)) if debt_max else None,
        }
    return out


def _regime_shares(
    config: WorldConfig, hmm_share: Sequence[float], keys: list[tuple[int, int]]
) -> dict[str, Any]:
    slow: list[float] = []
    crisis: list[float] = []
    for seed in TEST_SEEDS[:10]:
        try:
            with np.errstate(all="ignore"):
                regime = simulate_world(config, seed).regime
        except NUMERIC_ERRORS:
            continue
        slow.append(float(np.mean(regime == 1)))
        crisis.append(float(np.mean(regime == 2)))
    return {
        "nber_recession_share": nber_share(keys),
        "model_slowdown_share": float(np.mean(slow)) if slow else None,
        "model_crisis_share": float(np.mean(crisis)) if crisis else None,
        "hmm_state_share": list(hmm_share),
    }


def _safe_robustness(config: WorldConfig, seeds: Sequence[int], workers: int) -> dict[str, Any]:
    try:
        return robustness(config, seeds, workers)
    except NUMERIC_ERRORS as exc:
        return {"failed": f"{type(exc).__name__}: {exc}", "K-C": "INCONCLUSIVE"}


def run_study(
    *,
    workers: int = 18,
    fits: int = 3,
    max_evaluations: int = 700,
    replications: int = 200,
    robustness_seeds: Sequence[int] = ROBUST_SEEDS,
    skip_robustness: bool = False,
    checkpoint_dir: Path | None = None,
    anchor: bool = False,
) -> dict[str, Any]:
    started = time.time()
    data = load_real_data()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        simulator = Simulator(pool)
        train = _cached(
            checkpoint_dir,
            "train",
            lambda: estimate(
                data,
                TRAIN_END,
                simulator,
                fits=fits,
                max_evaluations=max_evaluations,
                replications=replications,
                anchor=anchor,
            ),
        )
        held_out = _cached(
            checkpoint_dir, "held_out", lambda: out_of_sample(data, train, simulator)
        )
        full = _cached(
            checkpoint_dir,
            "full",
            lambda: estimate(
                data,
                DATA_END,
                simulator,
                fits=fits,
                max_evaluations=max_evaluations,
                replications=replications,
                anchor=anchor,
            ),
        )
        ident = _cached(checkpoint_dir, "identification", lambda: identification(full, simulator))
        full_months = int(full["months"])
        full_sim = simulator.moments(full["config"], TEST_SEEDS)
        full_keys = slice_data(data, (1960, 1), DATA_END)["keys"][12:]
        shares = _regime_shares(full["config"], full["hmm"]["share"], full_keys)
        sanity = {
            "chosen": world_sanity(scenario("volatile"), TEST_SEEDS[:20]),
            "calibrated": world_sanity(full["config"], TEST_SEEDS[:20]),
        }
        robust = (
            None
            if skip_robustness
            else {
                "calibrated": _safe_robustness(
                    replace(full["config"], n_months=SCENARIO_MONTHS), robustness_seeds, workers
                ),
                "chosen": _safe_robustness(scenario("volatile"), robustness_seeds, workers),
            }
        )

    def public(result: dict[str, Any]) -> dict[str, Any]:
        keep = (
            "months",
            "real_moments",
            "moment_se",
            "bootstrap_replications",
            "hmm",
            "direct",
            "anchor",
            "macro_names",
            "macro_fits",
            "macro_values",
            "macro_distance",
            "credit_values",
            "credit_distance",
        )
        # checkpoints written before the anchor existed lack these two keys: they were unanchored
        defaults: dict[str, Any] = {"anchor": False, "macro_names": MACRO_MOMENTS}
        out = {k: result.get(k, defaults.get(k)) for k in keep}
        out["configuration"] = configuration_summary(result)
        return out

    chosen = configuration_summary({"config": scenario("volatile")})
    return {
        "design": {
            "train": "1960-01..1999-12 (equity from 1928-01)",
            "test": "2000-01..2023-01",
            "full": "1960-01..2023-01 (equity from 1928-01)",
            "simulation_paths": len(EQUITY_SEEDS),
            "evaluation_paths": len(TEST_SEEDS),
            "bootstrap": {"block_months": BLOCK, "replications": replications},
            "output_gap_anchor": anchor,
            "not_calibrated": [
                "bond and real-asset returns and correlations",
                "bank balance sheets, loss rates and capital rules",
                "firm, fiscal, foreign-sector and household-wealth blocks",
                "rate_sensitivity and credit_crunch_drag (output channels)",
            ],
        },
        "chosen_configuration": chosen,
        "train_fit": public(train),
        "out_of_sample": held_out,
        "full_fit": public(full),
        "identification": ident,
        "full_fit_months": full_months,
        "full_fit_simulated_moments": full_sim,
        "regime_shares": shares,
        "world_sanity": sanity,
        "world_sanity_240_months": world_sanity(
            replace(full["config"], n_months=SCENARIO_MONTHS), TEST_SEEDS[:20]
        ),
        "K-S": verdict_s(sanity["calibrated"], full["macro_values"]),
        "robustness": robust,
        "seconds": time.time() - started,
    }


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.floating, float)):
        return None if not math.isfinite(float(value)) else float(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--workers", type=int, default=18)
    parser.add_argument("--fits", type=int, default=3)
    parser.add_argument("--max-evaluations", type=int, default=700)
    parser.add_argument("--replications", type=int, default=200)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--output-gap-anchor", action="store_true")
    parser.add_argument("--checkpoint-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    result = run_study(
        workers=args.workers,
        fits=args.fits,
        max_evaluations=args.max_evaluations,
        replications=args.replications,
        checkpoint_dir=args.checkpoint_dir,
        anchor=args.output_gap_anchor,
    )
    output = args.output or (OUTPUT_V2 if args.output_gap_anchor else OUTPUT)
    output.write_text(json.dumps(_jsonable(result), indent=2) + "\n")
    print(f"wrote {output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
