"""Kenneth French factor ingestion with version tracking (DAT-05:
"build Kenneth French factor ingestion with version tracking";
acceptance criterion: "factors and methodological release notes
versioned").

A real round trip (real HTTP fetch of the ZIP archive -> unzip ->
parse -> `MacroObservation` construction) was run against the live
Kenneth French Data Library before any production code here was
written, confirming the file's exact structure: three free-text header
lines (the second of which names the CRSP database VINTAGE this
specific file release was built from, e.g. "This file was created
using the 202609 CRSP database" -- the version-tracking signal this
item asks for), a blank line, a monthly `Mkt-RF,SMB,HML,RF` table keyed
by `YYYYMM`, a blank line, an " Annual Factors: January-December "
marker, and an annual table of the same four factors keyed by `YYYY`.
Rows are distinguished by the LENGTH of their leading date key (6
digits for monthly, 4 for annual) rather than a hardcoded line number,
so a future file with more months does not silently misparse.

Like `worldbank.py`'s own documented choice, this file gives no
per-row publication vintage -- only the single "created using the
{YYYYMM} CRSP database" signal for the WHOLE release -- so every
observation in a given fetch shares that same `published_at` (the last
calendar day of the stated vintage month), the same safe-direction
approximation `worldbank.py` already uses for its own single
dataset-level `lastupdated` field.
"""

from __future__ import annotations

import calendar
import hashlib
import io
import re
import zipfile
from dataclasses import dataclass
from datetime import date
from typing import Literal

from prometheus.data_ingestion.transport import HttpTransport
from prometheus.econosim.pit import MacroObservation

FRENCH_FACTORS_URL = (
    "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
    "F-F_Research_Data_Factors_CSV.zip"
)
FRENCH_SOURCE_LICENSE = "Kenneth R. French Data Library (free for academic research use)"
_FACTOR_NAMES: tuple[str, ...] = ("Mkt-RF", "SMB", "HML", "RF")
_VINTAGE_PATTERN = re.compile(r"(\d{6})\s+CRSP database")

Frequency = Literal["monthly", "annual"]


class FrenchFactorsResponseError(ValueError):
    """Raised when the fetched archive does not match the confirmed-live
    structure this parser expects."""


@dataclass(frozen=True, slots=True)
class FrenchFactorsFetchResult:
    observations: tuple[MacroObservation, ...]
    raw_hash: str
    database_vintage: str
    """The CRSP database version (YYYYMM) this specific file release
    states it was built from -- DAT-05's own "version tracking"."""
    methodological_notes: str
    """The file's free-text header lines, verbatim."""


def _parse_header(lines: list[str]) -> tuple[str, str]:
    header_lines = []
    for line in lines:
        if line.strip() == "":
            break
        header_lines.append(line)
    header_text = "\n".join(header_lines)
    match = _VINTAGE_PATTERN.search(header_text)
    if match is None:
        raise FrenchFactorsResponseError(
            "could not find a 'YYYYMM CRSP database' vintage statement in the file header"
        )
    return match.group(1), header_text


def _parse_data_rows(
    lines: list[str],
) -> tuple[list[tuple[str, list[float]]], list[tuple[str, list[float]]]]:
    monthly: list[tuple[str, list[float]]] = []
    annual: list[tuple[str, list[float]]] = []
    in_annual_section = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if "Annual Factors" in stripped:
            in_annual_section = True
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != len(_FACTOR_NAMES) + 1:
            continue
        key = parts[0]
        if not key.isdigit():
            continue  # a column-header row, e.g. ",Mkt-RF,SMB,HML,RF"
        try:
            values = [float(p) for p in parts[1:]]
        except ValueError:
            continue
        (annual if in_annual_section else monthly).append((key, values))
    return monthly, annual


def _period_end_date(key: str) -> date:
    if len(key) == 6:
        year, month = int(key[:4]), int(key[4:6])
        return date(year, month, calendar.monthrange(year, month)[1])
    if len(key) == 4:
        return date(int(key), 12, 31)
    raise FrenchFactorsResponseError(f"unrecognized date key {key!r} (expected YYYYMM or YYYY)")


def fetch_french_factors(
    transport: HttpTransport, *, frequency: Frequency = "monthly"
) -> FrenchFactorsFetchResult:
    response = transport.get(FRENCH_FACTORS_URL, {})
    if response.status_code != 200:
        raise FrenchFactorsResponseError(
            f"HTTP {response.status_code} fetching Kenneth French factors"
        )
    raw_hash = hashlib.sha256(response.body).hexdigest()
    try:
        archive = zipfile.ZipFile(io.BytesIO(response.body))
        inner_name = archive.namelist()[0]
        content = archive.read(inner_name).decode("utf-8")
    except (zipfile.BadZipFile, IndexError, UnicodeDecodeError) as exc:
        raise FrenchFactorsResponseError(f"response is not a valid zip archive: {exc}") from exc

    lines = content.splitlines()
    vintage, header_text = _parse_header(lines)
    published_at = _period_end_date(vintage)
    monthly_rows, annual_rows = _parse_data_rows(lines)
    rows = monthly_rows if frequency == "monthly" else annual_rows
    if not rows:
        raise FrenchFactorsResponseError(f"no {frequency} data rows were found in the file")

    observations = tuple(
        MacroObservation(
            series_id=f"FF3_{factor_name}",
            observation_at=_period_end_date(key),
            published_at=published_at,
            value=value,
            source_url=FRENCH_FACTORS_URL,
            source_license=FRENCH_SOURCE_LICENSE,
            raw_hash=raw_hash,
            frequency="M" if frequency == "monthly" else "A",
        )
        for key, values in rows
        for factor_name, value in zip(_FACTOR_NAMES, values, strict=True)
    )
    return FrenchFactorsFetchResult(
        observations=observations,
        raw_hash=raw_hash,
        database_vintage=vintage,
        methodological_notes=header_text,
    )
