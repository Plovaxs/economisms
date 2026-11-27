"""A dataset registry and a data-quality report for the committed snapshots in `data_cache/`.

The audit's data work packages D-01 (a registry: source, license, units, frequency, vintage,
checksum and transformation lineage) and D-06 (missingness, outliers, revisions, duplicate
timestamps, schema drift) are answered from the files themselves, not from prose that can drift:

- `build_registry` joins each CSV with its `.meta.json`, the integrity manifest's digest, and what
  the file's own dates say (rows, first and last date, frequency). A field the metadata does not
  declare is listed in `registry_gaps` rather than invented, and a CSV with no `.meta.json` at all
  is reported as such.
- `qa_report` runs generic checks on every file: blank and non-numeric cells, duplicate or
  non-increasing dates, missing periods against the inferred frequency, robust-z outliers in the
  first difference, constant columns, and whether the header matches the declared columns.

Both outputs are deterministic (no timestamps) and committed under `docs/data/`; a test regenerates
them and fails on drift, the same way the integrity manifest does. A check that finds something is a
WARNING with its evidence, not a verdict: a missing month may be a real gap in the source (BLS
published no index for 2025-10), and the report says what it saw.

    python -m prometheus.data_ingestion.dataset_registry write     # regenerate docs/data/
    python -m prometheus.data_ingestion.dataset_registry check     # fail if they are stale
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from prometheus.data_ingestion.snapshot_integrity import MANIFEST_FILENAME

ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT / "data_cache"
OUTPUT_DIR = ROOT / "docs" / "data"
REGISTRY_NAME = "dataset_registry.json"
QA_NAME = "data_qa_report.json"
OUTLIER_Z = 12.0
"""Robust z (median / MAD) of a first difference above which a point is reported."""
REQUIRED_FIELDS = ("source", "source_url", "license", "downloaded_at")
FRENCH_FALLBACK = {
    "source": "Kenneth R. French Data Library, Fama/French 3 factors (monthly)",
    "source_url": "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_CSV.zip",
    "license": "Kenneth R. French Data Library (free for academic research use)",
}
"""`ff3_monthly_snapshot.csv` has no metadata file; these are the connector's own declared constants
(`data_ingestion.french_factors`), used only to fill what it declares, and flagged as such."""


def parse_date(text: str) -> date:
    """`YYYYMM` (the month's first day), `YYYY-MM` or `YYYY-MM-DD`."""
    text = text.strip()
    if len(text) == 6 and text.isdigit():
        return date(int(text[:4]), int(text[4:]), 1)
    parts = text.split("-")
    if len(parts) == 2:
        return date(int(parts[0]), int(parts[1]), 1)
    return date.fromisoformat(text)


def infer_frequency(dates: Sequence[date]) -> str:
    if len(dates) < 3:
        return "unknown"
    median = statistics.median((b - a).days for a, b in zip(dates, dates[1:], strict=False))
    if median >= 300:
        return "annual"
    if median >= 25:
        return "monthly"
    if median <= 5:
        return "daily"
    return "other"


def _read(path: Path) -> tuple[list[str], list[list[str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        return header, [row for row in reader]


def _month_index(d: date) -> int:
    return d.year * 12 + d.month - 1


def qa_file(path: Path, declared_columns: Sequence[str] | None = None) -> dict[str, Any]:
    """Generic quality checks for one `date,...` CSV. A check reports `ok`, `warn` (an integrity
    problem to look at) or `review` (listed for a human; real extremes in a financial series are
    expected and are not errors)."""
    header, rows = _read(path)
    checks: dict[str, Any] = {}

    def record(name: str, ok: bool, detail: Any = None, level: str = "warn") -> None:
        checks[name] = {"status": "ok" if ok else level, **({"detail": detail} if detail else {})}

    dates: list[date] = []
    unparsable = []
    for row in rows:
        try:
            dates.append(parse_date(row[0]))
        except (ValueError, IndexError):
            unparsable.append(row[:1])
    record(
        "dates_parse", not unparsable, {"unparsable_rows": len(unparsable)} if unparsable else None
    )
    increasing = all(b > a for a, b in zip(dates, dates[1:], strict=False))
    duplicates = len(dates) - len(set(dates))
    record(
        "dates_strictly_increasing", increasing, None if increasing else {"duplicates": duplicates}
    )
    frequency = infer_frequency(dates)

    if frequency == "monthly" and dates:
        have = {_month_index(d) for d in dates}
        missing = [m for m in range(min(have), max(have) + 1) if m not in have]
        record(
            "no_missing_months",
            not missing,
            {
                "missing_months": [f"{m // 12:04d}-{m % 12 + 1:02d}" for m in missing[:8]],
                "count": len(missing),
            }
            if missing
            else None,
        )
    elif frequency == "daily" and len(dates) > 1:
        gaps = [
            (a, b) for a, b in zip(dates, dates[1:], strict=False) if (b - a) > timedelta(days=7)
        ]
        record(
            "no_gap_over_seven_days",
            not gaps,
            {"count": len(gaps), "longest_days": max((b - a).days for a, b in gaps)}
            if gaps
            else None,
        )

    blanks: dict[str, int] = {}
    non_numeric: dict[str, int] = {}
    outliers: dict[str, Any] = {}
    constant: list[str] = []
    for index, name in enumerate(header[1:], start=1):
        values: list[float] = []
        for row in rows:
            cell = row[index].strip() if index < len(row) else ""
            if cell == "":
                blanks[name] = blanks.get(name, 0) + 1
                continue
            try:
                number = float(cell)
            except ValueError:
                non_numeric[name] = non_numeric.get(name, 0) + 1
                continue
            if not math.isfinite(number):
                non_numeric[name] = non_numeric.get(name, 0) + 1
                continue
            values.append(number)
        if len(values) > 1 and len(set(values)) == 1:
            constant.append(name)
        if len(values) > 30:
            wide = min(values) > 0 and max(values) / min(values) > 20
            series = [math.log(v) for v in values] if wide else values  # a price: use returns
            diffs = [b - a for a, b in zip(series, series[1:], strict=False)]
            center = statistics.median(diffs)
            mad = statistics.median(abs(d - center) for d in diffs)
            if mad > 0:
                scores = [abs(d - center) / (1.4826 * mad) for d in diffs]
                worst = max(scores)
                count = sum(s > OUTLIER_Z for s in scores)
                if count:
                    outliers[name] = {
                        "points_over_threshold": count,
                        "largest_robust_z": round(worst, 1),
                    }
    record("no_blank_cells", not blanks, {"blank_cells_by_column": blanks} if blanks else None)
    record(
        "all_cells_numeric", not non_numeric, {"by_column": non_numeric} if non_numeric else None
    )
    record(
        "no_outlier_in_first_difference",
        not outliers,
        {
            "threshold_robust_z": OUTLIER_Z,
            "by_column": outliers,
            "note": "first difference, or log difference for a series spanning more than 20x",
        }
        if outliers
        else None,
        level="review",
    )
    record("no_constant_column", not constant, {"columns": constant} if constant else None)
    if declared_columns is not None:
        extra = sorted(set(header[1:]) - set(declared_columns))
        absent = sorted(set(declared_columns) - set(header[1:]))
        record(
            "header_matches_declared_columns",
            not extra and not absent,
            {"in_file_not_declared": extra, "declared_not_in_file": absent}
            if extra or absent
            else None,
        )
    return {
        "rows": len(rows),
        "frequency": frequency,
        "first_date": dates[0].isoformat() if dates else None,
        "last_date": dates[-1].isoformat() if dates else None,
        "checks": checks,
        "warnings": sorted(name for name, c in checks.items() if c["status"] == "warn"),
        "to_review": sorted(name for name, c in checks.items() if c["status"] == "review"),
    }


def _declared_columns(meta: dict[str, Any] | None) -> list[str] | None:
    columns = (meta or {}).get("columns")
    return sorted(columns) if isinstance(columns, dict) else None


def _vintage(meta: dict[str, Any] | None) -> str:
    if meta is None:
        return "not recorded"
    stamp = meta.get("downloaded_at") or meta.get("fetched_at")
    base = f"as published on {stamp}" if stamp else "download date not recorded"
    return f"{base}; revised series (a later download can differ), not a real-time vintage"


def build_registry(data_dir: Path = DATA_DIR) -> dict[str, Any]:
    manifest = json.loads((data_dir / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    files = manifest.get("files", manifest)
    entries: list[dict[str, Any]] = []
    for csv_path in sorted(data_dir.glob("*.csv")):
        meta_path = csv_path.with_suffix(".meta.json")
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else None
        header, rows = _read(csv_path)
        dates = []
        for row in rows:
            try:
                dates.append(parse_date(row[0]))
            except (ValueError, IndexError):
                pass
        declared = {k: (meta or {}).get(k) for k in REQUIRED_FIELDS}
        declared["downloaded_at"] = declared["downloaded_at"] or (meta or {}).get("fetched_at")
        gaps = [k for k, v in declared.items() if not v]
        if meta is None:
            gaps = ["no .meta.json: source, download date and raw-file digests are not recorded"]
        source = declared["source"] or (
            FRENCH_FALLBACK["source"] if csv_path.name.startswith("ff3") else None
        )
        digest = files.get(csv_path.name)
        entries.append(
            {
                "file": csv_path.name,
                "sha256": digest["sha256"] if isinstance(digest, dict) else digest,
                "size_bytes": digest.get("bytes")
                if isinstance(digest, dict)
                else csv_path.stat().st_size,
                "rows": len(rows),
                "columns": header,
                "first_date": dates[0].isoformat() if dates else None,
                "last_date": dates[-1].isoformat() if dates else None,
                "frequency": infer_frequency(dates),
                "source": source,
                "source_url": declared["source_url"]
                or (FRENCH_FALLBACK["source_url"] if csv_path.name.startswith("ff3") else None),
                "license": declared["license"]
                or (FRENCH_FALLBACK["license"] if csv_path.name.startswith("ff3") else None),
                "downloaded_at": declared["downloaded_at"],
                "vintage": _vintage(meta),
                "units_and_columns": (meta or {}).get("columns"),
                "lineage": {
                    "derived_by": (meta or {}).get("derived_by") or (meta or {}).get("prep_script"),
                    "raw_files_sha256": (meta or {}).get("raw_files_sha256"),
                },
                "publication_lag_days": (meta or {}).get("publication_lag_assumption_days"),
                "caveat": (meta or {}).get("caveat"),
                "meta_file": meta_path.name if meta is not None else None,
                "registry_gaps": gaps,
            }
        )
    return {
        "format": "econosim-dataset-registry/1",
        "generated_from": "data_cache/*.csv, data_cache/*.meta.json and MANIFEST.sha256.json",
        "datasets": entries,
    }


def build_qa(data_dir: Path = DATA_DIR) -> dict[str, Any]:
    report: dict[str, Any] = {}
    for csv_path in sorted(data_dir.glob("*.csv")):
        meta_path = csv_path.with_suffix(".meta.json")
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else None
        report[csv_path.name] = qa_file(csv_path, _declared_columns(meta))
    return {
        "format": "econosim-data-qa/1",
        "outlier_robust_z_threshold": OUTLIER_Z,
        "files": report,
        "files_with_warnings": sorted(k for k, v in report.items() if v["warnings"]),
        "files_to_review": sorted(k for k, v in report.items() if v["to_review"]),
    }


def _dump(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("command", choices=("write", "check"))
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args(argv)
    outputs = {
        REGISTRY_NAME: _dump(build_registry(args.data_dir)),
        QA_NAME: _dump(build_qa(args.data_dir)),
    }
    if args.command == "write":
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for name, text in outputs.items():
            (args.output_dir / name).write_text(text, encoding="utf-8")
            print("wrote", args.output_dir / name)
        return 0
    stale = [
        name
        for name, text in outputs.items()
        if not (args.output_dir / name).exists() or (args.output_dir / name).read_text() != text
    ]
    if stale:
        print("stale (run `write`):", *stale, file=sys.stderr)
        return 1
    print("the registry and the QA report match the data")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
