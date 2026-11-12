"""Run the RECESSIONNET demonstration on real US GDP, unemployment-
claims, Fed funds rate, M2 and NASDAQ data (Kaggle dataset
`mikoajfish99/us-recession-and-financial-indicators`, ODbL-1.0) rather
than the Kenneth French market factors `recessionnet_run` uses --
reusing every other piece of that module (`RecessionNetRunConfig`,
`run_recessionnet_demo`, `summary_payload`) unchanged, since they
already take `observations`/`series_ids` generically.

Unlike `recessionnet_run`/`qmacro_run`, this CLI makes NO live network
call at all: `data_cache/kaggle_us_macro_monthly.csv` is a committed,
already-derived snapshot (see its `.meta.json` sidecar for exact
provenance and the fixed publication-lag assumption applied before
committing it), so a live demo run of this script cannot fail on a
network or Kaggle-API problem -- the data is already in the repo.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, fields
from datetime import date
from pathlib import Path
from typing import Any

from prometheus.data_ingestion.kaggle_macro import (
    KAGGLE_SERIES_IDS,
    load_kaggle_us_macro_observations,
)
from prometheus.evidence.contracts import CONVENTIONS
from prometheus.evidence.export import build_evidence_bundle
from prometheus.evidence.repository_status import current_repository_gate_report
from prometheus.experiments.manifest import (
    RunManifest,
    compute_result_hash,
    new_run_id,
    now_iso,
)
from prometheus.orchestration.recessionnet_run import (
    RecessionNetDemoResult,
    RecessionNetRunConfig,
    run_recessionnet_demo,
    summary_payload,
)

DEFAULT_CSV_PATH = (
    Path(__file__).resolve().parents[3] / "data_cache" / "kaggle_us_macro_monthly.csv"
)


@dataclass(frozen=True, slots=True)
class RecessionNetKaggleRunConfig:
    """A separate config from `RecessionNetRunConfig` on purpose: that
    class's zero-arg default uses the Kenneth-French `series_ids`
    (`DEFAULT_SERIES_IDS`), which would be the wrong default for a job
    kind that always runs against the committed Kaggle snapshot --
    `series_ids` is therefore not an exposed field here at all (there
    is only one real, committed Kaggle series set), fixed internally to
    `KAGGLE_SERIES_IDS` by `run_recessionnet_kaggle_job` below."""

    seed: int = 0
    max_epochs: int = 500
    patience: int = 20
    window: int = 6
    horizon: int = 6
    validation_split_date: date = date(2001, 1, 1)
    test_split_date: date = date(2008, 1, 1)
    bootstrap_resamples: int = 2_000

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
        if self.validation_split_date >= self.test_split_date:
            raise ValueError("validation_split_date must be strictly before test_split_date")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> RecessionNetKaggleRunConfig:
        if set(payload) != {item.name for item in fields(cls)}:
            raise ValueError(
                "recessionnet_kaggle recipe requires exactly the complete configuration fields"
            )
        values = dict(payload)
        try:
            for name in ("validation_split_date", "test_split_date"):
                if isinstance(values[name], str):
                    values[name] = date.fromisoformat(values[name])
            return cls(**values)
        except (TypeError, AttributeError) as exc:
            raise ValueError(f"invalid recessionnet_kaggle recipe: {exc}") from exc


@dataclass(frozen=True, slots=True)
class RecessionNetKaggleJobResult:
    demo_result: RecessionNetDemoResult
    manifest: RunManifest
    evidence_bundle: dict[str, Any]


def run_recessionnet_kaggle_job(config: RecessionNetKaggleRunConfig) -> RecessionNetKaggleJobResult:
    """The job-kind adapter: reuses `RecessionNetRunConfig`/
    `run_recessionnet_demo`/`summary_payload` unchanged, exactly as
    `main()` below already does, against the same real, already-
    committed, fully offline Kaggle snapshot -- wrapped with a
    `RunManifest`/evidence-bundle envelope."""
    full_config = RecessionNetRunConfig(
        seed=config.seed,
        max_epochs=config.max_epochs,
        patience=config.patience,
        window=config.window,
        horizon=config.horizon,
        validation_split_date=config.validation_split_date,
        test_split_date=config.test_split_date,
        bootstrap_resamples=config.bootstrap_resamples,
        series_ids=KAGGLE_SERIES_IDS,
    )
    observations = load_kaggle_us_macro_observations(DEFAULT_CSV_PATH)
    result = run_recessionnet_demo(observations, full_config)
    payload = summary_payload(result, "kaggle_local_snapshot")
    payload["schema_version"] = 1
    payload["accounting_convention"] = CONVENTIONS["recessionnet_kaggle"]
    payload["config"] = asdict(config)
    manifest = RunManifest(
        new_run_id("pmth-recessionnet-kaggle"),
        now_iso(),
        config.seed,
        asdict(config),
        compute_result_hash(payload),
    )
    bundle = build_evidence_bundle(manifest, [], current_repository_gate_report())
    bundle["recessionnet_kaggle"] = payload
    return RecessionNetKaggleJobResult(
        demo_result=result, manifest=manifest, evidence_bundle=bundle
    )


def main(argv: Sequence[str] | None = None, *, csv_path: Path | None = None) -> int:
    """`csv_path` is injectable purely so tests can point at a small
    fixture instead of the full real snapshot; a real invocation never
    passes it."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-epochs", type=int, default=500)
    parser.add_argument("--patience", type=int, default=20)
    parser.add_argument("--window", type=int, default=6)
    parser.add_argument("--horizon", type=int, default=6)
    parser.add_argument("--validation-split-date", type=str, default="2001-01-01")
    parser.add_argument("--test-split-date", type=str, default="2008-01-01")
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
            series_ids=KAGGLE_SERIES_IDS,
        )
    except ValueError as exc:
        parser.error(str(exc))

    observations = load_kaggle_us_macro_observations(csv_path or DEFAULT_CSV_PATH)
    result = run_recessionnet_demo(observations, config)
    payload: dict[str, Any] = summary_payload(result, "kaggle_local_snapshot")
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
