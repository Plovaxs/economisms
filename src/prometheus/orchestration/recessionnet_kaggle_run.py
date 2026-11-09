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
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

from prometheus.data_ingestion.kaggle_macro import (
    KAGGLE_SERIES_IDS,
    load_kaggle_us_macro_observations,
)
from prometheus.orchestration.recessionnet_run import (
    RecessionNetRunConfig,
    run_recessionnet_demo,
    summary_payload,
)

DEFAULT_CSV_PATH = (
    Path(__file__).resolve().parents[3] / "data_cache" / "kaggle_us_macro_monthly.csv"
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
