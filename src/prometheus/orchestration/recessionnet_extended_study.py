"""RECESSIONNET "more data" study (PR-198): does MORE HISTORY or MORE FEATURES make
the recession classifiers more accurate on the same, untouched test months?

The tempting reading of "train it on more data" is "add more columns". This
repository's own earlier evidence (Finding 12) says that can hurt a data-starved
model: the Kaggle snapshot has only ~220 training months and three recession
episodes before the 2001 validation split (two of them fragments: one month
of 1982 and three of 2001). So the study separates the two levers
instead of bundling them, on four feature sets that all share the SAME test months
(decision months from 2008-01 on, 175 of them, 14 positive):

- `baseline_5`     the five PR-145 features (GDP, claims, Fed funds, M2, NASDAQ),
                   1981-12 onward -- the reference.
- `macro_5_short`  five FRED-sourced features that reach back to the 1960s
                   (GDP, claims, Fed funds, unemployment, seasonally adjusted CPI),
                   restricted to the SAME 1981-12 onward window.
- `macro_5_long`   the identical five features over their full common history
                   (1968-02 onward): MORE RECESSIONS in training (1969-70, 1973-75,
                   1980, 1981-82, 1990-91, and the start of 2001) with the
                   features held fixed.
- `extended_11`    `baseline_5` plus unemployment, seasonally adjusted CPI, bank
                   credit, S&P 500 return and realised volatility, and the 10Y-3M
                   term spread: MORE FEATURES with the history held fixed.

`macro_5_long` vs. `macro_5_short` isolates the effect of history; `extended_11` vs.
`baseline_5` isolates the effect of features. Everything else is identical and
nothing is tuned on the test months: each learned model is early-stopped on the
validation split only (PR-142's methodology), at the production default patience.

Inference: per test month, the seed-averaged squared error of one configuration is
subtracted from the other's, and a MOVING-BLOCK bootstrap (block length = the
6-month horizon, because overlapping monthly forecasts are serially dependent)
gives the confidence interval of the mean difference in Brier score.

This is a standalone research CLI (no network call, all data committed), not a
queueable job kind.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from prometheus.data_ingestion.kaggle_build import add_months, month_end
from prometheus.data_ingestion.kaggle_macro import (
    KAGGLE_SERIES_IDS,
    load_kaggle_us_macro_observations,
)
from prometheus.data_ingestion.kaggle_macro_extended import (
    load_extended_macro_observations,
    series_id,
)
from prometheus.data_ingestion.kaggle_term_spread import (
    TERM_SPREAD_SERIES_ID,
    load_term_spread_observations,
)
from prometheus.econosim.pit import MacroObservation
from prometheus.experiments.block_bootstrap import moving_block_bootstrap
from prometheus.recessionnet.dataset import (
    RecessionDataset,
    build_recession_dataset,
    chronological_split,
)
from prometheus.recessionnet.evaluation import (
    BenchmarkReport,
    run_recessionnet_benchmark_with_early_stopping,
)
from prometheus.recessionnet.labels import NBER_RECESSIONS

DATA_DIR = Path(__file__).resolve().parents[3] / "data_cache"
WINDOW = 6
HORIZON = 6
VALIDATION_SPLIT = date(2001, 1, 1)
TEST_SPLIT = date(2008, 1, 1)
SHARED_FIRST_ROW = date(1981, 12, 31)
LAST_ROW = date(2023, 1, 31)
MODELS = ("base_rate", "logistic_regression", "classical_matched_mlp", "hybrid_quantum")
_MACRO_5 = ("GDP_YOY", "CLAIMS_YOY", "FEDFUNDS", "UNRATE", "CPI_YOY_SA")
_NEW_6 = ("UNRATE", "CPI_YOY_SA", "BANK_CREDIT_YOY", "SPX_YOY", "SPX_VOL")


@dataclass(frozen=True, slots=True)
class FeatureSet:
    name: str
    description: str
    series_ids: tuple[str, ...]
    observations: tuple[MacroObservation, ...]
    first_row: date
    last_row: date


def month_ends(first: date, last: date) -> list[date]:
    rows: list[date] = []
    current = first
    while current <= last:
        rows.append(current)
        current = add_months(current, 1)
    return rows


def trim_observations(
    observations: Sequence[MacroObservation],
    wanted: Sequence[str],
    first: date,
    last: date,
) -> tuple[MacroObservation, ...]:
    """Keep only the wanted series inside [first, last] and REQUIRE every one of them
    to have a value for every month: `build_monthly_series_matrix` has no per-series
    masking, so a gap must fail loudly here rather than shift the sample silently."""
    kept = tuple(
        o for o in observations if o.series_id in wanted and first <= o.observation_at <= last
    )
    expected = set(month_ends(first, last))
    for sid in wanted:
        have = {o.observation_at for o in kept if o.series_id == sid}
        missing = sorted(expected - have)
        if missing:
            raise ValueError(f"{sid} has no value for {len(missing)} months, first {missing[0]}")
    return kept


def common_first_row(observations: Sequence[MacroObservation], wanted: Sequence[str]) -> date:
    """The first month-end at which every wanted series has a value."""
    return max(min(o.observation_at for o in observations if o.series_id == sid) for sid in wanted)


def build_feature_sets(data_dir: Path = DATA_DIR) -> dict[str, FeatureSet]:
    baseline = load_kaggle_us_macro_observations(data_dir / "kaggle_us_macro_monthly.csv")
    extended = load_extended_macro_observations(data_dir / "kaggle_us_macro_extended_monthly.csv")
    spread = load_term_spread_observations(data_dir / "kaggle_term_spread_monthly.csv")
    macro_5 = tuple(series_id(c) for c in _MACRO_5)
    extended_11 = (*KAGGLE_SERIES_IDS, *(series_id(c) for c in _NEW_6[:5]), TERM_SPREAD_SERIES_ID)
    long_first = common_first_row(extended, macro_5)
    pool = [*baseline, *extended, *spread]

    def make(
        name: str, text: str, ids: tuple[str, ...], first: date, source: Sequence[MacroObservation]
    ) -> FeatureSet:
        return FeatureSet(
            name, text, ids, trim_observations(source, ids, first, LAST_ROW), first, LAST_ROW
        )

    return {
        "baseline_5": make(
            "baseline_5",
            "PR-145 features: GDP, claims, Fed funds, M2, NASDAQ (1981-12 onward)",
            KAGGLE_SERIES_IDS,
            SHARED_FIRST_ROW,
            baseline,
        ),
        "macro_5_short": make(
            "macro_5_short",
            "GDP, claims, Fed funds, unemployment, SA CPI over the same 1981-12 window",
            macro_5,
            SHARED_FIRST_ROW,
            extended,
        ),
        "macro_5_long": make(
            "macro_5_long",
            "the same five features over their full common history (more recessions)",
            macro_5,
            long_first,
            extended,
        ),
        "extended_11": make(
            "extended_11",
            "baseline_5 + unemployment, SA CPI, bank credit, S&P 500 return and volatility, "
            "term spread",
            extended_11,
            SHARED_FIRST_ROW,
            pool,
        ),
    }


def _training_episodes(train_targets: Sequence[date]) -> int:
    keys = {(d.year, d.month) for d in train_targets}
    return sum(
        1
        for period in NBER_RECESSIONS
        if any(period.contains_contraction_month(month_end(y, m)) for y, m in keys)
    )


@dataclass(frozen=True, slots=True)
class SeedRun:
    test: RecessionDataset
    report: BenchmarkReport
    counts: dict[str, int]


def run_seed(
    feature_set: FeatureSet,
    seed: int,
    *,
    max_epochs: int,
    patience: int,
    bootstrap_resamples: int,
) -> SeedRun:
    dataset = build_recession_dataset(
        feature_set.observations,
        feature_set.series_ids,
        NBER_RECESSIONS,
        window=WINDOW,
        horizon=HORIZON,
    )
    train_full, test = chronological_split(dataset, TEST_SPLIT)
    train_proper, validation = chronological_split(train_full, VALIDATION_SPLIT)
    report = run_recessionnet_benchmark_with_early_stopping(
        train_proper,
        validation,
        test,
        seed=seed,
        max_epochs=max_epochs,
        patience=patience,
        bootstrap_resamples=bootstrap_resamples,
    )
    counts = {
        "n_train": len(train_proper.labels),
        "n_train_positive": int(train_proper.labels.sum()),
        "n_train_recession_episodes": _training_episodes(train_proper.target_months),
        "n_validation": len(validation.labels),
        "n_test": len(test.labels),
        "n_test_positive": int(test.labels.sum()),
    }
    return SeedRun(test, report, counts)


def _verdict(ci_low: float, ci_high: float) -> str:
    if ci_high < 0:
        return "lower_brier_first_is_better"
    if ci_low > 0:
        return "higher_brier_first_is_worse"
    return "inconclusive"


def run_study(
    feature_sets: dict[str, FeatureSet],
    *,
    seeds: Sequence[int],
    max_epochs: int = 500,
    patience: int = 20,
    bootstrap_resamples: int = 2000,
    block_resamples: int = 2000,
) -> dict[str, Any]:
    runs: dict[str, list[SeedRun]] = {
        name: [
            run_seed(
                fs,
                s,
                max_epochs=max_epochs,
                patience=patience,
                bootstrap_resamples=bootstrap_resamples,
            )
            for s in seeds
        ]
        for name, fs in feature_sets.items()
    }
    reference = next(iter(runs.values()))[0].test.decision_months
    for name, seed_runs in runs.items():
        for r in seed_runs:
            if r.test.decision_months != reference:
                raise ValueError(f"{name}: test decision months differ from the other feature sets")

    results: dict[str, Any] = {}
    mean_squared_errors: dict[str, dict[str, np.ndarray]] = {}
    for name, seed_runs in runs.items():
        results[name] = {}
        mean_squared_errors[name] = {}
        for model in MODELS:
            briers = [r.report.metrics[model].brier_score for r in seed_runs]
            aucs = [r.report.metrics[model].roc_auc for r in seed_runs]
            valid_aucs = [a for a in aucs if a is not None]
            results[name][model] = {
                "brier_mean": float(np.mean(briers)),
                "brier_std": float(np.std(briers)),
                "auc_mean": float(np.mean(valid_aucs)) if valid_aucs else None,
                "auc_std": float(np.std(valid_aucs)) if valid_aucs else None,
                "auc_per_seed": aucs,
                "brier_per_seed": briers,
            }
            mean_squared_errors[name][model] = np.mean(
                [np.asarray(r.report.metrics[model].squared_errors) for r in seed_runs], axis=0
            )

    rng = np.random.default_rng(0)
    questions = {
        "more_history": ("macro_5_long", "macro_5_short"),
        "more_features": ("extended_11", "baseline_5"),
        "feature_swap_only": ("macro_5_short", "baseline_5"),
    }
    comparisons: dict[str, Any] = {}
    for label, (first, second) in questions.items():
        per_model: dict[str, Any] = {}
        for model in MODELS:
            difference = mean_squared_errors[first][model] - mean_squared_errors[second][model]
            boot = moving_block_bootstrap(
                np.mean, difference, HORIZON, rng, n_resamples=block_resamples
            )
            per_model[model] = {
                "delta_brier_first_minus_second": boot.point_estimate,
                "ci_low": boot.ci_low,
                "ci_high": boot.ci_high,
                "verdict": _verdict(boot.ci_low, boot.ci_high),
            }
        comparisons[label] = {"first": first, "second": second, "models": per_model}

    sizes = {name: seed_runs[0].counts for name, seed_runs in runs.items()}
    return {
        "config": {
            "seeds": list(seeds),
            "window": WINDOW,
            "horizon": HORIZON,
            "validation_split": VALIDATION_SPLIT.isoformat(),
            "test_split": TEST_SPLIT.isoformat(),
            "max_epochs": max_epochs,
            "patience": patience,
            "block_length": HORIZON,
        },
        "feature_sets": {
            name: {
                "description": fs.description,
                "series_ids": list(fs.series_ids),
                "first_row": fs.first_row.isoformat(),
                "last_row": fs.last_row.isoformat(),
                **sizes[name],
            }
            for name, fs in feature_sets.items()
        },
        "results": results,
        "comparisons": comparisons,
        "caveats": [
            "175 test months with 14 positives from two recession episodes (2008-09, 2020): "
            "every interval is wide and the test set is the same one every earlier RECESSIONNET "
            "finding used.",
            "Twelve model x question intervals are reported; none is corrected for multiplicity.",
            "Feature publication lags are fixed assumptions, and GDP / seasonally adjusted CPI "
            "are latest-revised values, not first-release vintages.",
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--max-epochs", type=int, default=500)
    parser.add_argument("--patience", type=int, default=20)
    parser.add_argument("--bootstrap-resamples", type=int, default=2000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.seeds < 1:
        parser.error("--seeds must be a positive integer")
    report = run_study(
        build_feature_sets(),
        seeds=list(range(args.seeds)),
        max_epochs=args.max_epochs,
        patience=args.patience,
        bootstrap_resamples=args.bootstrap_resamples,
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
