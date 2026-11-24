"""Command line for the confirmatory analysis.

    python -m prometheus.confirmatory reproduce           # all three endpoints on the OLD data
    python -m prometheus.confirmatory fetch-cpi --start-year 2022 --end-year 2026 --out FILE
    python -m prometheus.confirmatory power --lock-meta FILE.meta.json --output power.json
    python -m prometheus.confirmatory e1 --seeds 10000-10049
    python -m prometheus.confirmatory e2 --series c.csv --series-sha256 H --scored-from 2023-04-30
    python -m prometheus.confirmatory e3 --new px.csv --new-sha256 H --scored-from 2023-05-04

`reproduce` reads only committed data and seeds 0-7, needs no freeze, and compares the new code with
the numbers Findings 8, 15 and 18 already report. The other three commands would use up untouched
data or reserved seeds, so they refuse to run until the protocol's freeze record is complete.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from prometheus.confirmatory import bls_fetch, e1_hedging, e2_inflation, e3_var, power
from prometheus.confirmatory.freeze import (
    PROTOCOL_PATH,
    NotFrozenError,
    require_frozen,
    require_seeds_allowed,
)
from prometheus.confirmatory.intervals import bonferroni_confidence
from prometheus.data_ingestion.kaggle_sp500 import load_daily_closes
from prometheus.orchestration.inflationcast_long_study import N_LAGS
from prometheus.orchestration.market_risk_study import DATA_PATH as YAHOO_SP500_PATH

FINDING_8_SEEDS = tuple(range(8))
FINDING_8_EPOCHS = (400, 800)
FINDING_18_WINDOW = (date(2000, 1, 31), date(2023, 1, 31))
FINDING_15_TEST_START = date(2008, 1, 1)

DOCUMENTED: dict[str, Any] = {
    "finding_8": {
        "claim": "about 1.04x-1.41x the static baseline's CVaR across 8 seeds, at 400 and 800 "
        "epochs; 0 of 8 seeds beat the baseline at either budget",
        "in_sample_ratio_range_rounded": [1.04, 1.41],
        "seeds_beating_baseline": 0,
    },
    "finding_18": {
        "n_months": 277,
        "mae_persistence": 0.326,
        "mae_base_effect": 0.226,
        "difference_rule_minus_persistence": -0.100,
        "interval_95": [-0.136, -0.068],
    },
    "finding_15": {
        "n_test_days": 3235,
        "garch_fhs": {
            "0.99": {"exceedances": 48, "pinball_bp": 3.92},
            "0.975": {"pinball_bp": 8.22},
        },
        "historical_250": {
            "0.99": {"exceedances": 56, "pinball_bp": 5.63},
            "0.975": {"pinball_bp": 10.40},
        },
    },
}


def _check(name: str, measured: Any, documented: Any, passed: bool) -> dict[str, Any]:
    return {"check": name, "measured": measured, "documented": documented, "match": bool(passed)}


def reproduce_e1(
    seeds: Sequence[int] = FINDING_8_SEEDS, epochs: Sequence[int] = FINDING_8_EPOCHS
) -> dict[str, Any]:
    """Finding 8 on its eight seeds at both budgets, with the new held-out statistic beside it."""
    runs = {e: [e1_hedging.evaluate_seed(s, n_epochs=e) for s in seeds] for e in epochs}
    in_sample = {e: [r.in_sample_ratio for r in rs] for e, rs in runs.items()}
    everything = [x for xs in in_sample.values() for x in xs]
    below = {e: int(sum(x < 1.0 for x in xs)) for e, xs in in_sample.items()}
    report: dict[str, Any] = {
        "in_sample_ratio_by_epochs": {
            str(e): [round(x, 3) for x in xs] for e, xs in in_sample.items()
        },
        "seeds_beating_baseline_in_sample": {str(e): n for e, n in below.items()},
        "held_out_ratio_by_epochs": {
            str(e): [round(r.ratio, 3) for r in rs] for e, rs in runs.items()
        },
        "seeds_beating_baseline_held_out": {
            str(e): int(sum(r.ratio < 1.0 for r in rs)) for e, rs in runs.items()
        },
        "note": "the held-out ratio is the new endpoint's statistic and has no documented value; "
        "it is exploratory here because these seeds are old",
    }
    if tuple(seeds) == FINDING_8_SEEDS and set(epochs) == set(FINDING_8_EPOCHS):
        documented = DOCUMENTED["finding_8"]
        report["checks"] = [
            _check(
                "in-sample ratio range over both budgets, rounded to 2 decimals",
                [round(min(everything), 2), round(max(everything), 2)],
                documented["in_sample_ratio_range_rounded"],
                [round(min(everything), 2), round(max(everything), 2)]
                == documented["in_sample_ratio_range_rounded"],
            ),
            _check(
                "seeds beating the baseline (in-sample), at each budget",
                below,
                documented["seeds_beating_baseline"],
                all(n == documented["seeds_beating_baseline"] for n in below.values()),
            ),
        ]
    return report


def reproduce_e2() -> dict[str, Any]:
    """Finding 18's Q1 (rule against persistence, 2000-01 .. 2023-01) with that study's settings."""
    months, levels = e2_inflation.committed_levels()
    result = e2_inflation.analyse_window(
        months,
        levels,
        scored_from=FINDING_18_WINDOW[0],
        scored_to=FINDING_18_WINDOW[1],
        confidence=0.95,
        block_length=12,
        n_resamples=2000,
        seed=0,
        sensitivity_block_lengths=(),
    )
    documented = DOCUMENTED["finding_18"]
    interval = result["interval"]
    # Finding 18 reports |rule| - |persistence|; this endpoint reports the opposite sign.
    difference = -interval["estimate"]
    low, high = -interval["high"], -interval["low"]
    summary = {
        "n_months": result["n_months"],
        "mae_persistence": round(result["mae_persistence"], 3),
        "mae_base_effect": round(result["mae_base_effect"], 3),
        "difference_rule_minus_persistence": round(difference, 3),
        "interval_95": [round(low, 3), round(high, 3)],
    }
    return {
        "measured": summary,
        "checks": [
            _check(name, summary[name], documented[name], summary[name] == documented[name])
            for name in documented
        ],
    }


def reproduce_e3() -> dict[str, Any]:
    """Finding 15's GARCH-FHS and 250-day historical simulation on the 2008-01 .. 2020-11 test."""
    dates, closes = load_daily_closes(YAHOO_SP500_PATH)
    result = e3_var.analyse_window(
        dates,
        closes,
        scored_from=FINDING_15_TEST_START,
        scored_to=None,
        confidence=0.95,
        n_resamples=200,
    )
    documented = DOCUMENTED["finding_15"]
    cov = result["coverage"]
    measured = {
        "n_test_days": result["n_days"],
        "garch_fhs": {
            "0.99": {
                "exceedances": int(cov["alpha_0.99"]["garch_fhs"]["n_exceedances"]),
                "pinball_bp": round(cov["alpha_0.99"]["garch_fhs"]["pinball_loss_bp"], 2),
            },
            "0.975": {"pinball_bp": round(cov["alpha_0.975"]["garch_fhs"]["pinball_loss_bp"], 2)},
        },
        "historical_250": {
            "0.99": {
                "exceedances": int(cov["alpha_0.99"]["historical_250"]["n_exceedances"]),
                "pinball_bp": round(cov["alpha_0.99"]["historical_250"]["pinball_loss_bp"], 2),
            },
            "0.975": {
                "pinball_bp": round(cov["alpha_0.975"]["historical_250"]["pinball_loss_bp"], 2)
            },
        },
    }
    checks = [
        _check(
            "n_test_days",
            measured["n_test_days"],
            documented["n_test_days"],
            measured["n_test_days"] == documented["n_test_days"],
        )
    ]
    for model in ("garch_fhs", "historical_250"):
        for level, values in documented[model].items():
            for key, value in values.items():
                got = measured[model][level][key]
                checks.append(_check(f"{model} {level} {key}", got, value, got == value))
    return {"measured": measured, "checks": checks}


def reproduce(
    seeds: Sequence[int] = FINDING_8_SEEDS,
    epochs: Sequence[int] = FINDING_8_EPOCHS,
    *,
    include_e1: bool = True,
) -> dict[str, Any]:
    """All three endpoints on the OLD data, against the documented numbers."""
    report: dict[str, Any] = {}
    if include_e1:
        report["E1_finding_8"] = reproduce_e1(seeds, epochs)
    report["E2_finding_18"] = reproduce_e2()
    report["E3_finding_15"] = reproduce_e3()
    checks = [c for part in report.values() for c in part.get("checks", [])]
    report["all_checks_match"] = bool(checks) and all(c["match"] for c in checks)
    report["n_checks"] = len(checks)
    return report


E1_THETAS = (0.02, 0.03, 0.05, 0.075, 0.10)
E2_THETAS = (0.03, 0.05, 0.075, 0.10, 0.15)
E3_RATES = (0.005, 0.01, 0.0148, 0.02, 0.03)
E3_DAYS = (750, 880)


def planned_e2_months(meta_path: Path, scored_from: date, scored_to: date) -> int:
    """How many target months the primary E2 window will hold, from the lock file's SIDECAR only
    (labels and the list of months with no published level; no value is read): a missing level at
    month k removes the targets k .. k+13."""
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    gaps = [int(m[:4]) * 12 + int(m[5:]) for m in meta["missing_months"]]
    first = scored_from.year * 12 + scored_from.month
    last = scored_to.year * 12 + scored_to.month
    return sum(1 for t in range(first, last + 1) if not any(g <= t <= g + N_LAGS + 1 for g in gaps))


def power_report(*, include_e1: bool = True, meta_path: Path | None = None) -> dict[str, Any]:
    """The power note, from the OLD data and seeds only."""
    confidence = bonferroni_confidence()
    report: dict[str, Any] = {
        "assumption": "the new sample behaves like the old one; planning numbers, not predictions",
        "target_power": power.TARGET_POWER,
        "interval_confidence": confidence,
    }
    if include_e1:
        results = [e1_hedging.evaluate_seed(s) for s in FINDING_8_SEEDS]
        theta = -np.log([r.ratio for r in results])
        sd = float(np.std(theta, ddof=1))
        rows = power.power_e1(
            sd,
            50,
            E1_THETAS + (e1_hedging.MARGIN,),
            confidence=confidence,
            margin=e1_hedging.MARGIN,
        )
        reference = next(r for r in rows if r["true_theta"] == e1_hedging.MARGIN)
        report["E1"] = {
            "spread_of_theta_across_old_seeds": sd,
            "old_seeds": list(FINDING_8_SEEDS),
            "n_seeds_planned": 50,
            "reference_effect": "the margin: a 5% CVaR improvement",
            "analytic_smallest_effect_at_80pct": power.analytic_e1_minimum_effect(
                sd, 50, confidence=confidence
            ),
            "table": rows,
            "power_at_reference": reference["power_better"],
            "verdict": power.verdict(reference["power_better"]),
        }
    months, levels = e2_inflation.committed_levels()
    old = e2_inflation.analyse_window(
        months,
        levels,
        scored_from=FINDING_18_WINDOW[0],
        scored_to=FINDING_18_WINDOW[1],
        confidence=0.95,
        block_length=12,
        n_resamples=200,
        seed=0,
        sensitivity_block_lengths=(),
    )
    d = power.old_e2_differences(old)
    n_planned = (
        planned_e2_months(meta_path, date(2023, 4, 30), date(2026, 10, 31))
        if meta_path is not None
        else 30
    )
    e2: dict[str, Any] = {
        "old_months": int(d.size),
        "old_mean_theta": float(d.mean()),
        "old_sd_theta": float(d.std(ddof=1)),
        "reference_effect": "the retrospective mean (Finding 18)",
        "by_sample_size": {},
    }
    for n in (n_planned, 24):
        rows = power.power_e2(
            d,
            n,
            E2_THETAS,
            confidence=confidence,
            margin=e2_inflation.MARGIN,
            block_length=e2_inflation.BLOCK_LENGTH,
        )
        at_ref = min(rows, key=lambda r: abs(r["true_theta"] - float(d.mean())))
        e2["by_sample_size"][str(n)] = {
            "table": rows,
            "smallest_effect_at_80pct": power.smallest_effect(rows),
            "power_at_reference": at_ref["power_better"],
            "verdict": power.verdict(at_ref["power_better"]),
        }
    report["E2"] = e2
    e3: dict[str, Any] = {"nominal_rate": 0.01, "by_days": {}}
    for n_days in E3_DAYS:
        rows = power.power_e3(E3_RATES, n_days, nominal=0.01, confidence=confidence)
        at_ref = next(r for r in rows if r["true_rate"] == 0.0148)
        e3["by_days"][str(n_days)] = {
            "table": rows,
            "false_alarm_rate_at_nominal": next(
                r["power_to_exclude_nominal"] for r in rows if r["true_rate"] == 0.01
            ),
            "power_at_finding_15_rate": at_ref["power_to_exclude_nominal"],
            "verdict": power.verdict(at_ref["power_to_exclude_nominal"]),
        }
    report["E3"] = e3
    return report


def _parse_seeds(text: str) -> list[int]:
    if "-" in text:
        first, last = text.split("-", 1)
        return list(range(int(first), int(last) + 1))
    return [int(part) for part in text.split(",")]


def _emit(report: dict[str, Any], output: Path | None) -> None:
    text = json.dumps(report, indent=2)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text)
    print(text)


def _add_data_arguments(sub: argparse.ArgumentParser, flag: str, what: str) -> None:
    sub.add_argument(f"--{flag}", dest="data_path", type=Path, required=True, help=what)
    sub.add_argument(
        f"--{flag}-sha256", dest="data_sha256", required=True, help="the SHA-256 recorded for it"
    )
    sub.add_argument("--scored-from", type=date.fromisoformat, required=True)
    sub.add_argument("--scored-to", type=date.fromisoformat)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--protocol", type=Path, default=PROTOCOL_PATH)
    parser.add_argument("--output", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    fetch = commands.add_parser(
        "fetch-cpi", help="lock a BLS CPI series; prints labels and digests, never a value"
    )
    fetch.add_argument("--series-id", default="CUSR0000SA0")
    fetch.add_argument("--start-year", type=int, required=True)
    fetch.add_argument("--end-year", type=int, required=True)
    fetch.add_argument("--out", type=Path, required=True)
    pw = commands.add_parser("power", help="power notes from the OLD data and seeds")
    pw.add_argument("--skip-e1", action="store_true", help="skip the slow hedging runs")
    pw.add_argument("--lock-meta", type=Path, help="sidecar of the locked CPI file (labels only)")
    rep = commands.add_parser("reproduce", help="the new code against Findings 8, 15 and 18")
    rep.add_argument("--skip-e1", action="store_true", help="skip the slow hedging runs")
    e1 = commands.add_parser("e1", help="E1 on fresh seeds (needs a frozen protocol)")
    e1.add_argument("--seeds", default="10000-10049")
    _add_data_arguments(
        commands.add_parser("e2", help="E2 on untouched CPI months"),
        "series",
        "one-vintage CPI series (month,level) that reaches back 13 months before --scored-from",
    )
    _add_data_arguments(
        commands.add_parser("e3", help="E3 on untouched S&P 500 days"),
        "new",
        "CSV (date,close) of the closes after the committed series",
    )
    args = parser.parse_args(argv)

    try:
        if args.command == "reproduce":
            report = reproduce(include_e1=not args.skip_e1)
            _emit(report, args.output)
            return 0 if report["all_checks_match"] else 1
        if args.command == "power":
            _emit(power_report(include_e1=not args.skip_e1, meta_path=args.lock_meta), args.output)
            return 0
        if args.command == "fetch-cpi":
            fetched = bls_fetch.fetch_series(
                args.series_id, args.start_year, args.end_year, bls_fetch.UrllibPoster()
            )
            _emit(bls_fetch.write_locked(fetched, args.out), args.output)
            return 0
        confidence = bonferroni_confidence()
        if args.command == "e1":
            seeds = _parse_seeds(args.seeds)
            require_seeds_allowed(seeds, args.protocol)
            _emit(e1_hedging.run_e1(seeds, confidence=confidence), args.output)
            return 0
        require_frozen(args.protocol)
        if args.command == "e2":
            series = e2_inflation.load_new_levels(args.data_path, args.data_sha256)
            report = e2_inflation.analyse_window(
                *series,
                scored_from=args.scored_from,
                scored_to=args.scored_to,
                confidence=confidence,
            )
            report["vintage_check"] = e2_inflation.vintage_overlap(
                e2_inflation.committed_levels(), series
            )
            _emit(report, args.output)
            return 0
        old_closes = e3_var.committed_closes()
        new_closes = e3_var.load_new_closes(args.data_path, args.data_sha256)
        dates, closes = e3_var.merge_closes(old_closes, new_closes)
        _emit(
            e3_var.analyse_window(
                dates,
                closes,
                scored_from=args.scored_from,
                scored_to=args.scored_to,
                confidence=confidence,
            ),
            args.output,
        )
        return 0
    except NotFrozenError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
