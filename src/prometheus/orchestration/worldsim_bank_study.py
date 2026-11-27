"""Finding 29: estimating the WORLDSIM bank block from real FDIC bank data.

Finding 28 named the bank block as its weakest link: the credit statistics were not matched
(simulated credit growth about 0% a year against 7% in the data). The data it used, though, was a
measure that includes securities. This study replaces it with the FDIC's annual national totals of
the whole banking system (`data_ingestion.fdic_banks`, 1985-2022): the return on assets, the equity
ratio, net loan charge-offs, loan growth and the assets of failed banks, and estimates the bank
parameters by indirect inference (`worldsim.bank_calibration`).

What is estimated. Directly: the opening balance sheet (the real shares of loans, securities, cash
and deposits in assets). By indirect inference, against nine annual statistics (mean and standard
deviation of the return on assets, the mean equity ratio, the mean and standard deviation of the
net charge-off rate and its correlation with the unemployment gap, the mean and standard deviation
of loan growth and its correlation with the unemployment gap): the net interest margin, the base
default rate, the sensitivity of defaults to the output gap, a new dividend payout ratio and the
two loan-growth parameters. The macro parameters of Finding 28 are NOT re-estimated; a hypothesis
below asks whether the new bank block breaks that fit.

Not estimated: loss given default (charge-offs are net of recoveries, so only its product with the
default rate is identified; it stays 0.5), the capital trigger, the fire-sale fraction, the
securities' equity share and the interbank network (an aggregate has no information on them).

What I had looked at before writing this: the real annual rows and moments (so I know the real
return on assets averages 0.9%, the equity ratio 9% and the charge-off rate 0.8%), and the same
statistics in the Finding 28 world with its chosen banks (a return on assets of 2.6%, an equity
ratio of 26%). Retained earnings are never paid out there, so capital piles up. K-D1 below is
therefore close to a foregone conclusion and is reported as such; the informative tests are the
others. The estimation sample is 1985-2003 and the held-out sample 2004-2022 (which contains the
2008 crisis); the final estimate uses all 38 years. None of the held-out simulations had been run
when these hypotheses were written.

Pre-written hypotheses (rules fixed before the first run):

- **K-D1** (held-out fit): over the nine targeted statistics, the bank-calibrated world estimated
  on 1985-2003 is closer to 2004-2022 than the Finding 28 world, in the sum of squared standardised
  gaps. SUPPORTED if the 95% interval of the paired difference over block bootstraps of the real
  years is above zero, CONTRADICTED if below, otherwise INCONCLUSIVE.
- **K-D2** (untargeted statistics): of seven statistics no estimation step used (the mean share of
  assets that failed in a year, the share of years with more than 1% failing, the peak charge-off
  rate, the worst return on assets, the worst loan growth, the standard deviation of the equity
  ratio, the loans-to-assets ratio), at least five of the calibrated world's values lie inside the
  real 95% interval of 2004-2022 (SUPPORTED; at most two is CONTRADICTED).
- **K-D3** (sane world, final estimate): the mean equity ratio of the system is between 6% and 14%
  over paths; no more than 5% of paths end with every bank failed; no path of the plain or the
  connected world fails numerically; no estimated parameter lies within 1% of its bound.
- **K-D4** (no harm to the macro fit): the distance on the fourteen macro statistics of Finding 28
  (whole real sample) of the bank-calibrated world is at most 1.25 times that of the Finding 28
  world (SUPPORTED; more than twice is CONTRADICTED).
- **K-D5** (Finding 27 survives): in the bank-calibrated connected world the share of shock-by-
  outcome cells with an interval excluding zero exceeds that of the same world with the links off
  by at least 0.20 (the rule of K-C).

## First run (revision 1), recorded in `docs/numerics/worldsim_bank_study.json`

K-D1 SUPPORTED (as expected), K-D2 INCONCLUSIVE (4 of 7), K-D3 CONTRADICTED (the dividend payout,
the base loan growth and its slope all sat at a bound), K-D4 INCONCLUSIVE (a macro distance 1.27
times that of Finding 28), K-D5 SUPPORTED. It also showed what the estimation could not fix: the
standard deviation of the return on assets 1.4 against 0.4 in the data, loans at 76% of assets
against 58%, loan growth 7% against 4.6%, almost no bank failures, no credit contraction.

## Revision 2 (written after reading the first run and before running the second)

Three changes, each because of what the first run showed, none tuned on the held-out years:

1. `securities_equity_share` is now a direct estimate from the data (equity securities as a share of
   securities, FDIC field SCEQ, mean over the years reported: about 1.5%), instead of the chosen
   0.4. Forty percent of the banks' securities moved with the equity market, which is why bank
   earnings were five times too volatile.
2. `securities_growth_share` is 1: when loans grow the securities grow with them, so the balance
   sheet keeps its composition (assets grew proportionally in the data: loans stayed 50 to 62% of
   assets over 38 years). A structural choice, not an estimate.
3. The dividend rule gets a threshold: a bank distributes `payout_ratio` of a month's profit only
   while its equity ratio is above `dividend_threshold`, now the seventh estimated parameter (the
   mean equity ratio in the data identifies it). The first run had banks paying out 95% of profit
   whatever their capital, so they sat at the capital trigger and their growth was capital-bound
   rather than a parameter.

Hypotheses asked again with the same rules (labelled K-E; the first revision's world is added as a
comparator):

- **K-E1**: as K-D1 (held-out distance, closer than the Finding 28 world).
- **K-E2**: as K-D1 against the FIRST-REVISION world estimated on the same years (a harder test:
  does revision 2 improve on revision 1?).
- **K-E3**: as K-D2 (at least five of seven untargeted statistics inside the real 95% interval).
- **K-E4**: as K-D3 (sane world, final estimate).
- **K-E5**: as K-D4 (macro distance at most 1.25 times that of Finding 28).
- **K-E6**: as K-D5 (Finding 27 survives).
- **K-E7** (structure): of the standard deviation of the return on assets, the standard deviation of
  the equity ratio and the mean loans-to-assets ratio, at least two of the bank-calibrated world's
  held-out values lie inside the real 95% interval.

Run: `python -m prometheus.orchestration.worldsim_bank_study --checkpoint-dir <dir>
[--revision 2]`.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import minimize

from prometheus.data_ingestion.fdic_banks import load_bank_annual, load_failures_annual
from prometheus.orchestration.worldsim_calibration_study import (
    BLOCK,
    DATA_END,
    NUMERIC_ERRORS,
    SCENARIO_MONTHS,
    Simulator,
    _cached,
    _jsonable,
    _safe_robustness,
    _sd_with_error,
    _with_length,
    gdp_cycles,
    load_real_data,
    real_table,
    slice_data,
    verdict_a,
    world_sanity,
)
from prometheus.worldsim.bank_calibration import (
    BANK_PARAMETERS,
    BANK_PARAMETERS_V2,
    TARGETED_MOMENTS,
    UNTARGETED_MOMENTS,
    annual_bootstrap,
    annual_moments,
    annual_unemployment_gap,
    apply_balance_sheet,
    apply_bank,
    balance_sheet_shares,
    bank_distance,
    bank_standard_errors,
    interval,
    real_annual_table,
    simulated_annual_moments,
    simulated_annual_table,
)
from prometheus.worldsim.calibrated import calibrated_config
from prometheus.worldsim.config import WorldConfig
from prometheus.worldsim.real_calibration import (
    MACRO_MOMENTS,
    all_moments,
    bootstrap_moments,
    distance,
    standard_errors,
)
from prometheus.worldsim.world import simulate_world

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / "docs" / "numerics" / "worldsim_bank_study.json"
OUTPUT_V2 = ROOT / "docs" / "numerics" / "worldsim_bank_study_v2.json"
TRAIN_YEARS = (1985, 2003)
TEST_YEARS = (2004, 2022)
FULL_YEARS = (1985, 2022)
ESTIMATION_SEEDS = tuple(range(61_000, 61_024))
EVALUATION_SEEDS = tuple(range(62_000, 62_060))
SANITY_SEEDS = tuple(range(63_000, 63_040))
ROBUST_SEEDS = tuple(range(64_000, 64_040))
SUPPORT_UNTARGETED = 5
CONTRADICT_UNTARGETED = 2
MIN_EQUITY, MAX_EQUITY = 6.0, 14.0
MAX_COLLAPSED_SHARE = 0.05
NO_HARM_RATIO = 1.25
HARM_RATIO = 2.0
FIXED_LOSS_GIVEN_DEFAULT = 0.5


def _bank_moments_task(args: tuple[WorldConfig, int]) -> dict[str, float]:
    config, seed = args
    with np.errstate(all="ignore"):
        try:
            return simulated_annual_moments(simulate_world(config, seed))
        except NUMERIC_ERRORS:
            return {name: math.nan for name in (*TARGETED_MOMENTS, *UNTARGETED_MOMENTS)}


class BankSimulator(Simulator):
    """Average annual bank moments over a fixed set of seeds (parallel when given a pool)."""

    def bank_moments(self, config: WorldConfig, seeds: Sequence[int]) -> dict[str, float]:
        jobs = [(config, seed) for seed in seeds]
        rows = (
            list(self.pool.map(_bank_moments_task, jobs))
            if self.pool
            else list(map(_bank_moments_task, jobs))
        )
        out: dict[str, float] = {}
        for name in rows[0]:
            finite = [row[name] for row in rows if math.isfinite(row[name])]
            out[name] = float(np.mean(finite)) if finite else math.nan
        return out


# --------------------------------------------------------------------------- real annual data


def real_tables(
    data: dict[str, Any],
) -> dict[str, dict[str, np.ndarray]]:
    """The real annual rows for the full, training and test windows."""
    piece = slice_data(data, (1960, 1), DATA_END)
    monthly = real_table(piece)
    years = list(range(FULL_YEARS[0], FULL_YEARS[1] + 1))
    ugap = annual_unemployment_gap(piece["keys"], monthly["gap"], years)
    full = real_annual_table(
        load_bank_annual(),
        load_failures_annual(),
        dict(zip(years, ugap.tolist(), strict=True)),
        FULL_YEARS[0],
        FULL_YEARS[1],
    )

    def window(first: int, last: int) -> dict[str, np.ndarray]:
        keep = (full["year"] >= first) & (full["year"] <= last)
        return {k: v[keep] for k, v in full.items()}

    return {
        "full": full,
        "train": window(*TRAIN_YEARS),
        "test": window(*TEST_YEARS),
    }


# --------------------------------------------------------------------------- estimation


Parameters = tuple[tuple[str, float, float], ...]


def parameters_for(revision: int) -> Parameters:
    return BANK_PARAMETERS if revision == 1 else BANK_PARAMETERS_V2


def _unit(values: dict[str, float], parameters: Parameters = BANK_PARAMETERS) -> np.ndarray:
    return np.array([(values[n] - lo) / (hi - lo) for n, lo, hi in parameters])


def _from_unit(x: np.ndarray, parameters: Parameters = BANK_PARAMETERS) -> dict[str, float]:
    return {
        n: float(lo + np.clip(v, 0.0, 1.0) * (hi - lo))
        for (n, lo, hi), v in zip(parameters, x, strict=True)
    }


def _start_values(config: WorldConfig, revision: int = 1) -> dict[str, float]:
    b = config.banks
    values = {
        "net_interest_margin": b.net_interest_margin,
        "base_default_rate": b.base_default_rate,
        "default_sensitivity": b.default_sensitivity,
        "payout_ratio": 0.6,
        "loan_growth_base": b.loan_growth_base,
        "loan_growth_slope": b.loan_growth_slope,
    }
    if revision >= 2:
        values["payout_ratio"] = 0.8
        values["dividend_threshold"] = 0.09
    return values


def base_world(shares: dict[str, float], revision: int = 1) -> WorldConfig:
    """The Finding 28 world with the opening balance sheet from real shares and the loss given
    default fixed (revision 2 also sets the securities' equity share from the data)."""
    config = calibrated_config()
    config = apply_balance_sheet(config, shares, revision=revision)
    config = replace(
        config, banks=replace(config.banks, loss_given_default=FIXED_LOSS_GIVEN_DEFAULT)
    )
    return replace(config, n_months=SCENARIO_MONTHS)


def estimate_banks(
    table: dict[str, np.ndarray],
    shares: dict[str, float],
    simulator: BankSimulator,
    *,
    fits: int,
    max_evaluations: int,
    replications: int = 300,
    revision: int = 1,
) -> dict[str, Any]:
    parameters = parameters_for(revision)
    real = annual_moments(table)
    replicates = annual_bootstrap(table, replications=replications, seed=21)
    se = bank_standard_errors(replicates, TARGETED_MOMENTS)
    base = base_world(shares, revision)

    def objective(x: np.ndarray) -> float:
        simulated = simulator.bank_moments(
            apply_bank(base, _from_unit(x, parameters)), ESTIMATION_SEEDS
        )
        if not all(math.isfinite(simulated[n]) for n in TARGETED_MOMENTS):
            return 1e9
        return bank_distance(simulated, real, se)

    start = _unit(_start_values(base, revision), parameters)
    rng = np.random.default_rng(31)
    runs: list[dict[str, Any]] = []
    for index in range(fits):
        x0 = (
            start
            if index == 0
            else np.clip(start + rng.normal(0.0, 0.15, size=start.size), 0.02, 0.98)
        )
        result = minimize(
            objective,
            x0,
            method="Nelder-Mead",
            bounds=[(0.0, 1.0)] * len(parameters),
            options={"maxfev": max_evaluations, "xatol": 2e-3, "fatol": 1e-2},
        )
        runs.append(
            {
                "start": "chosen" if index == 0 else f"perturbed_{index}",
                "distance": float(result.fun),
                "evaluations": int(result.nfev),
                "values": _from_unit(np.asarray(result.x), parameters),
            }
        )
    best = min(runs, key=lambda r: float(r["distance"]))
    config = apply_bank(base, best["values"])
    return {
        "revision": revision,
        "parameters": parameters,
        "years": int(table["roa"].size),
        "real_moments": real,
        "moment_se": se,
        "bootstrap_replications": len(replicates),
        "direct_shares": shares,
        "fits": runs,
        "values": best["values"],
        "distance": float(best["distance"]),
        "config": config,
        "base": base,
    }


def identification(result: dict[str, Any], simulator: BankSimulator) -> dict[str, Any]:
    """The objective when each estimated parameter is moved 20% either way, the rest fixed."""
    values, base = result["values"], result["base"]
    real, se = result["real_moments"], result["moment_se"]

    def at(v: dict[str, float]) -> float:
        simulated = simulator.bank_moments(apply_bank(base, v), ESTIMATION_SEEDS)
        return bank_distance(simulated, real, se)

    centre = at(values)
    rows: dict[str, Any] = {}
    for name, lo, hi in result["parameters"]:
        down, up = dict(values), dict(values)
        down[name] = float(np.clip(values[name] * 0.8, lo, hi))
        up[name] = float(np.clip(values[name] * 1.2, lo, hi))
        d_down, d_up = at(down) - centre, at(up) - centre
        rows[name] = {
            "value": values[name],
            "increase_at_minus_20pct": d_down,
            "increase_at_plus_20pct": d_up,
            "identified": bool(min(d_down, d_up) > 3.84),
        }
    return {"distance_at_estimate": centre, "parameters": rows}


# --------------------------------------------------------------------------- evaluation


def verdict_d2(inside: int) -> str:
    if inside >= SUPPORT_UNTARGETED:
        return "SUPPORTED"
    if inside <= CONTRADICT_UNTARGETED:
        return "CONTRADICTED"
    return "INCONCLUSIVE"


def verdict_d4(new_distance: float, old_distance: float) -> str:
    if new_distance <= NO_HARM_RATIO * old_distance:
        return "SUPPORTED"
    if new_distance > HARM_RATIO * old_distance:
        return "CONTRADICTED"
    return "INCONCLUSIVE"


STRUCTURE_MOMENTS: tuple[str, ...] = ("roa_sd", "eq_sd", "loans_to_assets_mean")
STRUCTURE_SUPPORT = 2


def out_of_sample(
    trained: dict[str, Any],
    tables: dict[str, dict[str, np.ndarray]],
    simulator: BankSimulator,
    *,
    first_revision: WorldConfig | None = None,
) -> dict[str, Any]:
    """The held-out years: the distance test against the Finding 28 world (K-D1 / K-E1), the
    untargeted statistics (K-D2 / K-E3) and, in revision 2, the distance test against the first
    revision's world (K-E2) and the structure check (K-E7)."""
    table = tables["test"]
    real = annual_moments(table)
    replicates = annual_bootstrap(table, replications=300, seed=22)
    se = bank_standard_errors(replicates, TARGETED_MOMENTS)
    old = simulator.bank_moments(calibrated_config(), EVALUATION_SEEDS)
    new = simulator.bank_moments(trained["config"], EVALUATION_SEEDS)
    first = (
        None if first_revision is None else simulator.bank_moments(first_revision, EVALUATION_SEEDS)
    )
    rows: dict[str, Any] = {}
    for name in TARGETED_MOMENTS:
        rows[name] = {
            "real": real[name],
            "real_se": se[name],
            "finding28": old[name],
            "bank_calibrated": new[name],
            "z_finding28": (old[name] - real[name]) / se[name],
            "z_bank_calibrated": (new[name] - real[name]) / se[name],
        }
        if first is not None:
            rows[name]["first_revision"] = first[name]
            rows[name]["z_first_revision"] = (first[name] - real[name]) / se[name]
    d_old = bank_distance(old, real, se)
    d_new = bank_distance(new, real, se)
    differences = [bank_distance(old, rep, se) - bank_distance(new, rep, se) for rep in replicates]
    low, high = (float(v) for v in np.percentile(differences, [2.5, 97.5]))
    inside_new = inside_old = 0
    untargeted: dict[str, Any] = {}
    for name in UNTARGETED_MOMENTS:
        lo, hi = interval(replicates, name)
        ok_new, ok_old = lo <= new[name] <= hi, lo <= old[name] <= hi
        inside_new += int(ok_new)
        inside_old += int(ok_old)
        untargeted[name] = {
            "real": real[name],
            "interval_low": lo,
            "interval_high": hi,
            "finding28": old[name],
            "bank_calibrated": new[name],
            "bank_calibrated_inside": bool(ok_new),
            "finding28_inside": bool(ok_old),
        }
        if first is not None:
            untargeted[name]["first_revision"] = first[name]
            untargeted[name]["first_revision_inside"] = bool(lo <= first[name] <= hi)
    out: dict[str, Any] = {
        "test_years": int(table["roa"].size),
        "moments": rows,
        "distance_finding28": d_old,
        "distance_bank_calibrated": d_new,
        "distance_difference": {"estimate": d_old - d_new, "low": low, "high": high},
        "K-D1": verdict_a(low, high),
        "moments_closer": int(
            sum(abs(rows[n]["z_bank_calibrated"]) < abs(rows[n]["z_finding28"]) for n in rows)
        ),
        "moments_total": len(rows),
        "untargeted": untargeted,
        "untargeted_inside": inside_new,
        "untargeted_inside_finding28": inside_old,
        "K-D2": verdict_d2(inside_new),
    }
    if first is not None:
        d_first = bank_distance(first, real, se)
        against_first = [
            bank_distance(first, rep, se) - bank_distance(new, rep, se) for rep in replicates
        ]
        f_low, f_high = (float(v) for v in np.percentile(against_first, [2.5, 97.5]))
        out["distance_first_revision"] = d_first
        out["distance_difference_vs_first_revision"] = {
            "estimate": d_first - d_new,
            "low": f_low,
            "high": f_high,
        }
        out["K-E2"] = verdict_a(f_low, f_high)
        inside_structure = {}
        for name in STRUCTURE_MOMENTS:
            lo, hi = interval(replicates, name)
            inside_structure[name] = {
                "real": real[name],
                "interval_low": lo,
                "interval_high": hi,
                "bank_calibrated": new[name],
                "inside": bool(lo <= new[name] <= hi),
            }
        count = sum(v["inside"] for v in inside_structure.values())
        out["structure"] = inside_structure
        out["structure_inside"] = count
        out["K-E7"] = "SUPPORTED" if count >= STRUCTURE_SUPPORT else "CONTRADICTED"
    return out


def macro_check(
    data: dict[str, Any], final: WorldConfig, simulator: BankSimulator
) -> dict[str, Any]:
    """K-D4: the macro distance of Finding 28 (anchored, whole real sample) for both worlds."""
    piece = slice_data(data, (1960, 1), DATA_END)
    table = real_table(piece)
    months = int(table["gap"].size)
    replicates = bootstrap_moments(table, replications=200, block=BLOCK, seed=1)
    real = all_moments(table)
    se = standard_errors(replicates, tuple(real))
    _, y_cycle, _ = gdp_cycles(data, DATA_END)
    real["ygap_sd"], se["ygap_sd"] = _sd_with_error(y_cycle, seed=5)
    names = (*MACRO_MOMENTS, "ygap_sd")
    out: dict[str, Any] = {"names": list(names)}
    for label, config in (("finding28", calibrated_config()), ("bank_calibrated", final)):
        simulated = simulator.moments(_with_length(config, months), EVALUATION_SEEDS[:40])
        out[label] = float(distance(simulated, real, se, names))
    out["ratio"] = out["bank_calibrated"] / max(out["finding28"], 1e-9)
    out["K-D4"] = verdict_d4(out["bank_calibrated"], out["finding28"])
    return out


def sanity(final: dict[str, Any]) -> dict[str, Any]:
    """K-D3: equity ratio over paths, collapsed paths, numerical failures, parameters at a bound."""
    config: WorldConfig = final["config"]
    equity, collapsed = [], 0
    for seed in SANITY_SEEDS:
        with np.errstate(all="ignore"):
            path = simulate_world(config, seed)
        equity.append(float(np.mean(simulated_annual_table(path)["eq"])))
        collapsed += int(bool(path.bank_failed[-1].all()))
    numeric = world_sanity(config, SANITY_SEEDS[:20])
    at_bound = []
    for name, lo, hi in final["parameters"]:
        margin = 0.01 * (hi - lo)
        value = final["values"][name]
        if value <= lo + margin or value >= hi - margin:
            at_bound.append(name)
    mean_equity = float(np.mean(equity))
    collapsed_share = collapsed / len(SANITY_SEEDS)
    failed_paths = int(numeric["plain"]["failed_paths"] + numeric["connected"]["failed_paths"])
    ok = (
        MIN_EQUITY <= mean_equity <= MAX_EQUITY
        and collapsed_share <= MAX_COLLAPSED_SHARE
        and failed_paths == 0
        and not at_bound
    )
    return {
        "mean_equity_ratio_percent": mean_equity,
        "collapsed_share": collapsed_share,
        "numeric": numeric,
        "parameters_at_a_bound": at_bound,
        "K-D3": "SUPPORTED" if ok else "CONTRADICTED",
    }


def configuration_summary(config: WorldConfig) -> dict[str, Any]:
    b = config.banks
    return {
        name: getattr(b, name)
        for name in (
            "loans",
            "securities",
            "cash",
            "interbank_borrowed",
            "deposit_funding",
            "net_interest_margin",
            "base_default_rate",
            "default_sensitivity",
            "loss_given_default",
            "payout_ratio",
            "dividend_threshold",
            "securities_growth_share",
            "loan_growth_base",
            "loan_growth_slope",
            "capital_trigger",
            "fire_sale_fraction",
            "securities_equity_share",
        )
    }


def _not_calibrated(revision: int) -> list[str]:
    items = [
        "loss given default (only its product with the default rate is identified)",
        "capital trigger and fire-sale fraction",
        "the interbank network",
        "firm, fiscal, foreign-sector and household-wealth blocks",
    ]
    if revision == 1:
        items.insert(2, "securities' equity share")
    return items


def _first_revision_world(train_shares: dict[str, float]) -> WorldConfig:
    """The first run's world (estimated on the training years), rebuilt from the recorded run."""
    recorded = json.loads(OUTPUT.read_text(encoding="utf-8"))
    values = {k: float(v) for k, v in recorded["train_fit"]["values"].items()}
    return apply_bank(base_world(train_shares, 1), values)


def run_study(
    *,
    workers: int = 18,
    fits: int = 3,
    max_evaluations: int = 600,
    replications: int = 300,
    skip_robustness: bool = False,
    checkpoint_dir: Path | None = None,
    revision: int = 1,
) -> dict[str, Any]:
    if revision not in (1, 2):
        raise ValueError("revision must be 1 or 2")
    started = time.time()
    data = load_real_data()
    tables = real_tables(data)
    bank = load_bank_annual()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        simulator = BankSimulator(pool)
        train_shares = balance_sheet_shares(bank, *TRAIN_YEARS)
        first_revision = _first_revision_world(train_shares) if revision == 2 else None
        trained = _cached(
            checkpoint_dir,
            "train",
            lambda: estimate_banks(
                tables["train"],
                train_shares,
                simulator,
                fits=fits,
                max_evaluations=max_evaluations,
                replications=replications,
                revision=revision,
            ),
        )
        held_out = _cached(
            checkpoint_dir,
            "held_out",
            lambda: out_of_sample(trained, tables, simulator, first_revision=first_revision),
        )
        full_shares = balance_sheet_shares(bank, *FULL_YEARS)
        final = _cached(
            checkpoint_dir,
            "full",
            lambda: estimate_banks(
                tables["full"],
                full_shares,
                simulator,
                fits=fits,
                max_evaluations=max_evaluations,
                replications=replications,
                revision=revision,
            ),
        )
        ident = _cached(checkpoint_dir, "identification", lambda: identification(final, simulator))
        macro = _cached(
            checkpoint_dir, "macro", lambda: macro_check(data, final["config"], simulator)
        )
        checks = _cached(checkpoint_dir, "sanity", lambda: sanity(final))
        full_sim = simulator.bank_moments(final["config"], EVALUATION_SEEDS)
        robust = (
            None
            if skip_robustness
            else _cached(
                checkpoint_dir,
                "robustness",
                lambda: {
                    "bank_calibrated": _safe_robustness(
                        replace(final["config"], n_months=SCENARIO_MONTHS), ROBUST_SEEDS, workers
                    ),
                    "finding28": _safe_robustness(
                        replace(calibrated_config(), n_months=SCENARIO_MONTHS),
                        ROBUST_SEEDS,
                        workers,
                    ),
                },
            )
        )

    def public(result: dict[str, Any]) -> dict[str, Any]:
        keep = (
            "revision",
            "years",
            "real_moments",
            "moment_se",
            "bootstrap_replications",
            "direct_shares",
            "fits",
            "values",
            "distance",
        )
        out = {k: result[k] for k in keep}
        out["configuration"] = configuration_summary(result["config"])
        return out

    verdicts: dict[str, Any]
    if revision == 1:
        verdicts = {
            "K-D1": held_out["K-D1"],
            "K-D2": held_out["K-D2"],
            "K-D3": checks["K-D3"],
            "K-D4": macro["K-D4"],
            "K-D5": None if robust is None else robust["bank_calibrated"]["K-C"],
        }
    else:
        verdicts = {
            "K-E1": held_out["K-D1"],
            "K-E2": held_out["K-E2"],
            "K-E3": held_out["K-D2"],
            "K-E4": checks["K-D3"],
            "K-E5": macro["K-D4"],
            "K-E6": None if robust is None else robust["bank_calibrated"]["K-C"],
            "K-E7": held_out["K-E7"],
        }
    return {
        "revision": revision,
        "design": {
            "data": "FDIC national annual totals (commercial banks and savings institutions)",
            "train_years": list(TRAIN_YEARS),
            "test_years": list(TEST_YEARS),
            "full_years": list(FULL_YEARS),
            "simulation_paths": len(ESTIMATION_SEEDS),
            "evaluation_paths": len(EVALUATION_SEEDS),
            "scenario_months": SCENARIO_MONTHS,
            "bootstrap": {"block_years": 3, "replications": replications},
            "targeted": list(TARGETED_MOMENTS),
            "untargeted": list(UNTARGETED_MOMENTS),
            "loss_given_default_fixed_at": FIXED_LOSS_GIVEN_DEFAULT,
            "macro_block": "the Finding 28 estimates, not re-estimated",
            "not_calibrated": _not_calibrated(revision),
        },
        "finding28_banks": configuration_summary(calibrated_config()),
        "train_fit": public(trained),
        "out_of_sample": held_out,
        "full_fit": public(final),
        "identification": ident,
        "full_fit_simulated_moments": full_sim,
        "macro_check": macro,
        "sanity": checks,
        "robustness": robust,
        **verdicts,
        "seconds": time.time() - started,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--workers", type=int, default=18)
    parser.add_argument("--fits", type=int, default=3)
    parser.add_argument("--max-evaluations", type=int, default=600)
    parser.add_argument("--replications", type=int, default=300)
    parser.add_argument("--revision", type=int, choices=(1, 2), default=1)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--checkpoint-dir", type=Path, default=None)
    parser.add_argument("--skip-robustness", action="store_true")
    args = parser.parse_args(argv)
    result = run_study(
        workers=args.workers,
        fits=args.fits,
        max_evaluations=args.max_evaluations,
        replications=args.replications,
        checkpoint_dir=args.checkpoint_dir,
        skip_robustness=args.skip_robustness,
        revision=args.revision,
    )
    output = args.output or (OUTPUT if args.revision == 1 else OUTPUT_V2)
    output.write_text(json.dumps(_jsonable(result), indent=2) + "\n")
    print(f"wrote {output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
