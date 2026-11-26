"""The locked confirmatory data: its digest is the one recorded, and nothing has parsed its values.

The checks read the bytes (to hash them) and the month column (to count rows); they never convert
a level to a number, so the data stay unread in the sense the protocol defines.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "confirmatory_data" / "cpi_sa_bls_2026-11-24.csv"
META = LOCK.with_suffix(".meta.json")


def test_the_locked_file_matches_its_sidecar_and_the_protocol_records_the_same_digest() -> None:
    meta = json.loads(META.read_text(encoding="utf-8"))
    assert hashlib.sha256(LOCK.read_bytes()).hexdigest() == meta["csv_sha256"]
    protocol = (ROOT / "docs" / "CONFIRMATORY_PROTOCOL.md").read_text(encoding="utf-8")
    readme = (ROOT / "confirmatory_data" / "README.md").read_text(encoding="utf-8")
    assert meta["csv_sha256"] in protocol and meta["csv_sha256"] in readme


def test_the_lock_has_the_months_its_sidecar_declares_and_only_the_published_gap_is_blank() -> None:
    meta = json.loads(META.read_text(encoding="utf-8"))
    rows = [line.split(",") for line in LOCK.read_text(encoding="utf-8").splitlines()]
    assert rows[0] == ["month", "level"]
    months = [row[0] for row in rows[1:]]
    assert (months[0], months[-1], len(months)) == (
        meta["first_month"],
        meta["last_month"],
        meta["n_months"],
    )
    assert [row[0] for row in rows[1:] if row[1] == ""] == meta["missing_months"] == ["2025-10"]
    assert "public domain" in meta["license"] and meta["series_id"] == "CUSR0000SA0"


def test_no_source_file_refers_to_the_locked_data_directory() -> None:
    offenders = [
        str(path.relative_to(ROOT))
        for path in (ROOT / "src").rglob("*.py")
        if "confirmatory_data" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


SP500 = ROOT / "confirmatory_data" / "sp500_gspc_kaggle_2026-11-26.csv"
SP500_META = SP500.with_suffix(".meta.json")


def test_the_locked_sp500_file_matches_its_sidecar_and_the_digest_is_recorded_everywhere() -> None:
    meta = json.loads(SP500_META.read_text(encoding="utf-8"))
    assert hashlib.sha256(SP500.read_bytes()).hexdigest() == meta["csv_sha256"]
    protocol = (ROOT / "docs" / "CONFIRMATORY_PROTOCOL.md").read_text(encoding="utf-8")
    readme = (ROOT / "confirmatory_data" / "README.md").read_text(encoding="utf-8")
    assert meta["csv_sha256"] in protocol and meta["csv_sha256"] in readme


def test_the_locked_sp500_file_starts_the_day_after_the_snapshot_and_is_in_order() -> None:
    """Only the date column is read; no closing value is converted to a number."""
    meta = json.loads(SP500_META.read_text(encoding="utf-8"))
    rows = [line.split(",") for line in SP500.read_text(encoding="utf-8").splitlines()]
    assert rows[0] == ["date", "close"]
    dates = [row[0] for row in rows[1:]]
    assert (dates[0], dates[-1], len(dates)) == (
        meta["first_date"],
        meta["last_date"],
        meta["n_rows"],
    )
    assert dates[0] > "2023-05-03"  # the committed series ends 2023-05-03: no overlap
    assert dates == sorted(set(dates))
    assert all(row[1] != "" for row in rows[1:])
