"""US bank balance sheets, earnings, loan losses and failures, from the FDIC's own public API.

Finding 28 estimated the WORLDSIM bank block against one series (bank credit of the Fed's weekly
H.8 release, which counts securities as well as loans) and left everything else chosen. This module
adds what a bank model is actually judged by: the balance sheet (loans, securities, cash, deposits,
equity), earnings, net loan charge-offs, and the failures, as annual national totals of all
FDIC-insured institutions.

Source: the FDIC BankFind Suite API (`https://api.fdic.gov/banks/`), no key, US Government work in
the public domain. Two endpoints:

- `summary`: annual aggregates by state, commercial banks (`CB`) and savings institutions (`SI`)
  apart. The national total is the row named "All States and Territories" of each of the two;
  this module adds the two. All amounts are USD thousands as the FDIC publishes them. A field
  the FDIC reports as zero for a whole year (equity capital before 1984, for example) is stored
  blank, not as a zero, so a loader cannot mistake "not reported" for "no equity".
- `failures`: one row per failed or assisted institution since 1934, with total assets and deposits
  at the time. Failures (`RESTYPE` = FAILURE) and assistance transactions are counted separately.

As with the other snapshots in `data_cache/`, the result is committed and every loader reads it
through the integrity manifest; nothing here makes a network call at test or demo time. A
deliberate refresh is `python -m prometheus.data_ingestion.fdic_banks refresh` followed by
`python -m prometheus.data_ingestion.snapshot_integrity write`.

What the numbers are not: the summary counts every insured institution, so the 1980s include the
savings-and-loan industry that the Fed's commercial-bank series does not; the definitions of some
fields (loan categories, the allowance) changed over the decades, so statistics are used from 1984,
the first year equity is reported; and the totals are of the whole banking system, not of the ten
"banks" of the simulator, which are a stylised sample of large banks.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from prometheus.data_ingestion.snapshot_integrity import verified_dict_reader
from prometheus.data_ingestion.transport import HttpTransport, UrllibTransport

FDIC_SUMMARY_URL = "https://api.fdic.gov/banks/summary"
FDIC_FAILURES_URL = "https://api.fdic.gov/banks/failures"
FDIC_LICENSE = "US Government work, public domain (FDIC BankFind Suite API)"
NATIONAL_NAME = "All States and Territories"
DATA_DIR = Path(__file__).resolve().parents[3] / "data_cache"
ANNUAL_FILE = "fdic_bank_annual.csv"
FAILURES_FILE = "fdic_bank_failures_annual.csv"

# snapshot column -> FDIC field. USD thousands, except `banks` (a count).
ANNUAL_FIELDS: dict[str, str] = {
    "banks": "BANKS",
    "assets": "ASSET",
    "loans": "LNLS",
    "securities": "SC",
    "cash_and_balances": "CHBAL",
    "deposits": "DEP",
    "equity": "EQ",
    "net_charge_offs": "NTLNLS",
    "net_income": "NETINC",
    "interest_income": "INTINC",
    "interest_expense": "EINTEXP",
    "net_interest_income": "NIM",
    "noncurrent_loans": "NCLNLS",
}
ANNUAL_COLUMNS: tuple[str, ...] = ("date", *ANNUAL_FIELDS)
FAILURES_COLUMNS: tuple[str, ...] = (
    "date",
    "failures",
    "failed_assets",
    "failed_deposits",
    "assistance_transactions",
    "assisted_assets",
)
FIRST_YEAR = 1934


class FdicError(ValueError):
    """The API returned something other than the documented shape."""


def _records(body: bytes, expected_total: int | None = None) -> list[dict[str, Any]]:
    try:
        document = json.loads(body)
        rows = [item["data"] for item in document["data"]]
        total = int(document["meta"]["total"])
    except (ValueError, KeyError, TypeError) as exc:
        raise FdicError(f"unexpected FDIC response: {exc}") from exc
    if len(rows) != total:
        raise FdicError(f"the FDIC reports {total} rows but returned {len(rows)}")
    if expected_total is not None and total != expected_total:
        raise FdicError(f"expected {expected_total} rows, got {total}")
    return rows


def fetch_national_summary(transport: HttpTransport) -> list[dict[str, Any]]:
    """The national rows (commercial banks and savings institutions) of the `summary` endpoint."""
    fields = ",".join(("YEAR", "CB_SI", "STNAME", *ANNUAL_FIELDS.values()))
    response = transport.get(
        FDIC_SUMMARY_URL,
        {
            "filters": f'STNAME:"{NATIONAL_NAME}"',
            "fields": fields,
            "limit": "10000",
            "sort_by": "YEAR",
            "sort_order": "ASC",
        },
    )
    if response.status_code != 200:
        raise FdicError(f"summary request returned HTTP {response.status_code}")
    return _records(response.body)


def fetch_failures(transport: HttpTransport) -> list[dict[str, Any]]:
    response = transport.get(
        FDIC_FAILURES_URL,
        {"fields": "FAILYR,FAILDATE,QBFASSET,QBFDEP,RESTYPE,NAME", "limit": "10000"},
    )
    if response.status_code != 200:
        raise FdicError(f"failures request returned HTTP {response.status_code}")
    return _records(response.body)


def national_annual(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """One row per year: the national commercial-bank and savings-institution totals added.

    A field whose total is zero for the year is `None` (not reported), see the module docstring."""
    by_year: dict[int, dict[str, Mapping[str, Any]]] = defaultdict(dict)
    for row in rows:
        if row.get("STNAME") != NATIONAL_NAME:
            continue
        by_year[int(row["YEAR"])][str(row["CB_SI"])] = row
    if not by_year:
        raise FdicError("no national rows in the summary")
    out: list[dict[str, Any]] = []
    for year in sorted(by_year):
        parts = by_year[year]
        if "CB" not in parts:
            raise FdicError(f"{year}: no commercial-bank national row")
        record: dict[str, Any] = {"date": date(year, 12, 31).isoformat()}
        for column, field in ANNUAL_FIELDS.items():
            total = sum(float(part.get(field) or 0.0) for part in parts.values())
            record[column] = int(round(total)) if total != 0.0 else None
        out.append(record)
    return out


def failures_annual(rows: Sequence[Mapping[str, Any]], last_year: int) -> list[dict[str, Any]]:
    """Failures and assistance transactions per calendar year, from the first through
    `last_year` (the last complete year: the current year's failures are still being added)."""
    stats: dict[int, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0, 0.0])
    for row in rows:
        year = int(row["FAILYR"])
        if year > last_year:
            continue
        entry = stats[year]
        assets = float(row.get("QBFASSET") or 0.0)
        if row.get("RESTYPE") == "FAILURE":
            entry[0] += 1.0
            entry[1] += assets
            entry[2] += float(row.get("QBFDEP") or 0.0)
        elif row.get("RESTYPE") == "ASSISTANCE":
            entry[3] += 1.0
            entry[4] += assets
        else:
            raise FdicError(f"unknown resolution type {row.get('RESTYPE')!r}")
    if not stats:
        raise FdicError("no failure rows")
    out: list[dict[str, Any]] = []
    for year in range(FIRST_YEAR, last_year + 1):
        e = stats.get(year, [0.0] * 5)
        out.append(
            {
                "date": date(year, 12, 31).isoformat(),
                "failures": int(e[0]),
                "failed_assets": int(round(e[1])),
                "failed_deposits": int(round(e[2])),
                "assistance_transactions": int(e[3]),
                "assisted_assets": int(round(e[4])),
            }
        )
    return out


def to_csv(rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow(["" if row[c] is None else row[c] for c in columns])
    return buffer.getvalue()


def load_bank_annual(path: Path | None = None) -> dict[int, dict[str, float | None]]:
    """Year -> column -> value (USD thousands; `banks` a count; `None` where not reported)."""
    path = path or DATA_DIR / ANNUAL_FILE
    out: dict[int, dict[str, float | None]] = {}
    for row in verified_dict_reader(path, required=ANNUAL_COLUMNS):
        year = int(row["date"][:4])
        out[year] = {c: (float(row[c]) if row[c].strip() else None) for c in ANNUAL_FIELDS}
    if not out:
        raise FdicError(f"{path.name} has no rows")
    return out


def load_failures_annual(path: Path | None = None) -> dict[int, dict[str, float]]:
    path = path or DATA_DIR / FAILURES_FILE
    out: dict[int, dict[str, float]] = {}
    for row in verified_dict_reader(path, required=FAILURES_COLUMNS):
        year = int(row["date"][:4])
        out[year] = {c: float(row[c]) for c in FAILURES_COLUMNS if c != "date"}
    if not out:
        raise FdicError(f"{path.name} has no rows")
    return out


def _annual_meta(rows: Sequence[Mapping[str, Any]], downloaded_at: str) -> dict[str, Any]:
    first_equity = next(r["date"][:4] for r in rows if r["equity"] is not None)
    return {
        "source": "FDIC BankFind Suite, financial summary: national annual totals",
        "source_url": FDIC_SUMMARY_URL,
        "license": FDIC_LICENSE,
        "downloaded_at": downloaded_at,
        "derived_by": (
            "prometheus.data_ingestion.fdic_banks "
            "(national rows, commercial banks and savings institutions added)"
        ),
        "columns": {
            "banks": "number of FDIC-insured institutions at year end",
            "assets": "total assets, USD thousands",
            "loans": "total loans and leases, USD thousands (gross of the allowance)",
            "securities": "securities, USD thousands",
            "cash_and_balances": "cash and balances due from banks, USD thousands",
            "deposits": "total deposits, USD thousands",
            "equity": f"total equity capital, USD thousands; reported from {first_equity}",
            "net_charge_offs": "net loan and lease charge-offs during the year, USD thousands",
            "net_income": "net income during the year, USD thousands",
            "interest_income": "total interest income during the year, USD thousands",
            "interest_expense": "total interest expense during the year, USD thousands",
            "net_interest_income": "net interest income during the year, USD thousands",
            "noncurrent_loans": "noncurrent loans and leases at year end, USD thousands",
        },
        "frequency": "annual; the date is the year end",
        "caveat": (
            "includes savings institutions; field definitions changed over the decades, so "
            "statistics are used from the first year equity is reported"
        ),
        "publication_lag_assumption_days": {"all": 90},
    }


def _failures_meta(downloaded_at: str) -> dict[str, Any]:
    return {
        "source": "FDIC BankFind Suite, failures and assistance transactions since 1934",
        "source_url": FDIC_FAILURES_URL,
        "license": FDIC_LICENSE,
        "downloaded_at": downloaded_at,
        "derived_by": (
            "prometheus.data_ingestion.fdic_banks (counted per calendar year of the failure date)"
        ),
        "columns": {
            "failures": "institutions that failed in the year (resolution type FAILURE)",
            "failed_assets": "their total assets at failure, USD thousands",
            "failed_deposits": "their deposits at failure, USD thousands",
            "assistance_transactions": "open-bank assistance transactions (type ASSISTANCE)",
            "assisted_assets": "total assets of the assisted institutions, USD thousands",
        },
        "frequency": "annual; the date is the year end",
        "caveat": (
            "the 2008-2009 assistance rows include very large institutions (their assets are not "
            "losses); a failure's assets are not the loss to the insurance fund"
        ),
        "publication_lag_assumption_days": {"all": 0},
    }


def refresh(out_dir: Path, transport: HttpTransport, downloaded_at: str) -> list[Path]:
    """Fetch both endpoints and write the two snapshots with their metadata."""
    annual = national_annual(fetch_national_summary(transport))
    failures = failures_annual(fetch_failures(transport), int(annual[-1]["date"][:4]))
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, rows, columns, meta in (
        (ANNUAL_FILE, annual, ANNUAL_COLUMNS, _annual_meta(annual, downloaded_at)),
        (FAILURES_FILE, failures, FAILURES_COLUMNS, _failures_meta(downloaded_at)),
    ):
        path = out_dir / name
        path.write_text(to_csv(rows, columns), encoding="utf-8")
        path.with_suffix(".meta.json").write_text(
            json.dumps(meta, indent=2) + "\n", encoding="utf-8"
        )
        written.extend([path, path.with_suffix(".meta.json")])
    return written


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=("refresh",))
    parser.add_argument("--out-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--downloaded-at", default=date.today().isoformat())
    args = parser.parse_args(argv)
    for path in refresh(args.out_dir, UrllibTransport(timeout=120.0), args.downloaded_at):
        print("wrote", path)
    print("now run: python -m prometheus.data_ingestion.snapshot_integrity write", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
