"""Run the RECESSIONNET demonstration with the real US Treasury
10Y/3M yield-curve spread (`data_ingestion.treasury_yield_spread`)
added to the Kaggle macro feature set (`data_ingestion.kaggle_macro`)
-- closing a real, disclosed gap: neither the Kenneth French factors
nor the Kaggle macro snapshot on their own include any direct measure
of the yield curve, despite a curve inversion being one of the
most-studied real recession predictors in the macro-finance literature
(Estrella-Mishkin; the NY Fed's own published recession-probability
model uses this exact 10Y-3M spread). Reuses every RECESSIONNET
primitive unchanged (`RecessionNetRunConfig`, `run_recessionnet_demo`,
`summary_payload`) -- zero new training/benchmark code, the same
composition the Kaggle-only variant (`recessionnet_kaggle_run`)
already established.

Real data constraint, disclosed rather than worked around:
`home.treasury.gov`'s own CSV endpoint returns nothing before 1990
(confirmed by direct request), roughly nine years later than the
Kaggle snapshot's own 1981-12 start.
`recessionnet.dataset.build_monthly_series_matrix` requires every
series to have a value for every month in range, with no per-feature
masking (unlike `inflationcast.data`'s (value, mask) pairs) -- so this
module uses only the real OVERLAPPING range (1990-01 onward) between
the two sources, rather than inventing a masking layer
`build_monthly_series_matrix` was never built to need. This is a
disclosed, honest scope cut, not a silent one: `main()`'s own default
`validation_split_date`/`test_split_date` (2001/2008) sit comfortably
inside the 1990-2023 overlap either way.

Unlike `recessionnet_run`/`qmacro_run`, this CLI makes NO live network
call at all: both CSVs are already-committed, already-derived
snapshots (see their `.meta.json` sidecars for exact provenance), so a
demo run of this script cannot fail on a network problem. See
`data_ingestion.treasury_yield_spread`'s own module docstring for why
this is a separate, narrower module from the pre-existing
`data_ingestion.treasury_yield_curve` (DAT-04) connector, not a
duplicate of it.
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
from prometheus.data_ingestion.treasury_yield_spread import (
    load_treasury_yield_spread_observations,
)
from prometheus.econosim.pit import MacroObservation
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

DEFAULT_KAGGLE_CSV_PATH = (
    Path(__file__).resolve().parents[3] / "data_cache" / "kaggle_us_macro_monthly.csv"
)
DEFAULT_TREASURY_CSV_PATH = (
    Path(__file__).resolve().parents[3] / "data_cache" / "treasury_yield_spread_monthly.csv"
)
YIELD_CURVE_SPREAD_SERIES_ID = "TREASURY_10Y_3M_SPREAD"
SERIES_IDS: tuple[str, ...] = (*KAGGLE_SERIES_IDS, YIELD_CURVE_SPREAD_SERIES_ID)
EARLIEST_REAL_MONTH = date(1990, 1, 31)
"""`home.treasury.gov`'s own CSV endpoint has no data before 1990 --
see `data_ingestion.treasury_yield_spread`'s own module docstring.
Kaggle observations before this month are dropped so every requested
series has a value for every remaining month, the precondition
`build_monthly_series_matrix` enforces."""
LATEST_REAL_MONTH = date(2023, 1, 31)
"""`data_cache/kaggle_us_macro_monthly.csv`'s own real range ends
2023-01 -- the committed Treasury snapshot runs through 2023-12, so
treasury-only months after this are dropped for the same reason
`EARLIEST_REAL_MONTH` drops kaggle-only months before 1990."""


@dataclass(frozen=True, slots=True)
class RecessionNetYieldCurveRunConfig:
    """A separate config from `RecessionNetKaggleRunConfig` on purpose,
    the same reasoning that class itself documents relative to
    `RecessionNetRunConfig`: `series_ids` is not an exposed field here
    either (there is only one real, committed combined series set),
    fixed internally to `SERIES_IDS` by `run_recessionnet_yield_curve_
    job` below."""

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
    def from_dict(cls, payload: Mapping[str, Any]) -> RecessionNetYieldCurveRunConfig:
        if set(payload) != {item.name for item in fields(cls)}:
            raise ValueError(
                "recessionnet_yield_curve recipe requires exactly the complete configuration "
                "fields"
            )
        values = dict(payload)
        try:
            for name in ("validation_split_date", "test_split_date"):
                if isinstance(values[name], str):
                    values[name] = date.fromisoformat(values[name])
            return cls(**values)
        except (TypeError, AttributeError) as exc:
            raise ValueError(f"invalid recessionnet_yield_curve recipe: {exc}") from exc


@dataclass(frozen=True, slots=True)
class RecessionNetYieldCurveJobResult:
    demo_result: RecessionNetDemoResult
    manifest: RunManifest
    evidence_bundle: dict[str, Any]


def _combined_observations(kaggle_csv: Path, treasury_csv: Path) -> list[MacroObservation]:
    kaggle = load_kaggle_us_macro_observations(kaggle_csv)
    treasury = load_treasury_yield_spread_observations(treasury_csv)
    kaggle_overlap = [o for o in kaggle if o.observation_at >= EARLIEST_REAL_MONTH]
    treasury_overlap = [o for o in treasury if o.observation_at <= LATEST_REAL_MONTH]
    return [*kaggle_overlap, *treasury_overlap]


def run_recessionnet_yield_curve_job(
    config: RecessionNetYieldCurveRunConfig,
) -> RecessionNetYieldCurveJobResult:
    """The job-kind adapter: reuses `RecessionNetRunConfig`/
    `run_recessionnet_demo`/`summary_payload` unchanged against the
    same real, already-committed, fully offline Kaggle + Treasury
    snapshots -- wrapped with a `RunManifest`/evidence-bundle
    envelope."""
    full_config = RecessionNetRunConfig(
        seed=config.seed,
        max_epochs=config.max_epochs,
        patience=config.patience,
        window=config.window,
        horizon=config.horizon,
        validation_split_date=config.validation_split_date,
        test_split_date=config.test_split_date,
        bootstrap_resamples=config.bootstrap_resamples,
        series_ids=SERIES_IDS,
    )
    observations = _combined_observations(DEFAULT_KAGGLE_CSV_PATH, DEFAULT_TREASURY_CSV_PATH)
    result = run_recessionnet_demo(observations, full_config)
    payload = summary_payload(result, "kaggle_and_treasury_local_snapshot")
    payload["schema_version"] = 1
    # Not registered in orchestration.recipes.RUNNERS (this module is a
    # standalone research CLI, not a queueable job kind -- see this
    # module's own docstring), so this intentionally does NOT read from
    # evidence.contracts.CONVENTIONS, whose keys must exactly match
    # RUNNERS. Same contract shape as "recessionnet_kaggle" -- literally
    # the same kind of classifier benchmark -- hardcoded directly here.
    payload["accounting_convention"] = "classifier-benchmark-v1"
    payload["config"] = asdict(config)
    manifest = RunManifest(
        new_run_id("pmth-recessionnet-yield-curve"),
        now_iso(),
        config.seed,
        asdict(config),
        compute_result_hash(payload),
    )
    bundle = build_evidence_bundle(manifest, [], current_repository_gate_report())
    bundle["recessionnet_yield_curve"] = payload
    return RecessionNetYieldCurveJobResult(
        demo_result=result, manifest=manifest, evidence_bundle=bundle
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    kaggle_csv_path: Path | None = None,
    treasury_csv_path: Path | None = None,
) -> int:
    """`kaggle_csv_path`/`treasury_csv_path` are injectable purely so
    tests can point at small fixtures instead of the full real
    snapshots; a real invocation never passes them."""
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
            series_ids=SERIES_IDS,
        )
    except ValueError as exc:
        parser.error(str(exc))

    observations = _combined_observations(
        kaggle_csv_path or DEFAULT_KAGGLE_CSV_PATH, treasury_csv_path or DEFAULT_TREASURY_CSV_PATH
    )
    result = run_recessionnet_demo(observations, config)
    payload: dict[str, Any] = summary_payload(result, "kaggle_and_treasury_local_snapshot")
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
