"""Reproducible derivation of the committed Kaggle-derived snapshots.

PR-145 committed `data_cache/kaggle_us_macro_monthly.csv` from a one-off prep
script that was described in prose but never committed. This module is the
opposite: every snapshot added after it is rebuilt by a committed, tested
function from the raw Kaggle files (the operator downloads them from the
dataset pages named in each snapshot's `.meta.json`; the raw files themselves
are NOT committed -- their SHA-256 digests are recorded instead):

    python -m prometheus.data_ingestion.kaggle_build \\
        --backbone-zip   <mikoajfish99/us-recession-and-financial-indicators.zip> \\
        --sp500-zip      <henryhan117/sp-500-historical-data.zip> \\
        --treasury-zip   <guillemservera/us-treasury-yields-daily.zip> \\
        --fed-zip        <federalreserve/interest-rates.zip> \\
        --downloaded-at  2026-11-19 --out-dir data_cache

Point-in-time convention (the one PR-145 documented, applied uniformly): a
series' value for a period is first KNOWABLE one fixed publication lag after
the period ends, and is re-keyed to the first month-end at or after that
moment, so the value on row M is honestly known by M's own end. The lags are
fixed, documented assumptions -- not fetched release vintages (ALFRED is not
reachable from this environment). Quarterly GDP is released once per quarter
and HELD until the next release (never forward-filled before it is knowable).
"""

from __future__ import annotations

import argparse
import calendar
import csv
import hashlib
import io
import json
import lzma
import math
import zipfile
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from prometheus.data_ingestion.dataset_sandbox import validate_zip_archive
from prometheus.data_ingestion.kaggle_fed_policy import (
    FED_COLUMNS,
    KAGGLE_FED_POLICY_SOURCE_LICENSE,
    KAGGLE_FED_POLICY_SOURCE_URL,
)
from prometheus.data_ingestion.kaggle_macro import KAGGLE_SOURCE_LICENSE, KAGGLE_SOURCE_URL
from prometheus.data_ingestion.kaggle_macro_extended import EXTENDED_MACRO_COLUMNS
from prometheus.data_ingestion.kaggle_sp500 import (
    KAGGLE_SP500_SOURCE_LICENSE,
    KAGGLE_SP500_SOURCE_URL,
)
from prometheus.data_ingestion.kaggle_term_spread import (
    KAGGLE_TERM_SPREAD_SOURCE_LICENSE,
    KAGGLE_TERM_SPREAD_SOURCE_URL,
    TERM_SPREAD_COLUMN,
)
from prometheus.data_ingestion.snapshot_integrity import (
    MAX_CSV_ROWS,
    SnapshotParseError,
    iter_csv_rows,
)

Series = list[tuple[date, float]]
"""Observations sorted by date, ascending."""

GRID_START = date(1960, 1, 31)
GRID_END = date(2023, 1, 31)
"""The extended macro grid stops where the PR-145 grid stops (2023-01): the
Kaggle backbone dataset itself ends in 2023-05, and a later row would mix
complete and partial months."""

PUBLICATION_LAG_DAYS: dict[str, int] = {
    "GDP_YOY": 30,
    "CLAIMS_YOY": 7,
    "FEDFUNDS": 0,
    "UNRATE": 7,
    "CPI_YOY_SA": 15,
    "BANK_CREDIT_YOY": 9,
    "SPX_YOY": 0,
    "SPX_VOL": 0,
}
BACKBONE_MEMBERS: dict[str, str] = {
    "GDP_YOY": "Gross Domestic Product.csv",
    "CLAIMS_YOY": "Continued Claims (Insured Unemployment).csv",
    "FEDFUNDS": "Federal Funds Effective Rate.csv",
    "UNRATE": "Unemployment Rate.csv",
    "CPI_YOY_SA": "Consumer Price Index for All Urban Consumers All Items in U.S. City Average.csv",
    "BANK_CREDIT_YOY": "Bank Credit All Commercial Banks.csv",
    "SPX": "SPX500.csv",
}
BASELINE_COLUMNS: tuple[str, ...] = ("GDP_YOY", "CLAIMS_YOY", "FEDFUNDS", "M2_YOY", "NASDAQ_YOY")
"""The five columns of PR-145's `data_cache/kaggle_us_macro_monthly.csv`."""
BASELINE_ONLY_MEMBERS: dict[str, str] = {"M2_YOY": "M2.csv", "NASDAQ_YOY": "NASDAQ.csv"}
BASELINE_ONLY_LAG_DAYS: dict[str, int] = {"M2_YOY": 7, "NASDAQ_YOY": 0}
_MIN_RETURNS_PER_MONTH = 15
_MIN_SPREAD_DAYS_PER_MONTH = 10
_TRADING_DAYS_PER_YEAR = 252


# --------------------------------------------------------------------------- calendar


def month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def month_end_of(day: date) -> date:
    """The first month-end on or after `day` (a date's own month-end)."""
    return month_end(day.year, day.month)


def add_months(month_end_date: date, months: int) -> date:
    index = month_end_date.year * 12 + (month_end_date.month - 1) + months
    return month_end(index // 12, index % 12 + 1)


def effective_row(period_end: date, lag_days: int) -> date:
    """The row (month-end) on which a value for a period ending `period_end`
    first appears: the first month-end at or after `period_end + lag_days`."""
    return month_end_of(period_end + timedelta(days=lag_days))


# --------------------------------------------------------------------------- parsers
#
# Everything below reads files that a THIRD PARTY published. The contract, which
# `tests/unit/test_data_parser_fuzz.py` checks with arbitrary input: a parser either
# returns a series that is sorted, has no duplicate date and contains only finite
# numbers (prices also strictly positive), or raises `SnapshotParseError` naming the
# line. It never leaks a bare `KeyError`/`IndexError`/`ZeroDivisionError`/`csv.Error`,
# and it never lets `nan`/`inf` through -- `float("nan")` parses happily and then
# compares false against every threshold, which is how it would otherwise slip past
# a `price <= 0` check and poison a return series silently.


def _number(text: str, source: str, line: int, *, positive: bool = False) -> float:
    try:
        value = float(text)
    except ValueError:
        raise SnapshotParseError(f"{source}: line {line}: {text[:40]!r} is not a number") from None
    if not math.isfinite(value) or (positive and value <= 0.0):
        raise SnapshotParseError(f"{source}: line {line}: {text[:40]!r} is not an acceptable value")
    return value


def _iso_day(text: str, source: str, line: int) -> date:
    try:
        return date.fromisoformat(text.strip())
    except ValueError:
        raise SnapshotParseError(f"{source}: line {line}: {text[:40]!r} is not a date") from None


def _integer(text: str, source: str, line: int) -> int:
    try:
        return int(text)
    except ValueError:
        raise SnapshotParseError(
            f"{source}: line {line}: {text[:40]!r} is not an integer"
        ) from None


def _sorted_unique(out: Series, source: str) -> Series:
    out.sort(key=lambda item: item[0])
    for (earlier, _), (later, _) in zip(out, out[1:], strict=False):
        if earlier == later:
            raise SnapshotParseError(f"{source}: duplicate date {earlier.isoformat()}")
    return out


def parse_fred_csv(text: str, source: str = "FRED csv") -> Series:
    """`DATE,<series>` rows. Tolerates FRED's "." / empty missing markers and the
    decimal-comma values (`5,08`) the csv module splits into three fields."""
    reader = csv.reader(io.StringIO(text))
    out: Series = []
    try:
        next(reader, None)
        for count, row in enumerate(reader, start=1):
            if count > MAX_CSV_ROWS:
                raise SnapshotParseError(f"{source}: more than {MAX_CSV_ROWS} rows")
            if not row:
                continue
            if len(row) == 3:
                value_text = f"{row[1]}.{row[2]}"
            elif len(row) == 2:
                value_text = row[1]
            else:
                raise SnapshotParseError(
                    f"{source}: line {reader.line_num}: unexpected FRED row shape: {str(row)[:80]}"
                )
            value_text = value_text.strip()
            if value_text in ("", "."):
                continue
            out.append(
                (
                    _iso_day(row[0], source, reader.line_num),
                    _number(value_text, source, reader.line_num),
                )
            )
    except csv.Error as exc:
        raise SnapshotParseError(f"{source}: {exc}") from exc
    return _sorted_unique(out, source)


def parse_investing_csv(text: str, source: str = "Investing.com csv") -> Series:
    """Investing.com export: `Date` is MM/DD/YYYY, `Price` has thousands commas,
    rows are newest-first. Prices must be finite and positive."""
    out: Series = []
    for line, row in iter_csv_rows(text, source, ("Date", "Price")):
        pieces = row["Date"].split("/")
        if len(pieces) != 3:
            raise SnapshotParseError(f"{source}: line {line}: {row['Date'][:20]!r} is not M/D/Y")
        price = row["Price"].replace(",", "").strip()
        if not price:
            continue
        month, day, year = (_integer(piece, source, line) for piece in pieces)
        try:
            when = date(year, month, day)
        except ValueError:
            raise SnapshotParseError(
                f"{source}: line {line}: {row['Date'][:20]!r} is not a date"
            ) from None
        out.append((when, _number(price, source, line, positive=True)))
    return _sorted_unique(out, source)


def parse_yahoo_close_csv(text: str, source: str = "Yahoo csv") -> Series:
    """Yahoo Finance export (`Date`, `Close`); closes must be finite and positive."""
    out: Series = []
    for line, row in iter_csv_rows(text, source, ("Date", "Close")):
        out.append(
            (
                _iso_day(row["Date"], source, line),
                _number(row["Close"], source, line, positive=True),
            )
        )
    return _sorted_unique(out, source)


def parse_treasury_daily(text: str, source: str = "Treasury csv") -> tuple[Series, Series]:
    """(US3M, US10Y) daily par yields, only on days where BOTH are published."""
    three_month: Series = []
    ten_year: Series = []
    for line, row in iter_csv_rows(text, source, ("date", "US3M", "US10Y")):
        if row["US3M"].strip() and row["US10Y"].strip():
            day = _iso_day(row["date"], source, line)
            three_month.append((day, _number(row["US3M"], source, line)))
            ten_year.append((day, _number(row["US10Y"], source, line)))
    return _sorted_unique(three_month, source), _sorted_unique(ten_year, source)


# --------------------------------------------------------------------------- derivations


def monthly_levels(
    series: Series, first: date, last: date, *, max_staleness_days: int = 10
) -> dict[date, float]:
    """For each month-end in [first, last]: the last observation dated on or
    before it, provided it is at most `max_staleness_days` old (a long data gap
    must produce a missing month, not a silently carried-forward value)."""
    out: dict[date, float] = {}
    index = 0
    latest: tuple[date, float] | None = None
    row = month_end_of(first)
    while row <= last:
        while index < len(series) and series[index][0] <= row:
            latest = series[index]
            index += 1
        if latest is not None and (row - latest[0]).days <= max_staleness_days:
            out[row] = latest[1]
        row = add_months(row, 1)
    return out


def monthly_period_levels(series: Series) -> dict[date, float]:
    """A monthly series dated on the first of its period month -> keyed by the
    period's month-end."""
    return {month_end_of(day): value for day, value in series}


def yoy_percent(levels: Mapping[date, float]) -> dict[date, float]:
    out: dict[date, float] = {}
    for row, value in levels.items():
        previous = levels.get(add_months(row, -12))
        if previous:
            out[row] = (value / previous - 1.0) * 100.0
    return out


def apply_lag(values: Mapping[date, float], lag_days: int) -> dict[date, float]:
    """Re-key a period-matched monthly series to the first month-end at or after
    (period end + lag). For the lags used here (< 28 days) no two periods collide."""
    out: dict[date, float] = {}
    for period_end in sorted(values):
        out[effective_row(period_end, lag_days)] = values[period_end]
    return out


def hold_forward(values: Mapping[date, float], last: date) -> dict[date, float]:
    """Hold each value until the next one appears (releases that are quarterly)."""
    out: dict[date, float] = {}
    rows = sorted(values)
    if not rows:
        return out
    current = values[rows[0]]
    row = rows[0]
    while row <= last:
        current = values.get(row, current)
        out[row] = current
        row = add_months(row, 1)
    return out


def quarterly_yoy_released(gdp: Series, lag_days: int, last: date) -> dict[date, float]:
    """Quarterly level (dated on the quarter's first month) -> YoY growth against
    the same quarter a year earlier, first knowable `lag_days` after the QUARTER
    ends, then held until the next release."""
    levels: dict[date, float] = {}
    for day, value in gdp:
        if day.month not in (1, 4, 7, 10):
            raise ValueError(f"quarterly series dated off-quarter: {day}")
        levels[month_end(day.year, day.month + 2)] = value
    growth = yoy_percent(levels)
    released = {effective_row(q_end, lag_days): value for q_end, value in growth.items()}
    return hold_forward(released, last)


def realized_volatility(closes: Series) -> dict[date, float]:
    """Annualised realised volatility (%) per calendar month from daily log
    returns; a month needs at least `_MIN_RETURNS_PER_MONTH` returns."""
    by_month: dict[date, list[float]] = {}
    for (_, previous), (day, price) in zip(closes, closes[1:], strict=False):
        by_month.setdefault(month_end_of(day), []).append(math.log(price / previous))
    out: dict[date, float] = {}
    for row, returns in by_month.items():
        if len(returns) >= _MIN_RETURNS_PER_MONTH:
            mean = sum(returns) / len(returns)
            variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
            out[row] = math.sqrt(variance * _TRADING_DAYS_PER_YEAR) * 100.0
    return out


@dataclass(frozen=True, slots=True)
class Grid:
    columns: tuple[str, ...]
    rows: dict[date, dict[str, float]]

    def column_range(self, column: str) -> tuple[date, date] | None:
        present = sorted(row for row, values in self.rows.items() if column in values)
        return (present[0], present[-1]) if present else None


def _assemble(columns: Sequence[str], series: Mapping[str, Mapping[date, float]]) -> Grid:
    rows: dict[date, dict[str, float]] = {}
    for column in columns:
        for row, value in series[column].items():
            if GRID_START <= row <= GRID_END:
                rows.setdefault(row, {})[column] = value
    return Grid(tuple(columns), dict(sorted(rows.items())))


def build_extended_macro_grid(members: Mapping[str, str]) -> Grid:
    """`members` maps each `BACKBONE_MEMBERS` value (the file name inside the
    Kaggle backbone zip) to its decoded text."""
    last_period = date(2023, 3, 31)
    first_period = date(1947, 1, 31)

    def fred(column: str) -> Series:
        return parse_fred_csv(members[BACKBONE_MEMBERS[column]])

    spx = parse_investing_csv(members[BACKBONE_MEMBERS["SPX"]])
    series: dict[str, dict[date, float]] = {
        "GDP_YOY": quarterly_yoy_released(
            fred("GDP_YOY"), PUBLICATION_LAG_DAYS["GDP_YOY"], GRID_END
        ),
        "CLAIMS_YOY": apply_lag(
            yoy_percent(monthly_levels(fred("CLAIMS_YOY"), first_period, last_period)),
            PUBLICATION_LAG_DAYS["CLAIMS_YOY"],
        ),
        "FEDFUNDS": apply_lag(
            monthly_levels(fred("FEDFUNDS"), first_period, last_period),
            PUBLICATION_LAG_DAYS["FEDFUNDS"],
        ),
        "UNRATE": apply_lag(monthly_period_levels(fred("UNRATE")), PUBLICATION_LAG_DAYS["UNRATE"]),
        "CPI_YOY_SA": apply_lag(
            yoy_percent(monthly_period_levels(fred("CPI_YOY_SA"))),
            PUBLICATION_LAG_DAYS["CPI_YOY_SA"],
        ),
        "BANK_CREDIT_YOY": apply_lag(
            yoy_percent(monthly_levels(fred("BANK_CREDIT_YOY"), first_period, last_period)),
            PUBLICATION_LAG_DAYS["BANK_CREDIT_YOY"],
        ),
        "SPX_YOY": apply_lag(
            yoy_percent(monthly_levels(spx, first_period, last_period)),
            PUBLICATION_LAG_DAYS["SPX_YOY"],
        ),
        "SPX_VOL": apply_lag(realized_volatility(spx), PUBLICATION_LAG_DAYS["SPX_VOL"]),
    }
    return _assemble(EXTENDED_MACRO_COLUMNS, series)


def build_baseline_grid(members: Mapping[str, str]) -> Grid:
    """Re-derive the five columns of the PR-145 snapshot with the SAME helpers the
    extended grid uses. `members` must also carry the `BASELINE_ONLY_MEMBERS` files.
    This is what makes the PR-145 snapshot auditable: PR-145's own prep script was
    never committed."""
    extended = build_extended_macro_grid(members)
    first_period, last_period = date(1947, 1, 31), date(2023, 3, 31)
    series: dict[str, dict[date, float]] = {
        c: {row: values[c] for row, values in extended.rows.items() if c in values}
        for c in ("GDP_YOY", "CLAIMS_YOY", "FEDFUNDS")
    }
    for column, member in BASELINE_ONLY_MEMBERS.items():
        parser = parse_investing_csv if column == "NASDAQ_YOY" else parse_fred_csv
        levels = monthly_levels(parser(members[member]), first_period, last_period)
        series[column] = apply_lag(yoy_percent(levels), BASELINE_ONLY_LAG_DAYS[column])
    return _assemble(BASELINE_COLUMNS, series)


def count_baseline_mismatches(
    derived: Grid, baseline_csv_text: str, tolerance: float = 1e-9
) -> dict[str, int]:
    """Per column, how many rows of a committed baseline CSV differ from the
    re-derived value by more than `tolerance` (or are missing from the derivation)."""
    mismatches = {column: 0 for column in BASELINE_COLUMNS}
    for record in csv.DictReader(io.StringIO(baseline_csv_text)):
        row = month_end(int(record["date"][:4]), int(record["date"][4:6]))
        values = derived.rows.get(row, {})
        for column in BASELINE_COLUMNS:
            expected = values.get(column)
            if expected is None or abs(expected - float(record[column])) > tolerance:
                mismatches[column] += 1
    return mismatches


def build_term_spread_grid(treasury_text: str) -> tuple[Grid, dict[date, int]]:
    """Monthly mean of the daily 10Y-3M par-yield spread (the Estrella-Mishkin
    indicator), same convention as the committed home.treasury.gov snapshot."""
    three_month, ten_year = parse_treasury_daily(treasury_text)
    by_month: dict[date, list[float]] = {}
    for (day, short), (_, long) in zip(three_month, ten_year, strict=True):
        by_month.setdefault(month_end_of(day), []).append(long - short)
    spread: dict[date, float] = {}
    days: dict[date, int] = {}
    for row, values in by_month.items():
        if len(values) >= _MIN_SPREAD_DAYS_PER_MONTH:
            spread[row] = sum(values) / len(values)
            days[row] = len(values)
    last_row = date(2024, 6, 30)
    clipped = {row: v for row, v in spread.items() if row < last_row}  # June 2024 is partial
    grid = Grid(
        (TERM_SPREAD_COLUMN,), {row: {TERM_SPREAD_COLUMN: v} for row, v in sorted(clipped.items())}
    )
    return grid, {row: days[row] for row in clipped}


def build_fed_policy_grid(index_text: str) -> Grid:
    """Monthly rows of the Federal Reserve dataset. Period-matched (each value
    describes the month on its row) and NOT lag-shifted: the policy study applies
    its own one-month publication delay."""
    rows: dict[date, dict[str, float]] = {}
    sources = (
        ("FFR_EFFECTIVE", "Effective Federal Funds Rate"),
        ("UNRATE", "Unemployment Rate"),
        ("INFLATION", "Inflation Rate"),
        ("REAL_GDP_GROWTH", "Real GDP (Percent Change)"),
    )
    required = ("Year", "Month", "Day", *(source for _, source in sources))
    for line, record in iter_csv_rows(index_text, "Fed index csv", required):
        if record["Day"] != "01":
            continue
        year = _integer(record["Year"], "Fed index csv", line)
        month = _integer(record["Month"], "Fed index csv", line)
        if not (1 <= month <= 12 and 1 <= year <= 9999):
            raise SnapshotParseError(f"Fed index csv: line {line}: {year}-{month} is not a month")
        row = month_end(year, month)
        values: dict[str, float] = {}
        for column, source in sources:
            if record[source].strip():
                values[column] = _number(record[source], "Fed index csv", line)
        if values:
            rows[row] = values
    return Grid(FED_COLUMNS, dict(sorted(rows.items())))


# --------------------------------------------------------------------------- writers


def _format(value: float) -> str:
    return f"{value:.10g}"


def write_grid_csv(
    path: Path, grid: Grid, extra: Mapping[date, Mapping[str, int]] | None = None
) -> None:
    extra_columns = sorted({c for values in (extra or {}).values() for c in values})
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["date", *grid.columns, *extra_columns])
        for row, values in grid.rows.items():
            cells = [_format(values[c]) if c in values else "" for c in grid.columns]
            cells += [str((extra or {}).get(row, {}).get(c, "")) for c in extra_columns]
            writer.writerow([f"{row.year:04d}{row.month:02d}", *cells])


def write_close_csv(path: Path, closes: Series) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["date", "close"])
        for day, price in closes:
            writer.writerow([day.isoformat(), _format(price)])


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


_ARCHIVE_ERRORS = (
    zipfile.BadZipFile,  # bad CRC, bad local header
    zlib.error,  # corrupted deflate stream
    lzma.LZMAError,
    EOFError,  # truncated bz2 / lzma stream
    NotImplementedError,  # unsupported compression method
    RuntimeError,  # an encrypted member
    OSError,  # bz2 "invalid data stream"
    ValueError,  # a shifted directory offset: "negative seek value -1"
)
"""What the zip library raises when the archive's data, not its directory, is damaged."""


def read_zip_members(
    zip_path: Path, wanted: Sequence[str]
) -> tuple[dict[str, str], dict[str, str]]:
    """Validate the archive with the project's own SEC-08 sandbox, then read the
    wanted members IN MEMORY (nothing is extracted to disk). Returns
    (decoded text per member, SHA-256 of each member's raw bytes)."""
    data = zip_path.read_bytes()
    validate_zip_archive(data)
    texts: dict[str, str] = {}
    digests: dict[str, str] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for name in wanted:
                try:
                    raw = archive.read(name)
                except KeyError:
                    raise SnapshotParseError(f"{zip_path.name}: no member named {name!r}") from None
                try:
                    texts[name] = raw.decode("utf-8-sig")
                except UnicodeDecodeError as exc:
                    raise SnapshotParseError(f"{name}: not valid UTF-8: {exc}") from exc
                digests[name] = sha256_hex(raw)
    except SnapshotParseError:
        raise
    except _ARCHIVE_ERRORS as exc:
        # A corrupted or truncated download: the central directory parsed, the data did not.
        raise SnapshotParseError(
            f"{zip_path.name}: corrupted archive ({type(exc).__name__}: {exc})"
        ) from exc
    return texts, digests


def _range_text(grid: Grid, column: str) -> dict[str, str]:
    span = grid.column_range(column)
    return {"first_row": span[0].isoformat(), "last_row": span[1].isoformat()} if span else {}


def _value_at(grid: Grid, column: str, row: date) -> float:
    return grid.rows[row][column]


def _write_meta(path: Path, meta: Mapping[str, object]) -> None:
    path.write_text(json.dumps(meta, indent=2, sort_keys=False) + "\n")


_LAG_NOTE = (
    "FIXED, documented assumptions (not fetched release vintages; ALFRED is unreachable "
    "here). A period's value is re-keyed to the first month-end at or after (period end "
    "+ lag), so the value on row M is knowable by M's own end."
)
_MACRO_COLUMN_NOTES: dict[str, str] = {
    "GDP_YOY": (
        "FRED GDP (quarterly, nominal), YoY % vs the same quarter a year earlier; released "
        "once per quarter and HELD until the next release"
    ),
    "CLAIMS_YOY": (
        "FRED CCSA continued claims (weekly), last weekly value at or before month-end, YoY %"
    ),
    "FEDFUNDS": (
        "FRED DFF effective federal funds rate (daily), last value at or before month-end, "
        "level in percent"
    ),
    "UNRATE": "FRED UNRATE unemployment rate (monthly, seasonally adjusted), level in percent",
    "CPI_YOY_SA": (
        "FRED CPIAUCSL CPI-U all items, SEASONALLY ADJUSTED (not the NSA series the "
        "INFLATIONCAST target uses), YoY %"
    ),
    "BANK_CREDIT_YOY": (
        "FRED TOTBKCR bank credit of all commercial banks (weekly), last weekly value at or "
        "before month-end, YoY %"
    ),
    "SPX_YOY": "Investing.com S&P 500 daily close, last close at or before month-end, YoY %",
    "SPX_VOL": (
        "annualised realised volatility (%) of the month's daily log returns, needs >= 15 returns"
    ),
}


def _sanity_macro(grid: Grid) -> dict[str, float]:
    """Computed (never asserted) values at dates whose real-world outcome is
    independently known; `tests/unit/test_kaggle_build.py` checks them against
    the committed snapshot."""
    return {
        "SPX_YOY row 2008-10 (financial-crisis crash)": _value_at(
            grid, "SPX_YOY", date(2008, 10, 31)
        ),
        "UNRATE row 2020-05 (April-2020 COVID peak, published early May)": _value_at(
            grid, "UNRATE", date(2020, 5, 31)
        ),
        "CPI_YOY_SA row 2022-07 (June-2022 inflation peak, published mid-July)": _value_at(
            grid, "CPI_YOY_SA", date(2022, 7, 31)
        ),
        "FEDFUNDS row 1981-06 (Volcker-era peak)": _value_at(grid, "FEDFUNDS", date(1981, 6, 30)),
        "SPX_VOL row 2008-10 (annualised realised volatility, %)": _value_at(
            grid, "SPX_VOL", date(2008, 10, 31)
        ),
    }


def _write_macro(out: Path, zip_path: Path, downloaded_at: str) -> None:
    texts, hashes = read_zip_members(zip_path, sorted(set(BACKBONE_MEMBERS.values())))
    grid = build_extended_macro_grid(texts)
    write_grid_csv(out / "kaggle_us_macro_extended_monthly.csv", grid)
    _write_meta(
        out / "kaggle_us_macro_extended_monthly.meta.json",
        {
            "source": (
                "Kaggle dataset mikoajfish99/us-recession-and-financial-indicators "
                "(FRED series plus Investing.com S&P 500 prices)"
            ),
            "source_url": KAGGLE_SOURCE_URL,
            "license": KAGGLE_SOURCE_LICENSE,
            "downloaded_at": downloaded_at,
            "raw_files_sha256": {name: hashes[name] for name in sorted(hashes)},
            "derived_by": "prometheus.data_ingestion.kaggle_build.build_extended_macro_grid",
            "columns": _MACRO_COLUMN_NOTES,
            "publication_lag_assumption_days": PUBLICATION_LAG_DAYS,
            "publication_lag_note": _LAG_NOTE,
            "grid": {
                "first_row": GRID_START.isoformat(),
                "last_row": GRID_END.isoformat(),
                "note": "blank cell = series does not exist yet; the grid is NOT rectangular",
            },
            "real_ranges": {c: _range_text(grid, c) for c in grid.columns},
            "sanity_checks": _sanity_macro(grid),
        },
    )


def _write_term_spread(out: Path, zip_path: Path, downloaded_at: str) -> None:
    texts, hashes = read_zip_members(zip_path, ["us_treasury_yields_daily.csv"])
    grid, days = build_term_spread_grid(texts["us_treasury_yields_daily.csv"])
    write_grid_csv(
        out / "kaggle_term_spread_monthly.csv",
        grid,
        {row: {"n_trading_days": n} for row, n in days.items()},
    )
    _write_meta(
        out / "kaggle_term_spread_monthly.meta.json",
        {
            "source": (
                "Kaggle dataset guillemservera/us-treasury-yields-daily "
                "(daily US Treasury constant-maturity yields)"
            ),
            "source_url": KAGGLE_TERM_SPREAD_SOURCE_URL,
            "license": KAGGLE_TERM_SPREAD_SOURCE_LICENSE,
            "downloaded_at": downloaded_at,
            "raw_files_sha256": hashes,
            "derived_by": "prometheus.data_ingestion.kaggle_build.build_term_spread_grid",
            "columns": {
                TERM_SPREAD_COLUMN: (
                    "mean over the month's trading days of (US10Y - US3M), percentage points; "
                    "needs >= 10 days with both yields published"
                )
            },
            "publication_lag_assumption_days": {TERM_SPREAD_COLUMN: 0},
            "real_ranges": {TERM_SPREAD_COLUMN: _range_text(grid, TERM_SPREAD_COLUMN)},
            "excluded": "2024-06 (partial month at the dataset's last update)",
            "sanity_checks": {
                "row 2000-07 (inversion before the 2001 recession)": _value_at(
                    grid, TERM_SPREAD_COLUMN, date(2000, 7, 31)
                ),
                "row 2007-01 (inversion before the Dec 2007 recession)": _value_at(
                    grid, TERM_SPREAD_COLUMN, date(2007, 1, 31)
                ),
                "row 2019-08 (inversion before the Feb 2020 recession)": _value_at(
                    grid, TERM_SPREAD_COLUMN, date(2019, 8, 31)
                ),
            },
            "cross_check": (
                "Against data_cache/treasury_yield_spread_monthly.csv (home.treasury.gov) on "
                "the 408 months both cover (1990-01..2023-12): max absolute difference 0.0093 "
                "percentage points, measured when this file was added."
            ),
        },
    )


def _write_sp500(out: Path, zip_path: Path, downloaded_at: str) -> None:
    texts, hashes = read_zip_members(zip_path, ["SPX.csv"])
    closes = parse_yahoo_close_csv(texts["SPX.csv"])
    write_close_csv(out / "kaggle_sp500_daily_close.csv", closes)
    worst_day, worst_return = min(
        ((d1, math.log(p1 / p0)) for (_, p0), (d1, p1) in zip(closes, closes[1:], strict=False)),
        key=lambda item: item[1],
    )
    _write_meta(
        out / "kaggle_sp500_daily_close.meta.json",
        {
            "source": (
                "Kaggle dataset henryhan117/sp-500-historical-data "
                "(Yahoo Finance ^GSPC daily history)"
            ),
            "source_url": KAGGLE_SP500_SOURCE_URL,
            "license": KAGGLE_SP500_SOURCE_LICENSE,
            "downloaded_at": downloaded_at,
            "raw_files_sha256": hashes,
            "derived_by": "prometheus.data_ingestion.kaggle_build.write_close_csv",
            "columns": {
                "close": (
                    "daily closing level; Adj Close equals Close on every row (an index), "
                    "so only Close is stored"
                )
            },
            "rows": len(closes),
            "real_range": {
                "first_date": closes[0][0].isoformat(),
                "last_date": closes[-1][0].isoformat(),
            },
            "caveat": (
                "Open = High = Low = Close on 8,547 early rows (last 1983-06-30): a close-only "
                "era, so only close-based statistics are meaningful there."
            ),
            "sanity_checks": {
                "worst daily log return": {"date": worst_day.isoformat(), "value": worst_return}
            },
        },
    )


def _write_fed(out: Path, zip_path: Path, downloaded_at: str) -> None:
    texts, hashes = read_zip_members(zip_path, ["index.csv"])
    grid = build_fed_policy_grid(texts["index.csv"])
    write_grid_csv(out / "kaggle_fed_policy_monthly.csv", grid)
    peak_row, peak = max(
        ((row, v["FFR_EFFECTIVE"]) for row, v in grid.rows.items() if "FFR_EFFECTIVE" in v),
        key=lambda item: item[1],
    )
    _write_meta(
        out / "kaggle_fed_policy_monthly.meta.json",
        {
            "source": (
                "Kaggle dataset federalreserve/interest-rates "
                "(Federal Reserve Interest Rates, 1954-Present)"
            ),
            "source_url": KAGGLE_FED_POLICY_SOURCE_URL,
            "license": KAGGLE_FED_POLICY_SOURCE_LICENSE,
            "downloaded_at": downloaded_at,
            "raw_files_sha256": hashes,
            "derived_by": "prometheus.data_ingestion.kaggle_build.build_fed_policy_grid",
            "columns": {
                "FFR_EFFECTIVE": "effective federal funds rate, percent (the row dated day 01)",
                "UNRATE": "unemployment rate, percent, seasonally adjusted",
                "INFLATION": "inflation rate, percent, as published in the dataset",
                "REAL_GDP_GROWTH": (
                    "quarterly real GDP growth, percent (SA rate of change); blank except in "
                    "the first month of a quarter"
                ),
            },
            "period_matched": (
                "each value describes its own row's month; NOT shifted for publication lag "
                "(the policy study applies a one-month delay)"
            ),
            "real_ranges": {c: _range_text(grid, c) for c in grid.columns},
            "sanity_checks": {
                "peak effective federal funds rate": {"row": peak_row.isoformat(), "value": peak}
            },
        },
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--backbone-zip", type=Path, required=True)
    parser.add_argument("--sp500-zip", type=Path)
    parser.add_argument("--treasury-zip", type=Path)
    parser.add_argument("--fed-zip", type=Path)
    parser.add_argument("--downloaded-at", type=str, help="ISO date the raw files were downloaded")
    parser.add_argument("--out-dir", type=Path, default=Path("data_cache"))
    parser.add_argument(
        "--verify-baseline",
        type=Path,
        help="only audit: re-derive the five PR-145 columns from --backbone-zip and compare "
        "them with this committed CSV (exit 1 on any mismatch); writes nothing",
    )
    args = parser.parse_args(argv)
    if args.verify_baseline is not None:
        members = sorted(set(BACKBONE_MEMBERS.values()) | set(BASELINE_ONLY_MEMBERS.values()))
        texts, _ = read_zip_members(args.backbone_zip, members)
        counts = count_baseline_mismatches(
            build_baseline_grid(texts), args.verify_baseline.read_text()
        )
        print(json.dumps({"mismatching_rows_per_column": counts}, indent=2))
        return 1 if any(counts.values()) else 0
    required = ("sp500_zip", "treasury_zip", "fed_zip", "downloaded_at")
    if any(getattr(args, name) is None for name in required):
        parser.error(
            "building snapshots needs --sp500-zip --treasury-zip --fed-zip --downloaded-at"
        )
    date.fromisoformat(args.downloaded_at)
    out: Path = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    _write_macro(out, args.backbone_zip, args.downloaded_at)
    _write_term_spread(out, args.treasury_zip, args.downloaded_at)
    _write_sp500(out, args.sp500_zip, args.downloaded_at)
    _write_fed(out, args.fed_zip, args.downloaded_at)
    print(f"wrote 4 snapshots and 4 .meta.json files to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
