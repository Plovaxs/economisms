"""Tests for the committed Kaggle snapshot builder (`data_ingestion.kaggle_build`) and
for the committed snapshots it produced (PR-197).

Hermetic: the raw Kaggle archives are NOT in the repository, so the builder's logic is
tested on small synthetic inputs, and the committed snapshots are checked against
real-world facts that are independently known (the 2008 crash, the 2020 unemployment
peak, the 1987 Black Monday, ...), against each other, and against one structural
invariant that makes a point-in-time look-ahead impossible to reintroduce silently.
"""

from __future__ import annotations

import csv
import json
import math
import zipfile
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from prometheus.data_ingestion.dataset_sandbox import UnsafeDatasetError
from prometheus.data_ingestion.kaggle_build import (
    BASELINE_COLUMNS,
    Grid,
    add_months,
    apply_lag,
    build_fed_policy_grid,
    build_spliced_sp500,
    build_term_spread_grid,
    count_baseline_mismatches,
    effective_row,
    hold_forward,
    month_end,
    monthly_levels,
    parse_fred_csv,
    parse_investing_csv,
    parse_treasury_daily,
    parse_yahoo_close_csv,
    quarterly_yoy_released,
    read_zip_members,
    realized_volatility,
    write_grid_csv,
    yoy_percent,
)
from prometheus.data_ingestion.kaggle_fed_policy import (
    KAGGLE_FED_POLICY_SOURCE_LICENSE,
    KAGGLE_FED_POLICY_SOURCE_URL,
    load_fed_policy_months,
)
from prometheus.data_ingestion.kaggle_macro import (
    KAGGLE_SOURCE_LICENSE,
    KAGGLE_SOURCE_URL,
    load_kaggle_us_macro_observations,
)
from prometheus.data_ingestion.kaggle_macro_extended import (
    EXTENDED_MACRO_COLUMNS,
    SERIES_PREFIX,
    load_extended_macro_observations,
    series_id,
)
from prometheus.data_ingestion.kaggle_sp500 import (
    KAGGLE_SP500_SOURCE_LICENSE,
    KAGGLE_SP500_SOURCE_URL,
    load_sp500_closes,
    log_returns,
)
from prometheus.data_ingestion.kaggle_term_spread import (
    KAGGLE_TERM_SPREAD_SOURCE_LICENSE,
    KAGGLE_TERM_SPREAD_SOURCE_URL,
    load_term_spread_observations,
)
from prometheus.data_ingestion.snapshot_integrity import SnapshotParseError

_DATA = Path(__file__).resolve().parents[2] / "data_cache"


# ----------------------------------------------------------------------------- parsers


def test_parse_fred_csv_skips_missing_markers_and_reads_decimal_commas() -> None:
    text = "DATE,DFF\n2023-05-01,5.07\n2023-05-02,.\n2023-05-03,5,08\n2023-05-04,\n"
    assert parse_fred_csv(text) == [(date(2023, 5, 1), 5.07), (date(2023, 5, 3), 5.08)]


def test_parse_fred_csv_rejects_a_row_it_cannot_interpret() -> None:
    with pytest.raises(ValueError, match="unexpected FRED row shape"):
        parse_fred_csv("DATE,X\n2020-01-01,1,2,3\n")


def test_parse_investing_csv_reads_thousands_separators_and_sorts_ascending() -> None:
    text = (
        '"Date","Price","Open","High","Low","Vol.","Change %"\n'
        '"05/03/2023","4,090.75","4,122.25","4,148.30","4,088.86","","-0.70%"\n'
        '"12/26/1979","107.80","107.80","108.40","107.10","","0.09%"\n'
    )
    assert parse_investing_csv(text) == [(date(1979, 12, 26), 107.80), (date(2023, 5, 3), 4090.75)]


def test_parse_yahoo_close_csv_and_treasury_daily() -> None:
    assert parse_yahoo_close_csv(
        "Date,Open,High,Low,Close,Adj Close,Volume\n2020-01-02,1,2,0,1.5,1.5,0\n"
    ) == [(date(2020, 1, 2), 1.5)]
    treasury = (
        "date,US1M,US3M,US6M,US1Y,US2Y,US3Y,US5Y,US7Y,US10Y,US20Y,US30Y\n"
        "1981-09-01,,15.0,,,,,,,15.5,,\n"
        "1981-09-02,,,,,,,,,15.6,,\n"
    )
    short, long = parse_treasury_daily(treasury)
    assert short == [(date(1981, 9, 1), 15.0)] and long == [(date(1981, 9, 1), 15.5)]


# ----------------------------------------------------------------------------- calendar


def test_effective_row_is_the_first_month_end_at_or_after_period_end_plus_lag() -> None:
    assert effective_row(date(2020, 3, 31), 0) == date(2020, 3, 31)
    assert effective_row(date(2020, 3, 31), 7) == date(2020, 4, 30)
    assert effective_row(date(2020, 3, 31), 30) == date(2020, 4, 30)  # quarterly GDP release
    assert effective_row(date(2020, 6, 30), 30) == date(2020, 7, 31)
    assert effective_row(date(2020, 12, 31), 15) == date(2021, 1, 31)


def test_add_months_moves_between_month_ends_across_year_boundaries() -> None:
    assert add_months(date(2020, 1, 31), -12) == date(2019, 1, 31)
    assert add_months(date(2020, 3, 31), 1) == date(2020, 4, 30)
    assert add_months(date(2020, 12, 31), 2) == date(2021, 2, 28)


# ----------------------------------------------------------------------------- derivations


def test_monthly_levels_takes_the_last_observation_and_refuses_a_stale_one() -> None:
    weekly = [
        (date(2020, 1, 4), 1.0),
        (date(2020, 1, 25), 2.0),  # last obs on/before 2020-01-31, 6 days old
        (date(2020, 2, 22), 3.0),  # last obs on/before 2020-02-29, 7 days old
        # then a long gap: nothing until late April
        (date(2020, 4, 25), 9.0),
    ]
    levels = monthly_levels(weekly, date(2020, 1, 31), date(2020, 4, 30))
    assert levels[date(2020, 1, 31)] == 2.0
    assert levels[date(2020, 2, 29)] == 3.0
    assert date(2020, 3, 31) not in levels, "a 38-day-old value must not be carried forward"
    assert levels[date(2020, 4, 30)] == 9.0


def test_yoy_percent_needs_the_value_twelve_months_earlier() -> None:
    levels = {date(2019, 1, 31): 100.0, date(2020, 1, 31): 110.0, date(2020, 2, 29): 50.0}
    assert yoy_percent(levels) == {date(2020, 1, 31): pytest.approx(10.0)}


def test_apply_lag_shifts_a_monthly_series_to_the_row_it_becomes_knowable() -> None:
    assert apply_lag({date(2020, 4, 30): 1.0, date(2020, 5, 31): 2.0}, 7) == {
        date(2020, 5, 31): 1.0,
        date(2020, 6, 30): 2.0,
    }
    assert apply_lag({date(2020, 4, 30): 1.0}, 0) == {date(2020, 4, 30): 1.0}


def test_hold_forward_repeats_a_release_until_the_next_one() -> None:
    held = hold_forward({date(2020, 1, 31): 1.0, date(2020, 4, 30): 2.0}, date(2020, 6, 30))
    assert [held[r] for r in sorted(held)] == [1.0, 1.0, 1.0, 2.0, 2.0, 2.0]


def _quarterly_gdp() -> list[tuple[date, float]]:
    """2019: 100..103; 2020: 104 / 90 (the Q2 collapse) / 100 / 108; first of each quarter."""
    levels = [100, 101, 102, 103, 104, 90, 100, 108]
    months = [1, 4, 7, 10] * 2
    years = [2019] * 4 + [2020] * 4
    return [(date(y, m, 1), float(v)) for y, m, v in zip(years, months, levels, strict=True)]


def test_quarterly_gdp_is_released_after_the_quarter_ends_not_during_it() -> None:
    """The PR-145 look-ahead, as a regression test. Q2-2020's YoY (90/101 - 1 = -10.89%)
    ends on 2020-06-30 and is first knowable 30 days later; it must NOT appear on the
    2020-05 or 2020-06 rows (PR-145 showed it from 2020-05)."""
    rows = quarterly_yoy_released(_quarterly_gdp(), 30, date(2020, 12, 31))
    q1_yoy = (104 / 100 - 1) * 100
    q2_yoy = (90 / 101 - 1) * 100
    assert rows[date(2020, 4, 30)] == pytest.approx(q1_yoy)  # Q1 released 2020-04-30
    assert rows[date(2020, 5, 31)] == pytest.approx(q1_yoy)
    assert rows[date(2020, 6, 30)] == pytest.approx(q1_yoy)
    assert rows[date(2020, 7, 31)] == pytest.approx(q2_yoy)
    assert rows[date(2020, 9, 30)] == pytest.approx(q2_yoy)
    assert rows[date(2020, 10, 31)] == pytest.approx((100 / 102 - 1) * 100)


def test_quarterly_gdp_rejects_a_series_that_is_not_dated_on_quarter_starts() -> None:
    with pytest.raises(ValueError, match="off-quarter"):
        quarterly_yoy_released([(date(2020, 2, 1), 1.0)], 30, date(2020, 12, 31))


def test_realized_volatility_needs_a_minimum_number_of_returns() -> None:
    full_month = [(date(2020, 1, d), 100.0 * (1.01 if d % 2 else 0.99) ** d) for d in range(1, 29)]
    vol = realized_volatility(full_month)
    assert set(vol) == {date(2020, 1, 31)} and vol[date(2020, 1, 31)] > 0
    assert realized_volatility(full_month[:10]) == {}


def test_term_spread_is_the_monthly_mean_and_needs_ten_trading_days() -> None:
    header = "date,US1M,US3M,US6M,US1Y,US2Y,US3Y,US5Y,US7Y,US10Y,US20Y,US30Y\n"
    rows = "".join(f"1990-01-{d:02d},,8.0,,,,,,,9.0,,\n" for d in range(1, 16))
    rows += "".join(f"1990-02-{d:02d},,8.0,,,,,,,9.0,,\n" for d in range(1, 4))  # too few days
    grid, days = build_term_spread_grid(header + rows)
    assert list(grid.rows) == [date(1990, 1, 31)]
    assert grid.rows[date(1990, 1, 31)]["TERM_SPREAD_10Y3M"] == pytest.approx(1.0)
    assert days == {date(1990, 1, 31): 15}


def test_fed_policy_grid_keeps_only_the_first_of_month_rows() -> None:
    text = (
        "Year,Month,Day,Federal Funds Target Rate,Federal Funds Upper Target,"
        "Federal Funds Lower Target,Effective Federal Funds Rate,Real GDP (Percent Change),"
        "Unemployment Rate,Inflation Rate\n"
        "1982,09,01,10.5,,,11.0,,9.8,6.1\n"
        "1982,09,27,10.0,,,,,,\n"
    )
    grid = build_fed_policy_grid(text)
    assert grid.rows == {
        date(1982, 9, 30): {"FFR_EFFECTIVE": 11.0, "UNRATE": 9.8, "INFLATION": 6.1}
    }


def test_count_baseline_mismatches_flags_a_changed_value_and_a_missing_row() -> None:
    derived = Grid(BASELINE_COLUMNS, {date(2020, 1, 31): dict.fromkeys(BASELINE_COLUMNS, 1.0)})
    header = "date," + ",".join(BASELINE_COLUMNS) + "\n"
    good = header + "202001," + ",".join(["1.0"] * 5) + "\n"
    assert count_baseline_mismatches(derived, good) == dict.fromkeys(BASELINE_COLUMNS, 0)
    changed = header + "202001,1.0,1.0,1.0,1.0,1.5\n" + "202002," + ",".join(["1.0"] * 5) + "\n"
    counts = count_baseline_mismatches(derived, changed)
    assert counts["NASDAQ_YOY"] == 2 and counts["GDP_YOY"] == 1  # 1 changed + 1 missing row


# ----------------------------------------------------------------------------- IO


def test_a_written_grid_round_trips_through_the_extended_loader_and_skips_blanks(
    tmp_path: Path,
) -> None:
    grid = Grid(
        ("UNRATE", "SPX_YOY"),
        {date(1980, 1, 31): {"UNRATE": 6.3}, date(1981, 1, 31): {"UNRATE": 7.5, "SPX_YOY": -3.25}},
    )
    path = tmp_path / "grid.csv"
    write_grid_csv(path, grid)
    assert path.read_text().splitlines()[1] == "198001,6.3,"
    observations = load_extended_macro_observations(path, ("UNRATE", "SPX_YOY"))
    assert [(o.series_id, o.observation_at.year, o.value) for o in observations] == [
        (series_id("UNRATE"), 1980, 6.3),
        (series_id("UNRATE"), 1981, 7.5),
        (series_id("SPX_YOY"), 1981, -3.25),
    ]
    assert all(o.published_at == o.observation_at for o in observations)
    with pytest.raises(ValueError, match="unknown extended macro columns"):
        load_extended_macro_observations(path, ("NOPE",))


def test_read_zip_members_validates_the_archive_and_records_content_digests(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "ok.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("a.csv", "x,y\n1,2\n")
    texts, digests = read_zip_members(archive, ["a.csv"])
    assert texts == {"a.csv": "x,y\n1,2\n"}
    assert len(digests["a.csv"]) == 64

    bomb = tmp_path / "bomb.zip"
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("zeros.csv", b"0" * 5_000_000)
    with pytest.raises(UnsafeDatasetError):
        read_zip_members(bomb, ["zeros.csv"])


# ----------------------------------------------------------------------------- committed snapshots


def _rows(name: str) -> list[dict[str, str]]:
    with (_DATA / name).open() as handle:
        return list(csv.DictReader(handle))


def _value(rows: list[dict[str, str]], key: str, column: str) -> float:
    return float(next(r for r in rows if r["date"] == key)[column])


def test_committed_extended_macro_snapshot_matches_independently_known_events() -> None:
    rows = _rows("kaggle_us_macro_extended_monthly.csv")
    assert _value(rows, "200810", "SPX_YOY") < -35  # the 2008 crash (about -37%)
    assert _value(rows, "202005", "UNRATE") == pytest.approx(14.7)  # April-2020 peak, published May
    assert _value(rows, "202207", "CPI_YOY_SA") > 8.5  # the June-2022 inflation peak
    assert _value(rows, "198106", "FEDFUNDS") > 18  # Volcker-era policy rate
    assert _value(rows, "200810", "SPX_VOL") > 60  # crisis realised volatility, annualised %
    assert [r["date"] for r in rows][0] == "196001" and [r["date"] for r in rows][-1] == "202301"


def test_committed_extended_grid_ranges_are_what_the_meta_file_records() -> None:
    meta = json.loads((_DATA / "kaggle_us_macro_extended_monthly.meta.json").read_text())
    rows = _rows("kaggle_us_macro_extended_monthly.csv")
    for column in EXTENDED_MACRO_COLUMNS:
        present = [r["date"] for r in rows if r[column] != ""]
        first, last = (
            meta["real_ranges"][column]["first_row"],
            meta["real_ranges"][column]["last_row"],
        )
        assert f"{present[0][:4]}-{present[0][4:]}" == first[:7]
        assert f"{present[-1][:4]}-{present[-1][4:]}" == last[:7]


@pytest.mark.parametrize(
    "name",
    ["kaggle_us_macro_extended_monthly.csv", "kaggle_us_macro_monthly.csv"],
)
def test_committed_gdp_column_only_changes_on_release_rows(name: str) -> None:
    """The structural invariant that makes the PR-145 look-ahead impossible to
    reintroduce: quarterly GDP is released ~30 days after a quarter ends, so its
    value may only CHANGE on the Jan/Apr/Jul/Oct rows. PR-145's grid changed on 288
    other rows."""
    previous: float | None = None
    for row in _rows(name):
        if row["GDP_YOY"] == "":
            continue
        value = float(row["GDP_YOY"])
        month = int(row["date"][4:])
        if previous is not None and value != previous:
            assert month in (1, 4, 7, 10), f"GDP_YOY changed on row {row['date']}"
        previous = value


def test_committed_baseline_shows_the_covid_gdp_collapse_only_when_it_was_released() -> None:
    rows = _rows("kaggle_us_macro_monthly.csv")
    assert _value(rows, "202005", "GDP_YOY") == pytest.approx(2.5, abs=0.01)  # still Q1's value
    assert _value(rows, "202006", "GDP_YOY") == pytest.approx(2.5, abs=0.01)
    assert _value(rows, "202007", "GDP_YOY") == pytest.approx(-7.689368896330128, abs=1e-6)


def test_committed_baseline_grid_still_has_its_other_four_columns_unchanged() -> None:
    """PR-197 rewrote ONLY GDP_YOY; the committed builder reproduces the other four
    columns exactly (494 of 494 months each), so they are asserted at known points."""
    observations = load_kaggle_us_macro_observations(_DATA / "kaggle_us_macro_monthly.csv")
    by = {(o.series_id, o.observation_at): o.value for o in observations}
    assert by[("KAGGLE_NASDAQ_YOY", date(2008, 10, 31))] == pytest.approx(-39.8, abs=0.1)
    assert by[("KAGGLE_CLAIMS_YOY", date(2020, 4, 30))] == pytest.approx(339.1, abs=0.1)


def test_committed_term_spread_matches_the_home_treasury_snapshot_on_common_months() -> None:
    kaggle = {
        r["date"]: float(r["TERM_SPREAD_10Y3M"]) for r in _rows("kaggle_term_spread_monthly.csv")
    }
    treasury = {
        r["date"]: float(r["TREASURY_10Y_3M_SPREAD"])
        for r in _rows("treasury_yield_spread_monthly.csv")
    }
    common = sorted(set(kaggle) & set(treasury))
    assert len(common) == 408
    assert max(abs(kaggle[m] - treasury[m]) for m in common) < 0.01
    assert min(kaggle) == "198109"  # the 3-month yield starts in 1981-09
    assert kaggle["200701"] < 0 and kaggle["201908"] < 0 and kaggle["200007"] < 0  # real inversions


def test_committed_term_spread_loader_returns_one_observation_per_month() -> None:
    observations = load_term_spread_observations(_DATA / "kaggle_term_spread_monthly.csv")
    assert len(observations) == 513
    assert len({o.observation_at for o in observations}) == 513


def test_committed_sp500_snapshot_is_a_clean_price_history() -> None:
    dates, closes = load_sp500_closes(_DATA / "kaggle_sp500_daily_close.csv")
    assert (
        len(dates) == 23_323 and dates[0] == date(1927, 12, 30) and dates[-1] == date(2020, 11, 4)
    )
    returns = log_returns(closes)
    worst = int(returns.argmin())
    assert dates[worst + 1] == date(1987, 10, 19) and returns[worst] == pytest.approx(
        -0.229, abs=1e-3
    )
    assert (
        float(((returns - returns.mean()) ** 4).mean() / returns.var() ** 2) - 3 > 15
    )  # fat tails


def test_sp500_loader_rejects_unsorted_dates_and_non_positive_prices(tmp_path: Path) -> None:
    bad_order = tmp_path / "a.csv"
    bad_order.write_text("date,close\n2020-01-02,1\n2020-01-01,1\n")
    with pytest.raises(ValueError, match="strictly increasing"):
        load_sp500_closes(bad_order)
    bad_price = tmp_path / "b.csv"
    bad_price.write_text("date,close\n2020-01-01,0\n")
    with pytest.raises(ValueError, match="positive"):
        load_sp500_closes(bad_price)
    with pytest.raises(ValueError, match="at least two"):
        log_returns(np.array([1.0]))


def test_committed_fed_policy_snapshot_covers_the_documented_range() -> None:
    months = load_fed_policy_months(_DATA / "kaggle_fed_policy_monthly.csv")
    effective = [(m.month_end, m.ffr_effective) for m in months if m.ffr_effective is not None]
    assert effective[0][0] == date(1954, 7, 31) and effective[-1][0] == date(2017, 2, 28)
    assert len(effective) == 752
    peak_month, peak = max(effective, key=lambda item: item[1] or 0.0)
    assert peak_month == date(1981, 6, 30) and peak == pytest.approx(19.1)
    assert sum(m.real_gdp_growth is not None for m in months) == 250  # quarterly


def test_every_new_snapshot_has_a_meta_file_that_names_its_source_license_and_raw_hashes() -> None:
    expected = {
        "kaggle_us_macro_extended_monthly": (KAGGLE_SOURCE_URL, KAGGLE_SOURCE_LICENSE),
        "kaggle_term_spread_monthly": (
            KAGGLE_TERM_SPREAD_SOURCE_URL,
            KAGGLE_TERM_SPREAD_SOURCE_LICENSE,
        ),
        "kaggle_sp500_daily_close": (KAGGLE_SP500_SOURCE_URL, KAGGLE_SP500_SOURCE_LICENSE),
        "kaggle_fed_policy_monthly": (
            KAGGLE_FED_POLICY_SOURCE_URL,
            KAGGLE_FED_POLICY_SOURCE_LICENSE,
        ),
    }
    for stem, (url, license_text) in expected.items():
        meta = json.loads((_DATA / f"{stem}.meta.json").read_text())
        assert meta["source_url"] == url and meta["license"] == license_text
        assert meta["downloaded_at"] == "2026-11-19"
        hashes = meta["raw_files_sha256"]
        assert hashes and all(len(h) == 64 and int(h, 16) >= 0 for h in hashes.values())
    # The NC licence restriction is stated where a reader of the derived file will see it.
    assert "non-commercial" in KAGGLE_TERM_SPREAD_SOURCE_LICENSE.lower()


def test_series_ids_are_namespaced_so_they_cannot_collide_with_the_pr145_ids() -> None:
    assert series_id("UNRATE") == "KAGGLEX_UNRATE" and SERIES_PREFIX != "KAGGLE_"
    with pytest.raises(ValueError, match="unknown extended macro column"):
        series_id("GDP")


def test_month_end_handles_leap_years() -> None:
    assert month_end(2020, 2) == date(2020, 2, 29)
    assert month_end(2021, 2) == date(2021, 2, 28)


# ------------------------------------------------------- PR-202: spliced S&P 500 and NASDAQ


def _yahoo_csv(rows: list[tuple[str, float]]) -> str:
    return "Date,Open,High,Low,Close,Adj Close,Volume\n" + "".join(
        f"{d},{p},{p},{p},{p},{p},0\n" for d, p in rows
    )


def _investing_csv(rows: list[tuple[str, float]]) -> str:
    """Newest first, `MM/DD/YYYY`, thousands separators: the real file's shape."""
    lines = ['"Date","Price","Open","High","Low","Vol.","Change %"']
    for day, price in reversed(rows):
        year, month, d = day.split("-")
        lines.append(f'"{month}/{d}/{year}","{price:,.2f}","1","1","1","","0%"')
    return "\n".join(lines) + "\n"


def _zip_with(path: Path, members: dict[str, str]) -> Path:
    import zipfile

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in members.items():
            archive.writestr(name, text)
    return path


def test_the_spliced_series_joins_exactly_and_records_how_well_the_vendors_agree() -> None:
    yahoo = [(date(2020, 1, 1), 100.0), (date(2020, 1, 2), 101.0), (date(2020, 1, 3), 102.0)]
    other = [
        (date(2020, 1, 1), 200.0),
        (date(2020, 1, 2), 202.0),
        (date(2020, 1, 3), 204.0),
        (date(2020, 1, 6), 206.0),
        (date(2020, 1, 7), 208.0),
    ]
    spliced, agreement = build_spliced_sp500(yahoo, other)
    assert spliced[:3] == yahoo, "the original history is untouched"
    assert agreement["scale_at_join"] == 0.5
    assert spliced[3:] == [(date(2020, 1, 6), 103.0), (date(2020, 1, 7), 104.0)]
    # a return is scale-free: the join-day return is the continuation's own
    assert math.log(spliced[3][1] / spliced[2][1]) == pytest.approx(math.log(206.0 / 204.0))
    assert agreement["overlap_days"] == 3 and agreement["continuation_days"] == 2
    assert agreement["median_abs_level_gap"] == pytest.approx(0.0)
    assert agreement["share_of_days_return_difference_below_10bp"] == 1.0
    assert agreement["continuation_first_date"] == "2020-01-06"


def test_the_spliced_agreement_statistics_show_a_disagreement_when_there_is_one() -> None:
    yahoo = [(date(2020, 1, d), 100.0 + d) for d in range(1, 6)]
    other = [(d, p * 2.0) for d, p in yahoo]
    other[2] = (other[2][0], other[2][1] * 1.02)  # a 2% vendor discrepancy on one day
    other.append((date(2020, 1, 8), 220.0))
    _, agreement = build_spliced_sp500(yahoo, other)
    assert agreement["max_abs_level_gap"] == pytest.approx(0.02)
    assert agreement["max_abs_return_difference"] > 0.015
    assert agreement["share_of_days_return_difference_below_10bp"] < 1.0


def test_a_splice_without_a_shared_join_date_or_a_continuation_is_refused() -> None:
    yahoo = [(date(2020, 1, 1), 100.0), (date(2020, 1, 2), 101.0)]
    with pytest.raises(SnapshotParseError, match="join date 2020-01-02"):
        build_spliced_sp500(yahoo, [(date(2020, 1, 1), 5.0), (date(2020, 1, 3), 6.0)])
    with pytest.raises(SnapshotParseError, match="no day after the join"):
        build_spliced_sp500(yahoo, [(date(2020, 1, 1), 5.0), (date(2020, 1, 2), 6.0)])


def test_the_market_writers_produce_loadable_snapshots_with_provenance(tmp_path: Path) -> None:
    from prometheus.data_ingestion.kaggle_build import _write_markets
    from prometheus.data_ingestion.kaggle_sp500 import load_daily_closes

    yahoo_rows = [("2020-01-02", 100.0), ("2020-01-03", 101.0), ("2020-01-06", 99.5)]
    spx_rows = [(d, p * 1.5) for d, p in yahoo_rows] + [
        ("2020-01-07", 151.0),
        ("2020-01-08", 152.5),
    ]
    nasdaq_rows = [("2020-01-02", 9000.0), ("2020-01-03", 9100.5), ("2020-01-06", 9050.25)]
    backbone = _zip_with(
        tmp_path / "backbone.zip",
        {"SPX500.csv": _investing_csv(spx_rows), "NASDAQ.csv": _investing_csv(nasdaq_rows)},
    )
    sp500 = _zip_with(tmp_path / "sp500.zip", {"SPX.csv": _yahoo_csv(yahoo_rows)})
    out = tmp_path / "out"
    out.mkdir()
    _write_markets(out, backbone, sp500, "2026-11-20")

    days, closes = load_daily_closes(out / "kaggle_sp500_spliced_daily_close.csv")
    assert len(days) == 5 and days[-1] == date(2020, 1, 8)
    assert closes[3] == pytest.approx(151.0 / 1.5, rel=1e-9)
    nas_days, nas_closes = load_daily_closes(out / "kaggle_nasdaq_daily_close.csv", "NASDAQ")
    assert len(nas_days) == 3 and nas_closes[1] == pytest.approx(9100.5)

    meta = json.loads((out / "kaggle_sp500_spliced_daily_close.meta.json").read_text())
    assert set(meta["raw_files_sha256"]) == {"SPX.csv", "SPX500.csv"}
    assert meta["splice"]["overlap_days"] == 3 and meta["rows"] == 5
    assert meta["license"].startswith("ODbL-1.0")
    nas_meta = json.loads((out / "kaggle_nasdaq_daily_close.meta.json").read_text())
    assert set(nas_meta["raw_files_sha256"]) == {"NASDAQ.csv"}
    assert nas_meta["real_range"] == {"first_date": "2020-01-02", "last_date": "2020-01-06"}


def test_the_generic_close_loader_labels_its_errors_with_the_market_it_was_given(
    tmp_path: Path,
) -> None:
    from prometheus.data_ingestion.kaggle_sp500 import load_daily_closes

    path = tmp_path / "x.csv"
    path.write_text("date,close\n2020-01-02,10\n2020-01-02,11\n")
    with pytest.raises(ValueError, match="NASDAQ dates must be strictly increasing"):
        load_daily_closes(path, "NASDAQ")
