"""Run the real Q-MACRO demonstration end to end: fetch the real
Kenneth French monthly factor series live, build a point-in-time-safe
regression dataset (h-months-ahead Mkt-RF), split it three ways --
train-proper / validation / test, all strictly chronological -- and
benchmark the hybrid quantum regressor against AR(p), linear
regression, a parameter-matched classical MLP and a naive persistence
baseline (`macrocore.quantum_benchmark.run_qmacro_benchmark`).

Mirrors `orchestration.recessionnet_run`'s own structure and its
`transport`-injection pattern for the same reason: one real network
call happens inside `load_real_ff3_observations_or_cached` (reused
directly from that module, not duplicated), so `main`'s `transport`
parameter lets `tests/unit/test_qmacro_run.py` exercise the full CLI
hermetically. The same function's offline-fallback behavior (a
committed snapshot at `data_cache/ff3_monthly_snapshot.csv` when a
live fetch fails) applies here too, for the same reason: a live demo
should not die on a bad wifi moment.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

from prometheus.data_ingestion.egress_allowlist import default_ingestion_transport
from prometheus.data_ingestion.transport import HttpTransport
from prometheus.econosim.pit import MacroObservation
from prometheus.macrocore.quantum_benchmark import QMacroBenchmarkReport, run_qmacro_benchmark
from prometheus.macrocore.regression_dataset import (
    build_macro_regression_dataset,
    chronological_split,
    extract_target_history,
)
from prometheus.orchestration.recessionnet_run import (
    DataSource,
    load_real_ff3_observations_or_cached,
)

DEFAULT_FEATURE_SERIES_IDS: tuple[str, ...] = ("FF3_Mkt-RF", "FF3_SMB", "FF3_HML", "FF3_RF")
DEFAULT_TARGET_SERIES_ID = "FF3_Mkt-RF"
Verdict = Literal["quantum_better", "classical_better", "inconclusive"]


@dataclass(frozen=True, slots=True)
class QMacroRunConfig:
    seed: int = 0
    max_epochs: int = 500
    patience: int = 20
    window: int = 6
    horizon: int = 6
    ar_order: int = 3
    validation_split_date: date = date(1988, 1, 1)
    test_split_date: date = date(2000, 1, 1)
    bootstrap_resamples: int = 2_000
    feature_series_ids: tuple[str, ...] = DEFAULT_FEATURE_SERIES_IDS
    target_series_id: str = DEFAULT_TARGET_SERIES_ID

    def __post_init__(self) -> None:
        if self.seed < 0:
            raise ValueError("seed must be non-negative")
        if self.max_epochs < 1:
            raise ValueError("max_epochs must be a positive integer")
        if self.patience < 1:
            raise ValueError("patience must be a positive integer")
        if self.window < 1:
            raise ValueError("window must be a positive integer")
        if self.horizon < 1:
            raise ValueError("horizon must be a positive integer")
        if self.ar_order < 1:
            raise ValueError("ar_order must be a positive integer")
        if self.bootstrap_resamples < 1:
            raise ValueError("bootstrap_resamples must be a positive integer")
        if not self.feature_series_ids:
            raise ValueError("feature_series_ids must not be empty")
        if self.validation_split_date >= self.test_split_date:
            raise ValueError("validation_split_date must be strictly before test_split_date")


@dataclass(frozen=True, slots=True)
class QMacroDemoResult:
    config: QMacroRunConfig
    n_train_samples: int
    n_validation_samples: int
    n_test_samples: int
    report: QMacroBenchmarkReport
    verdict: Verdict


def _verdict(report: QMacroBenchmarkReport) -> Verdict:
    bootstrap = report.quantum_vs_best_classical
    if not bootstrap.excludes_zero():
        return "inconclusive"
    return "quantum_better" if bootstrap.point_estimate < 0 else "classical_better"


def run_qmacro_demo(
    observations: Sequence[MacroObservation], config: QMacroRunConfig
) -> QMacroDemoResult:
    dataset = build_macro_regression_dataset(
        observations,
        config.feature_series_ids,
        config.target_series_id,
        window=config.window,
        horizon=config.horizon,
    )
    train_full, test = chronological_split(dataset, config.test_split_date)
    train_proper, validation = chronological_split(train_full, config.validation_split_date)
    months, values = extract_target_history(observations, config.target_series_id)

    report = run_qmacro_benchmark(
        train_proper,
        validation,
        test,
        months,
        values.tolist(),
        seed=config.seed,
        ar_order=config.ar_order,
        max_epochs=config.max_epochs,
        patience=config.patience,
        bootstrap_resamples=config.bootstrap_resamples,
    )
    return QMacroDemoResult(
        config=config,
        n_train_samples=len(train_proper.targets),
        n_validation_samples=len(validation.targets),
        n_test_samples=len(test.targets),
        report=report,
        verdict=_verdict(report),
    )


def _summary_payload(result: QMacroDemoResult, data_source: DataSource) -> dict[str, Any]:
    report = result.report
    bootstrap = report.quantum_vs_best_classical
    return {
        "data_source": data_source,
        "dataset": {
            "n_train": result.n_train_samples,
            "n_validation": result.n_validation_samples,
            "n_test": result.n_test_samples,
            "window_months": result.config.window,
            "horizon_months": result.config.horizon,
            "target_series_id": result.config.target_series_id,
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
        "best_classical_challenger": report.best_classical_challenger,
        "quantum_vs_best_classical": {
            "point_estimate": bootstrap.point_estimate,
            "ci_low": bootstrap.ci_low,
            "ci_high": bootstrap.ci_high,
            "confidence": bootstrap.confidence,
            "excludes_zero": bootstrap.excludes_zero(),
        },
        "verdict": result.verdict,
        "run_manifest": report.run_manifest.to_dict(),
    }


def main(argv: Sequence[str] | None = None, *, transport: HttpTransport | None = None) -> int:
    """`transport` is injectable for hermetic testing, same pattern as
    `orchestration.recessionnet_run.main`; a real invocation never
    passes it."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-epochs", type=int, default=500)
    parser.add_argument("--patience", type=int, default=20)
    parser.add_argument("--window", type=int, default=6)
    parser.add_argument("--horizon", type=int, default=6)
    parser.add_argument("--ar-order", type=int, default=3)
    parser.add_argument("--validation-split-date", type=str, default="1988-01-01")
    parser.add_argument("--test-split-date", type=str, default="2000-01-01")
    parser.add_argument("--bootstrap-resamples", type=int, default=2_000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        config = QMacroRunConfig(
            seed=args.seed,
            max_epochs=args.max_epochs,
            patience=args.patience,
            window=args.window,
            horizon=args.horizon,
            ar_order=args.ar_order,
            validation_split_date=date.fromisoformat(args.validation_split_date),
            test_split_date=date.fromisoformat(args.test_split_date),
            bootstrap_resamples=args.bootstrap_resamples,
        )
    except ValueError as exc:
        parser.error(str(exc))

    real_transport = transport if transport is not None else default_ingestion_transport()
    observations, data_source = load_real_ff3_observations_or_cached(real_transport)
    result = run_qmacro_demo(observations, config)
    payload = _summary_payload(result, data_source)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
