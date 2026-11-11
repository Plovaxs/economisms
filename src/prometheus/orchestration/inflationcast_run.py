"""Run the INFLATIONCAST demonstration end to end: load the real,
committed BLS CPI-U series (`data_cache/us_cpi_monthly.csv`) and the
real, committed Kaggle macro snapshot
(`data_cache/kaggle_us_macro_monthly.csv`), build the point-in-time-
safe mixed-frequency nowcasting dataset (`inflationcast.data`), split
it three ways -- train-proper / validation / test, all strictly
chronological -- and benchmark naive persistence / linear regression /
a parameter-matched classical MLP / a hybrid quantum regressor against
`InflationGRU`'s calibrated forecast
(`inflationcast.evaluation.run_inflationcast_benchmark`).

Unlike `qmacro_run`/`recessionnet_run`, this CLI makes NO live network
call at all, the same reason `recessionnet_kaggle_run` doesn't: both
CSVs are already-committed, already-derived snapshots (see their own
`.meta.json` sidecars for exact provenance), so a demo run of this
script cannot fail on a network problem."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

import numpy as np

from prometheus.data_ingestion.kaggle_macro import load_kaggle_us_macro_observations
from prometheus.econosim.pit import MacroObservation, PointInTimeStore
from prometheus.inflationcast.data import (
    ALL_SERIES_IDS,
    InflationNowcastExample,
    build_inflationcast_dataset,
    chronological_split,
    load_cpi_observations,
)
from prometheus.inflationcast.evaluation import (
    InflationcastBenchmarkReport,
    run_inflationcast_benchmark,
)

DEFAULT_CPI_CSV_PATH = (
    Path(__file__).resolve().parents[3] / "data_cache" / "us_cpi_monthly.csv"
)
DEFAULT_MACRO_CSV_PATH = (
    Path(__file__).resolve().parents[3] / "data_cache" / "kaggle_us_macro_monthly.csv"
)
Verdict = Literal["gru_better", "classical_better", "inconclusive"]


@dataclass(frozen=True, slots=True)
class InflationcastRunConfig:
    seed: int = 0
    max_epochs: int = 500
    patience: int = 20
    window: int = 6
    validation_split_date: date = date(2019, 1, 1)
    test_split_date: date = date(2022, 1, 1)
    bootstrap_resamples: int = 2_000
    calibration_coverage: float = 0.90

    def __post_init__(self) -> None:
        if self.seed < 0:
            raise ValueError("seed must be non-negative")
        if self.max_epochs < 1:
            raise ValueError("max_epochs must be a positive integer")
        if self.patience < 1:
            raise ValueError("patience must be a positive integer")
        if self.window < 1:
            raise ValueError("window must be a positive integer")
        if self.bootstrap_resamples < 1:
            raise ValueError("bootstrap_resamples must be a positive integer")
        if not 0.0 < self.calibration_coverage < 1.0:
            raise ValueError("calibration_coverage must be in (0, 1)")
        if self.validation_split_date >= self.test_split_date:
            raise ValueError("validation_split_date must be strictly before test_split_date")


@dataclass(frozen=True, slots=True)
class InflationcastDemoResult:
    config: InflationcastRunConfig
    n_train_samples: int
    n_validation_samples: int
    n_test_samples: int
    report: InflationcastBenchmarkReport
    verdict: Verdict


def _verdict(report: InflationcastBenchmarkReport) -> Verdict:
    bootstrap = report.gru_vs_best_classical
    if not bootstrap.excludes_zero():
        return "inconclusive"
    return "gru_better" if bootstrap.point_estimate < 0 else "classical_better"


def _arrays(examples: Sequence[InflationNowcastExample]) -> tuple[np.ndarray, np.ndarray]:
    features = np.stack([e.features for e in examples])
    targets = np.array([e.target for e in examples])
    return features, targets


def run_inflationcast_demo(
    observations: Sequence[MacroObservation], config: InflationcastRunConfig
) -> InflationcastDemoResult:
    store = PointInTimeStore()
    for observation in observations:
        store.record(observation)

    cpi_months = sorted({o.observation_at for o in observations if o.series_id == "CPI_YOY"})
    examples = build_inflationcast_dataset(store, cpi_months, window=config.window)

    train_full, test = chronological_split(examples, config.test_split_date)
    train, validation = chronological_split(train_full, config.validation_split_date)

    train_features, train_targets = _arrays(train)
    validation_features, validation_targets = _arrays(validation)
    test_features, test_targets = _arrays(test)

    report = run_inflationcast_benchmark(
        train_features,
        train_targets,
        validation_features,
        validation_targets,
        test_features,
        test_targets,
        n_series=len(ALL_SERIES_IDS),
        seed=config.seed,
        max_epochs=config.max_epochs,
        patience=config.patience,
        bootstrap_resamples=config.bootstrap_resamples,
        calibration_coverage=config.calibration_coverage,
    )
    return InflationcastDemoResult(
        config=config,
        n_train_samples=len(train),
        n_validation_samples=len(validation),
        n_test_samples=len(test),
        report=report,
        verdict=_verdict(report),
    )


def summary_payload(result: InflationcastDemoResult) -> dict[str, Any]:
    report = result.report
    bootstrap = report.gru_vs_best_classical
    calibration = report.gru_calibration
    return {
        "data_source": "bls_public_api_and_kaggle_local_snapshot",
        "dataset": {
            "n_train": result.n_train_samples,
            "n_validation": result.n_validation_samples,
            "n_test": result.n_test_samples,
            "window_months": result.config.window,
            "series_ids": list(ALL_SERIES_IDS),
            "validation_split_date": result.config.validation_split_date.isoformat(),
            "test_split_date": result.config.test_split_date.isoformat(),
        },
        "models": {
            name: {
                "mae": metrics.mae,
                "rmse": metrics.rmse,
                "mase": metrics.mase,
                "n_parameters": report.parameter_counts[name],
                "train_seconds": report.train_seconds[name],
                "selected_epoch": report.selected_epochs.get(name),
            }
            for name, metrics in report.metrics.items()
        },
        "best_point_challenger": report.best_point_challenger,
        "gru_calibration": {
            "n_observations": calibration.n_observations,
            "nominal_coverage": calibration.nominal_coverage,
            "observed_coverage": calibration.observed_coverage,
            "p_value": calibration.p_value,
        },
        "gru_vs_best_classical": {
            "point_estimate": bootstrap.point_estimate,
            "ci_low": bootstrap.ci_low,
            "ci_high": bootstrap.ci_high,
            "confidence": bootstrap.confidence,
            "excludes_zero": bootstrap.excludes_zero(),
        },
        "verdict": result.verdict,
        "run_manifest": report.run_manifest.to_dict(),
    }


def main(
    argv: Sequence[str] | None = None,
    *,
    cpi_csv_path: Path | None = None,
    macro_csv_path: Path | None = None,
) -> int:
    """`cpi_csv_path`/`macro_csv_path` are injectable purely so tests
    can point at small fixtures instead of the full real snapshots; a
    real invocation never passes them."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-epochs", type=int, default=500)
    parser.add_argument("--patience", type=int, default=20)
    parser.add_argument("--window", type=int, default=6)
    parser.add_argument("--validation-split-date", type=str, default="2019-01-01")
    parser.add_argument("--test-split-date", type=str, default="2022-01-01")
    parser.add_argument("--bootstrap-resamples", type=int, default=2_000)
    parser.add_argument("--calibration-coverage", type=float, default=0.90)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        config = InflationcastRunConfig(
            seed=args.seed,
            max_epochs=args.max_epochs,
            patience=args.patience,
            window=args.window,
            validation_split_date=date.fromisoformat(args.validation_split_date),
            test_split_date=date.fromisoformat(args.test_split_date),
            bootstrap_resamples=args.bootstrap_resamples,
            calibration_coverage=args.calibration_coverage,
        )
    except ValueError as exc:
        parser.error(str(exc))

    cpi_observations = load_cpi_observations(cpi_csv_path or DEFAULT_CPI_CSV_PATH)
    macro_observations = load_kaggle_us_macro_observations(macro_csv_path or DEFAULT_MACRO_CSV_PATH)
    result = run_inflationcast_demo([*cpi_observations, *macro_observations], config)
    payload = summary_payload(result)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
