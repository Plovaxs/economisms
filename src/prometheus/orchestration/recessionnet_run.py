"""Run the real RECESSIONNET demonstration end to end: fetch the real
Kenneth French monthly factor series live, build a point-in-time-safe
dataset against the real NBER recession chronology
(`recessionnet.labels`), split it three ways -- train-proper /
validation / test, all strictly chronological -- and benchmark the
hybrid quantum classifier against logistic regression, a parameter-
matched classical MLP and a base-rate baseline, each learned model
selected by validation-set early stopping
(`recessionnet.evaluation.run_recessionnet_benchmark_with_early_stopping`,
PR-142's methodology -- this CLI used the superseded fixed-epoch
`run_recessionnet_benchmark` through PR-142, a gap that PR's own
ledger entry disclosed; PR-144 closes it, matching Q-MACRO's CLI,
which already used early stopping from the start).

This is a minimum-demonstration script in the sense section 10 of the
PROMETHEUS-X final-project addendum describes ("load one historical
as-of date ... generate ... recession probabilities with uncertainty
... export a reproducibility manifest"), scoped to RECESSIONNET alone
(FP-06/FP-20) plus the quantum challenger the user-supplied quantum
blueprint asked for -- not the other nine addendum subsystems.

A real invocation makes one live network call (fetching the French
factor ZIP), with an offline fallback (`load_real_ff3_observations_or_
cached`) to a committed snapshot if that fails -- a live demo should
not die on a bad wifi moment. `main`'s `transport` parameter is
injectable, mirroring every `data_ingestion` connector's own
`HttpTransport` pattern, so `tests/unit/test_recessionnet_run.py` can
exercise the full CLI -- argument parsing, config validation,
`--output` file writing -- with a small scripted transport and stay
hermetic (no real network call during `pytest`), while a real
invocation with no `transport` argument still performs the real fetch.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

from prometheus.data_ingestion.french_factors import (
    FrenchFactorsResponseError,
    fetch_french_factors,
    load_cached_ff3_snapshot,
)
from prometheus.data_ingestion.transport import HttpRequestError, HttpTransport, UrllibTransport
from prometheus.econosim.pit import MacroObservation
from prometheus.recessionnet.dataset import build_recession_dataset, chronological_split
from prometheus.recessionnet.evaluation import (
    BenchmarkReport,
    run_recessionnet_benchmark_with_early_stopping,
)
from prometheus.recessionnet.labels import NBER_RECESSIONS

DEFAULT_SERIES_IDS: tuple[str, ...] = ("FF3_Mkt-RF", "FF3_SMB", "FF3_HML", "FF3_RF")
DEFAULT_CACHE_PATH = Path(__file__).resolve().parents[3] / "data_cache" / "ff3_monthly_snapshot.csv"
Verdict = Literal["quantum_better", "classical_better", "inconclusive"]
DataSource = Literal["live", "cached_snapshot_fallback"]


@dataclass(frozen=True, slots=True)
class RecessionNetRunConfig:
    seed: int = 0
    max_epochs: int = 500
    patience: int = 20
    window: int = 6
    horizon: int = 6
    validation_split_date: date = date(1988, 1, 1)
    test_split_date: date = date(2000, 1, 1)
    bootstrap_resamples: int = 2_000
    series_ids: tuple[str, ...] = DEFAULT_SERIES_IDS

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
        if self.bootstrap_resamples < 1:
            raise ValueError("bootstrap_resamples must be a positive integer")
        if not self.series_ids:
            raise ValueError("series_ids must not be empty")
        if self.validation_split_date >= self.test_split_date:
            raise ValueError("validation_split_date must be strictly before test_split_date")


@dataclass(frozen=True, slots=True)
class RecessionNetDemoResult:
    config: RecessionNetRunConfig
    n_train_samples: int
    n_validation_samples: int
    n_test_samples: int
    n_train_positive: int
    n_test_positive: int
    report: BenchmarkReport
    verdict: Verdict


def load_real_ff3_observations(transport: HttpTransport) -> list[MacroObservation]:
    """A thin wrapper (fetch, unwrap) -- the real parsing logic is
    `data_ingestion.french_factors.fetch_french_factors`'s own,
    already tested there against a real captured archive."""
    return list(fetch_french_factors(transport, frequency="monthly").observations)


def load_real_ff3_observations_or_cached(
    transport: HttpTransport, cache_path: Path = DEFAULT_CACHE_PATH
) -> tuple[list[MacroObservation], DataSource]:
    """What every CLI invocation of this module actually calls: try a
    real live fetch first; if it fails for any network/response
    reason, fall back to the committed offline snapshot
    (`data_cache/ff3_monthly_snapshot.csv`, refreshed deliberately via
    `french_factors.save_ff3_snapshot`) rather than hard-failing --
    a live demo should not die because a venue's wifi or the Dartmouth
    server had a bad moment. The returned `DataSource` tag makes which
    path was actually used visible in the output, not silently
    papered over."""
    try:
        return load_real_ff3_observations(transport), "live"
    except (HttpRequestError, FrenchFactorsResponseError, OSError):
        return load_cached_ff3_snapshot(cache_path), "cached_snapshot_fallback"


def _verdict(report: BenchmarkReport) -> Verdict:
    bootstrap = report.quantum_vs_best_classical
    if not bootstrap.excludes_zero():
        return "inconclusive"
    return "quantum_better" if bootstrap.point_estimate < 0 else "classical_better"


def run_recessionnet_demo(
    observations: Sequence[MacroObservation], config: RecessionNetRunConfig
) -> RecessionNetDemoResult:
    dataset = build_recession_dataset(
        observations,
        config.series_ids,
        NBER_RECESSIONS,
        window=config.window,
        horizon=config.horizon,
    )
    train_full, test = chronological_split(dataset, config.test_split_date)
    train_proper, validation = chronological_split(train_full, config.validation_split_date)
    report = run_recessionnet_benchmark_with_early_stopping(
        train_proper,
        validation,
        test,
        seed=config.seed,
        max_epochs=config.max_epochs,
        patience=config.patience,
        bootstrap_resamples=config.bootstrap_resamples,
    )
    return RecessionNetDemoResult(
        config=config,
        n_train_samples=len(train_proper.labels),
        n_validation_samples=len(validation.labels),
        n_test_samples=len(test.labels),
        n_train_positive=int(train_proper.labels.sum()),
        n_test_positive=int(test.labels.sum()),
        report=report,
        verdict=_verdict(report),
    )


def _summary_payload(result: RecessionNetDemoResult, data_source: DataSource) -> dict[str, Any]:
    report = result.report
    bootstrap = report.quantum_vs_best_classical
    return {
        "data_source": data_source,
        "dataset": {
            "n_train": result.n_train_samples,
            "n_train_positive": result.n_train_positive,
            "n_validation": result.n_validation_samples,
            "n_test": result.n_test_samples,
            "n_test_positive": result.n_test_positive,
            "window_months": result.config.window,
            "horizon_months": result.config.horizon,
            "validation_split_date": result.config.validation_split_date.isoformat(),
            "test_split_date": result.config.test_split_date.isoformat(),
        },
        "models": {
            name: {
                "brier_score": metrics.brier_score,
                "roc_auc": metrics.roc_auc,
                "calibration_slope": metrics.calibration_slope,
                "calibration_intercept": metrics.calibration_intercept,
                "n_parameters": report.parameter_counts[name],
                "train_seconds": report.train_seconds[name],
                "selected_epoch": (report.selected_epochs or {}).get(name),
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
    """`transport` is injectable (defaulting to the real `UrllibTransport`)
    purely so this CLI's argument parsing, config validation and output
    plumbing can be tested with a scripted, non-network transport --
    exactly the same injection pattern every `data_ingestion` connector
    in this repository already uses; a real invocation never passes it."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-epochs", type=int, default=500)
    parser.add_argument("--patience", type=int, default=20)
    parser.add_argument("--window", type=int, default=6)
    parser.add_argument("--horizon", type=int, default=6)
    parser.add_argument("--validation-split-date", type=str, default="1988-01-01")
    parser.add_argument("--test-split-date", type=str, default="2000-01-01")
    parser.add_argument("--bootstrap-resamples", type=int, default=2_000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        config = RecessionNetRunConfig(
            seed=args.seed,
            max_epochs=args.max_epochs,
            patience=args.patience,
            window=args.window,
            horizon=args.horizon,
            validation_split_date=date.fromisoformat(args.validation_split_date),
            test_split_date=date.fromisoformat(args.test_split_date),
            bootstrap_resamples=args.bootstrap_resamples,
        )
    except ValueError as exc:
        parser.error(str(exc))

    real_transport = transport if transport is not None else UrllibTransport()
    observations, data_source = load_real_ff3_observations_or_cached(real_transport)
    result = run_recessionnet_demo(observations, config)
    payload = _summary_payload(result, data_source)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
