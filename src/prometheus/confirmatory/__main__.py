"""Command line for the confirmatory analysis.

    python -m prometheus.confirmatory reproduce           # all three endpoints on the OLD data
    python -m prometheus.confirmatory e1 --seeds 10000-10049
    python -m prometheus.confirmatory e2 --new cpi.csv --new-sha256 <hex> --scored-from 2023-04-30
    python -m prometheus.confirmatory e3 --new px.csv --new-sha256 <hex> --scored-from 2023-05-04

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

from prometheus.confirmatory import e1_hedging, e2_inflation, e3_var
from prometheus.confirmatory.freeze import (
    PROTOCOL_PATH,
    NotFrozenError,
    require_frozen,
    require_seeds_allowed,
)
from prometheus.confirmatory.intervals import bonferroni_confidence
from prometheus.data_ingestion.kaggle_sp500 import load_daily_closes
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


def _add_data_arguments(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("--new", type=Path, required=True, help="CSV of the new observations")
    sub.add_argument("--new-sha256", required=True, help="the SHA-256 recorded for that file")
    sub.add_argument("--scored-from", type=date.fromisoformat, required=True)
    sub.add_argument("--scored-to", type=date.fromisoformat)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--protocol", type=Path, default=PROTOCOL_PATH)
    parser.add_argument("--output", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    rep = commands.add_parser("reproduce", help="the new code against Findings 8, 15 and 18")
    rep.add_argument("--skip-e1", action="store_true", help="skip the slow hedging runs")
    e1 = commands.add_parser("e1", help="E1 on fresh seeds (needs a frozen protocol)")
    e1.add_argument("--seeds", default="10000-10049")
    _add_data_arguments(commands.add_parser("e2", help="E2 on untouched CPI months"))
    _add_data_arguments(commands.add_parser("e3", help="E3 on untouched S&P 500 days"))
    args = parser.parse_args(argv)

    try:
        if args.command == "reproduce":
            report = reproduce(include_e1=not args.skip_e1)
            _emit(report, args.output)
            return 0 if report["all_checks_match"] else 1
        confidence = bonferroni_confidence()
        if args.command == "e1":
            seeds = _parse_seeds(args.seeds)
            require_seeds_allowed(seeds, args.protocol)
            _emit(e1_hedging.run_e1(seeds, confidence=confidence), args.output)
            return 0
        require_frozen(args.protocol)
        if args.command == "e2":
            old = e2_inflation.committed_levels()
            new = e2_inflation.load_new_levels(args.new, args.new_sha256)
            months, levels = e2_inflation.merge_levels(old, new)
            _emit(
                e2_inflation.analyse_window(
                    months,
                    levels,
                    scored_from=args.scored_from,
                    scored_to=args.scored_to,
                    confidence=confidence,
                ),
                args.output,
            )
            return 0
        old_closes = e3_var.committed_closes()
        new_closes = e3_var.load_new_closes(args.new, args.new_sha256)
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
