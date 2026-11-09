"""Run the real RECESSIONNET demonstration end to end: fetch the real
Kenneth French monthly factor series live, build a point-in-time-safe
dataset against the real NBER recession chronology
(`recessionnet.labels`), split it chronologically, and benchmark the
hybrid quantum classifier against logistic regression, a parameter-
matched classical MLP and a base-rate baseline
(`recessionnet.evaluation.run_recessionnet_benchmark`).

This is a minimum-demonstration script in the sense section 10 of the
PROMETHEUS-X final-project addendum describes ("load one historical
as-of date ... generate ... recession probabilities with uncertainty
... export a reproducibility manifest"), scoped to RECESSIONNET alone
(FP-06/FP-20) plus the quantum challenger the user-supplied quantum
blueprint asked for -- not the other nine addendum subsystems.

A real invocation makes one live network call (fetching the French
factor ZIP). `main`'s `transport` parameter is injectable, mirroring
every `data_ingestion` connector's own `HttpTransport` pattern, so
`tests/unit/test_recessionnet_run.py` can exercise the full CLI --
argument parsing, config validation, `--output` file writing -- with a
small scripted transport and stay hermetic (no real network call
during `pytest`), while a real invocation with no `transport` argument
still performs the real fetch.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

from prometheus.data_ingestion.french_factors import fetch_french_factors
from prometheus.data_ingestion.transport import HttpTransport, UrllibTransport
from prometheus.econosim.pit import MacroObservation
from prometheus.recessionnet.dataset import build_recession_dataset, chronological_split
from prometheus.recessionnet.evaluation import BenchmarkReport, run_recessionnet_benchmark
from prometheus.recessionnet.labels import NBER_RECESSIONS

DEFAULT_SERIES_IDS: tuple[str, ...] = ("FF3_Mkt-RF", "FF3_SMB", "FF3_HML", "FF3_RF")
Verdict = Literal["quantum_better", "classical_better", "inconclusive"]


@dataclass(frozen=True, slots=True)
class RecessionNetRunConfig:
    seed: int = 0
    n_epochs: int = 300
    window: int = 6
    horizon: int = 6
    split_date: date = date(2000, 1, 1)
    bootstrap_resamples: int = 2_000
    series_ids: tuple[str, ...] = DEFAULT_SERIES_IDS

    def __post_init__(self) -> None:
        if self.seed < 0:
            raise ValueError("seed must be non-negative")
        if self.n_epochs < 1:
            raise ValueError("n_epochs must be a positive integer")
        if self.window < 1:
            raise ValueError("window must be a positive integer")
        if self.horizon < 1:
            raise ValueError("horizon must be a positive integer")
        if self.bootstrap_resamples < 1:
            raise ValueError("bootstrap_resamples must be a positive integer")
        if not self.series_ids:
            raise ValueError("series_ids must not be empty")


@dataclass(frozen=True, slots=True)
class RecessionNetDemoResult:
    config: RecessionNetRunConfig
    n_train_samples: int
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
    train, test = chronological_split(dataset, config.split_date)
    report = run_recessionnet_benchmark(
        train,
        test,
        seed=config.seed,
        n_epochs=config.n_epochs,
        bootstrap_resamples=config.bootstrap_resamples,
    )
    return RecessionNetDemoResult(
        config=config,
        n_train_samples=len(train.labels),
        n_test_samples=len(test.labels),
        n_train_positive=int(train.labels.sum()),
        n_test_positive=int(test.labels.sum()),
        report=report,
        verdict=_verdict(report),
    )


def _summary_payload(result: RecessionNetDemoResult) -> dict[str, Any]:
    report = result.report
    bootstrap = report.quantum_vs_best_classical
    return {
        "dataset": {
            "n_train": result.n_train_samples,
            "n_train_positive": result.n_train_positive,
            "n_test": result.n_test_samples,
            "n_test_positive": result.n_test_positive,
            "window_months": result.config.window,
            "horizon_months": result.config.horizon,
            "split_date": result.config.split_date.isoformat(),
        },
        "models": {
            name: {
                "brier_score": metrics.brier_score,
                "roc_auc": metrics.roc_auc,
                "calibration_slope": metrics.calibration_slope,
                "calibration_intercept": metrics.calibration_intercept,
                "n_parameters": report.parameter_counts[name],
                "train_seconds": report.train_seconds[name],
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
    parser.add_argument("--n-epochs", type=int, default=300)
    parser.add_argument("--window", type=int, default=6)
    parser.add_argument("--horizon", type=int, default=6)
    parser.add_argument("--split-date", type=str, default="2000-01-01")
    parser.add_argument("--bootstrap-resamples", type=int, default=2_000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        split_date = date.fromisoformat(args.split_date)
        config = RecessionNetRunConfig(
            seed=args.seed,
            n_epochs=args.n_epochs,
            window=args.window,
            horizon=args.horizon,
            split_date=split_date,
            bootstrap_resamples=args.bootstrap_resamples,
        )
    except ValueError as exc:
        parser.error(str(exc))

    real_transport = transport if transport is not None else UrllibTransport()
    observations = load_real_ff3_observations(real_transport)
    result = run_recessionnet_demo(observations, config)
    payload = _summary_payload(result)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
