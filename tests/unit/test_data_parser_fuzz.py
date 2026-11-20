"""PR-201: property tests (fuzzing) of every reader of a third-party data file.

The builder in `data_ingestion.kaggle_build` parses files that someone ELSE published
(Kaggle datasets, a zip archive), and its output trains every model here. The contract,
checked with arbitrary input rather than the handful of cases a person would think of:

* a parser returns a series that is sorted, has no duplicate date and holds only finite
  numbers (prices also strictly positive) -- or raises `SnapshotParseError`;
* it NEVER leaks a bare `KeyError` / `TypeError` / `ZeroDivisionError` / `csv.Error`;
* `nan`, `inf`, a non-positive price and a repeated date are each REJECTED (before this
  PR `float("nan")` parsed cleanly and slipped past a `price <= 0` test, because `nan`
  compares false against everything);
* well-formed input round-trips exactly.
"""

from __future__ import annotations

import csv
import io
import json
import math
import struct
import tempfile
import zipfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from prometheus.data_ingestion import kaggle_build as builder
from prometheus.data_ingestion import snapshot_integrity as integrity
from prometheus.data_ingestion.dataset_sandbox import UnsafeDatasetError, validate_zip_archive
from prometheus.data_ingestion.kaggle_build import (
    build_fed_policy_grid,
    parse_fred_csv,
    parse_investing_csv,
    parse_treasury_daily,
    parse_yahoo_close_csv,
    read_zip_members,
)
from prometheus.data_ingestion.kaggle_sp500 import load_sp500_closes
from prometheus.data_ingestion.snapshot_integrity import (
    MANIFEST_FILENAME,
    SnapshotIntegrityError,
    SnapshotParseError,
    load_manifest,
)

FUZZ = settings(
    max_examples=300,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)

Series = list[tuple[date, float]]
POISON = ["nan", "NaN", "-nan", "inf", "-inf", "Infinity", "1e999", "-1e999"]
NON_POSITIVE = ["0", "0.0", "-0", "-1", "-12.5", "1e-999"]


@contextmanager
def _temp_file(content: bytes, name: str = "data.bin") -> Iterator[Path]:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / name
        path.write_bytes(content)
        yield path


def _render(header: list[str], rows: list[list[str]]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return out.getvalue()


# name -> (parser, header, date cell, positive-only?)
def _fred_day(day: date) -> str:
    return day.isoformat()


def _investing_day(day: date) -> str:
    return f"{day.month:02d}/{day.day:02d}/{day.year:04d}"


SERIES_PARSERS: dict[
    str, tuple[Callable[[str], Series], list[str], Callable[[date], str], bool]
] = {
    "fred": (parse_fred_csv, ["DATE", "X"], _fred_day, False),
    "investing": (parse_investing_csv, ["Date", "Price"], _investing_day, True),
    "yahoo": (parse_yahoo_close_csv, ["Date", "Close"], _fred_day, True),
}
NAMES = list(SERIES_PARSERS)


def _assert_valid_series(series: Series, *, positive: bool) -> None:
    days = [day for day, _ in series]
    assert days == sorted(days), "dates must be ascending"
    assert len(set(days)) == len(days), "dates must be unique"
    assert all(math.isfinite(value) for _, value in series), "values must be finite"
    if positive:
        assert all(value > 0 for _, value in series), "prices must be positive"


def _contained(parse: Callable[[str], Series], text: str, *, positive: bool) -> Series | None:
    """Run a parser and assert the contract; return the series or None if it refused."""
    try:
        series = parse(text)
    except SnapshotParseError:
        return None
    _assert_valid_series(series, positive=positive)
    return series


odd_cells = st.one_of(
    st.sampled_from(
        [*POISON, *NON_POSITIVE, "", ".", " ", "5,08", "1,234.5", "1_0", "0x10", "١٢٣", "+7", "7."]
    ),
    st.floats(allow_nan=False, allow_infinity=False).map(repr),
    st.text(max_size=10),
)
day_cells = st.one_of(
    st.dates().map(date.isoformat),
    st.dates().map(_investing_day),
    st.sampled_from(["2023-02-30", "0000-00-00", "2023-13-01", "20230105", "13/40/2020", "", "x"]),
    st.text(max_size=12),
)


# ------------------------------------------------------------------ arbitrary input


@FUZZ
@given(text=st.text(max_size=300))
def test_arbitrary_text_is_parsed_or_rejected_by_every_series_parser(text: str) -> None:
    for name in NAMES:
        parse, _, _, positive = SERIES_PARSERS[name]
        _contained(parse, text, positive=positive)
    try:
        three, ten = parse_treasury_daily(text)
    except SnapshotParseError:
        return
    _assert_valid_series(three, positive=False)
    _assert_valid_series(ten, positive=False)
    assert [d for d, _ in three] == [d for d, _ in ten]


@FUZZ
@given(
    name=st.sampled_from(NAMES),
    rows=st.lists(st.tuples(day_cells, odd_cells), max_size=12),
)
def test_well_formed_csv_with_hostile_cells_is_parsed_or_rejected(
    name: str, rows: list[tuple[str, str]]
) -> None:
    parse, header, _, positive = SERIES_PARSERS[name]
    _contained(parse, _render(header, [list(row) for row in rows]), positive=positive)


@FUZZ
@given(
    rows=st.lists(st.tuples(day_cells, odd_cells, odd_cells), max_size=12),
    swap=st.booleans(),
)
def test_the_treasury_parser_keeps_both_legs_aligned_or_rejects(
    rows: list[tuple[str, str, str]], swap: bool
) -> None:
    header = ["US10Y", "US3M", "date"] if swap else ["date", "US3M", "US10Y"]
    body = [[r[2], r[1], r[0]] if swap else list(r) for r in rows]
    try:
        three, ten = parse_treasury_daily(_render(header, body))
    except SnapshotParseError:
        return
    assert [d for d, _ in three] == [d for d, _ in ten]
    _assert_valid_series(three, positive=False)


# ------------------------------------------------------------------ what must be rejected


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("poison", POISON)
def test_a_non_finite_value_is_always_rejected(name: str, poison: str) -> None:
    parse, header, day, _ = SERIES_PARSERS[name]
    good = [day(date(2020, 1, 2)), "10.5"]
    bad = [day(date(2020, 1, 3)), poison]
    with pytest.raises(SnapshotParseError):
        parse(_render(header, [good, bad]))


@pytest.mark.parametrize("name", ["investing", "yahoo"])
@pytest.mark.parametrize("value", NON_POSITIVE)
def test_a_non_positive_price_is_always_rejected(name: str, value: str) -> None:
    parse, header, day, _ = SERIES_PARSERS[name]
    with pytest.raises(SnapshotParseError, match="not an acceptable value"):
        parse(_render(header, [[day(date(2020, 1, 2)), value]]))


def test_the_rate_series_parser_still_accepts_zero_and_negative_values() -> None:
    """Rates and growth figures can be zero or negative; only prices are positive-only."""
    series = parse_fred_csv("DATE,X\n2020-01-01,0\n2020-02-01,-0.5\n")
    assert series == [(date(2020, 1, 1), 0.0), (date(2020, 2, 1), -0.5)]


@pytest.mark.parametrize("name", NAMES)
def test_a_repeated_date_is_rejected(name: str) -> None:
    parse, header, day, _ = SERIES_PARSERS[name]
    row = [day(date(2020, 1, 2)), "10.5"]
    with pytest.raises(SnapshotParseError, match="duplicate date 2020-01-02"):
        parse(_render(header, [row, row]))


@pytest.mark.parametrize("name", ["investing", "yahoo"])
def test_a_missing_column_is_a_parse_error_not_a_key_error(name: str) -> None:
    parse, header, _, _ = SERIES_PARSERS[name]
    with pytest.raises(SnapshotParseError, match="missing column"):
        parse(_render(header[:1], [["2020-01-02"]]))
    with pytest.raises(SnapshotParseError, match="short row"):
        parse(_render(header, [["2020-01-02"]]).replace("\n2020-01-02\n", "\n2020-01-02\n"))


def test_the_treasury_parser_names_a_missing_column() -> None:
    with pytest.raises(SnapshotParseError, match=r"missing column\(s\) \['US10Y'\]"):
        parse_treasury_daily("date,US3M\n2020-01-02,1.5\n")


def test_an_oversized_field_is_a_parse_error_not_a_csv_error() -> None:
    text = "Date,Price\n01/02/2020," + "9" * 200_000 + "\n"
    with pytest.raises(SnapshotParseError):
        parse_investing_csv(text)
    with pytest.raises(SnapshotParseError):
        parse_fred_csv("DATE,X\n2020-01-02," + "9" * 200_000 + "\n")


def test_a_malformed_fred_row_shape_still_names_itself() -> None:
    with pytest.raises(SnapshotParseError, match="unexpected FRED row shape"):
        parse_fred_csv("DATE,X\n2020-01-02,1,2,3\n")


def test_the_row_ceiling_applies_to_every_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(builder, "MAX_CSV_ROWS", 3)
    monkeypatch.setattr(integrity, "MAX_CSV_ROWS", 3)
    rows = [[f"2020-01-{day:02d}", "1.5"] for day in range(1, 6)]
    for name in NAMES:
        parse, header, day_text, _ = SERIES_PARSERS[name]
        body = [[day_text(date(2020, 1, d)), "1.5"] for d in range(1, 6)]
        with pytest.raises(SnapshotParseError, match="more than 3 rows"):
            parse(_render(header, body))
    assert len(rows) == 5


# ------------------------------------------------------------------ well-formed input round-trips


@FUZZ
@given(
    data=st.dictionaries(
        st.dates(),
        st.floats(min_value=0.01, max_value=1e9, allow_nan=False, allow_infinity=False),
        max_size=40,
    ),
    name=st.sampled_from(NAMES),
)
def test_well_formed_series_round_trip_exactly(data: dict[date, float], name: str) -> None:
    parse, header, day_text, positive = SERIES_PARSERS[name]
    rows = [[day_text(day), repr(value)] for day, value in data.items()]
    parsed = parse(_render(header, rows))
    assert parsed == sorted(data.items())
    _assert_valid_series(parsed, positive=positive)


@FUZZ
@given(
    data=st.dictionaries(
        st.dates(), st.floats(min_value=0.01, max_value=1e9, allow_nan=False), max_size=30
    )
)
def test_thousands_separators_in_investing_prices_round_trip(data: dict[date, float]) -> None:
    rows = [[_investing_day(day), f"{value:,.4f}"] for day, value in data.items()]
    parsed = parse_investing_csv(_render(["Date", "Price"], rows))
    assert parsed == sorted((day, float(f"{value:.4f}")) for day, value in data.items())


# ------------------------------------------------------------------ the Fed index builder


_FED_HEADER = [
    "Year",
    "Month",
    "Day",
    "Effective Federal Funds Rate",
    "Unemployment Rate",
    "Inflation Rate",
    "Real GDP (Percent Change)",
]


@FUZZ
@given(
    rows=st.lists(
        st.tuples(
            st.one_of(st.integers(-5, 12000).map(str), st.text(max_size=5)),
            st.one_of(st.integers(-3, 15).map(str), st.text(max_size=5)),
            st.sampled_from(["01", "02", "1", ""]),
            odd_cells,
            odd_cells,
            odd_cells,
            odd_cells,
        ),
        max_size=10,
    )
)
def test_the_fed_index_builder_is_contained_and_never_emits_a_non_finite_value(
    rows: list[tuple[str, ...]],
) -> None:
    try:
        grid = build_fed_policy_grid(_render(_FED_HEADER, [list(row) for row in rows]))
    except SnapshotParseError:
        return
    for values in grid.rows.values():
        assert all(math.isfinite(v) for v in values.values())


def test_the_fed_index_builder_rejects_an_impossible_month() -> None:
    row = ["2000", "13", "01", "5.5", "4.0", "2.0", "3.0"]
    with pytest.raises(SnapshotParseError, match="not a month"):
        build_fed_policy_grid(_render(_FED_HEADER, [row]))


# ------------------------------------------------------------------ the S&P 500 snapshot loader


@FUZZ
@given(text=st.text(max_size=300))
def test_the_sp500_loader_returns_clean_arrays_or_a_value_error(text: str) -> None:
    with _temp_file(text.encode("utf-8", errors="replace"), "x.csv") as path:
        try:
            days, closes = load_sp500_closes(path)
        except ValueError:
            return
    assert len(days) == closes.size
    assert np.all(np.isfinite(closes)) and np.all(closes > 0)
    assert all(b > a for a, b in zip(days, days[1:], strict=False))


@pytest.mark.parametrize("close", ["nan", "inf", "-inf", "0", "-1"])
def test_the_sp500_loader_rejects_nan_inf_and_non_positive_closes(close: str) -> None:
    text = f"date,close\n2020-01-02,10.0\n2020-01-03,{close}\n"
    with _temp_file(text.encode(), "x.csv") as path, pytest.raises(ValueError):  # noqa: PT011
        load_sp500_closes(path)


# ------------------------------------------------------------------ the manifest loader


json_values: st.SearchStrategy[Any] = st.recursive(
    st.none() | st.booleans() | st.integers(-5, 10**12) | st.text(max_size=12),
    lambda inner: st.lists(inner, max_size=3) | st.dictionaries(st.text(max_size=12), inner),
    max_leaves=12,
)


@FUZZ
@given(document=json_values)
def test_the_manifest_loader_accepts_only_well_formed_documents(document: Any) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / MANIFEST_FILENAME).write_text(json.dumps(document))
        try:
            entries = load_manifest(root)
        except SnapshotIntegrityError:
            return
    for name, entry in entries.items():
        assert name and not name.startswith("/") and ".." not in name.split("/")
        assert len(entry.sha256) == 64 and entry.size >= 0


@FUZZ
@given(raw=st.binary(max_size=200))
def test_the_manifest_loader_survives_arbitrary_bytes(raw: bytes) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / MANIFEST_FILENAME).write_bytes(raw)
        try:
            load_manifest(root)
        except SnapshotIntegrityError:
            pass


# ------------------------------------------------------------------ corrupted or hostile archives


def _small_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("a.csv", "DATE,X\n2020-01-01,1.5\n" * 50)
    return buffer.getvalue()


def _read_or_refuse(mutated: bytes) -> None:
    """Whatever the zip library raises (`BadZipFile`, `zlib.error`, `NotImplementedError`,
    ...) must reach the caller as a `ValueError` subclass, or the member must read intact."""
    with _temp_file(mutated, "z.zip") as path:
        try:
            texts, digests = read_zip_members(path, ["a.csv"])
        except (UnsafeDatasetError, SnapshotParseError):
            return
    assert set(texts) == {"a.csv"} and len(digests["a.csv"]) == 64


@FUZZ
@given(
    flips=st.lists(st.tuples(st.integers(0, 10_000), st.integers(0, 255)), min_size=1, max_size=6)
)
def test_bit_flips_in_an_archive_are_refused_with_a_value_error_never_a_library_error(
    flips: list[tuple[int, int]],
) -> None:
    """Bit flips, the first thing a bad download does. The archive keeps its length (and
    so, usually, its central directory), which is exactly what lets a corrupted
    compressed stream reach the decompressor."""
    blob = bytearray(_small_zip())
    for position, value in flips:
        blob[position % len(blob)] = value
    _read_or_refuse(bytes(blob))


@FUZZ
@given(cut=st.integers(0, 10_000))
def test_a_truncated_archive_is_refused_with_a_value_error_never_a_library_error(
    cut: int,
) -> None:
    blob = _small_zip()
    _read_or_refuse(blob[: cut % (len(blob) + 1)])


@pytest.mark.parametrize("offset", range(30))
def test_a_flipped_byte_inside_the_compressed_stream_is_always_contained(offset: int) -> None:
    """The deterministic counterpart of the property above: flip each byte of the
    compressed stream in turn (this was the case that leaked `zlib.error` and
    `BadZipFile` before PR-201)."""
    blob = bytearray(_small_zip())
    blob[30 + len("a.csv") + offset] ^= 0xFF
    _read_or_refuse(bytes(blob))


@FUZZ
@given(
    flips=st.lists(st.tuples(st.integers(0, 10_000), st.integers(0, 255)), min_size=1, max_size=6),
    cut=st.one_of(st.none(), st.integers(0, 10_000)),
)
def test_the_sandbox_itself_answers_with_its_own_error_for_any_damaged_archive(
    flips: list[tuple[int, int]], cut: int | None
) -> None:
    """`validate_zip_archive` is the SEC-08 sandbox. Hypothesis found it letting a raw
    `NotImplementedError` ("zip file version 6.4") escape; it must answer with
    `UnsafeDatasetError` -- or accept the archive -- and never anything else."""
    blob = bytearray(_small_zip())
    for position, value in flips:
        blob[position % len(blob)] = value
    data = bytes(blob if cut is None else blob[: cut % (len(blob) + 1)])
    try:
        validate_zip_archive(data)
    except UnsafeDatasetError:
        pass


def test_an_unsupported_zip_version_is_refused_by_the_sandbox() -> None:
    """The first case Hypothesis found: the version-needed-to-extract field set to 6.4."""
    blob = bytearray(_small_zip())
    directory = blob.find(b"PK\x01\x02")
    blob[directory + 6 : directory + 8] = struct.pack("<H", 64)
    with pytest.raises(UnsafeDatasetError, match="not a valid zip archive"):
        validate_zip_archive(bytes(blob))
    with _temp_file(bytes(blob), "z.zip") as path, pytest.raises(UnsafeDatasetError):
        read_zip_members(path, ["a.csv"])


def test_a_shifted_central_directory_offset_is_a_parse_error_not_a_bare_value_error() -> None:
    """The second case Hypothesis found: the directory offset is one byte too large, so
    the first member's header offset becomes -1 and `zipfile` raises `ValueError: negative
    seek value -1` from deep inside."""
    blob = bytearray(_small_zip())
    end = blob.rfind(b"PK\x05\x06")
    (offset,) = struct.unpack("<I", blob[end + 16 : end + 20])
    blob[end + 16 : end + 20] = struct.pack("<I", offset + 1)
    with (
        _temp_file(bytes(blob), "z.zip") as path,
        pytest.raises(SnapshotParseError, match="corrupted archive"),
    ):
        read_zip_members(path, ["a.csv"])


@FUZZ
@given(raw=st.binary(max_size=300))
def test_arbitrary_bytes_are_never_an_acceptable_archive_unless_they_are_one(raw: bytes) -> None:
    with _temp_file(raw, "z.zip") as path:
        try:
            read_zip_members(path, ["a.csv"])
        except (UnsafeDatasetError, SnapshotParseError):
            return
    pytest.fail("random bytes were accepted as an archive containing a.csv")


def test_a_missing_member_is_a_parse_error_not_a_key_error() -> None:
    with (
        _temp_file(_small_zip(), "z.zip") as path,
        pytest.raises(SnapshotParseError, match="no member"),
    ):
        read_zip_members(path, ["absent.csv"])


def test_a_non_utf8_member_is_a_parse_error() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("a.csv", b"DATE,X\n\xff\xfe,1\n")
    with (
        _temp_file(buffer.getvalue(), "z.zip") as path,
        pytest.raises(SnapshotParseError, match="UTF-8"),
    ):
        read_zip_members(path, ["a.csv"])


def test_a_valid_archive_reads_back_with_its_digest() -> None:
    with _temp_file(_small_zip(), "z.zip") as path:
        texts, digests = read_zip_members(path, ["a.csv"])
    assert texts["a.csv"].startswith("DATE,X\n2020-01-01,1.5\n")
    assert digests["a.csv"] == builder.sha256_hex(texts["a.csv"].encode())
