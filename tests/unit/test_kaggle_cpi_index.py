"""PR-203: the monthly CPI index snapshot and its loader.

Row `r` of the file holds the index of month `r - 1` (knowable 15 days after that month ends);
the loader undoes the shift. Checked against three well-known facts about US inflation that are
independent of this code, and on synthetic files for every refusal.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pytest

from prometheus.data_ingestion.kaggle_build import build_cpi_index_grid, write_grid_csv
from prometheus.data_ingestion.kaggle_cpi_index import load_cpi_index

_DATA = Path(__file__).resolve().parents[2] / "data_cache" / "kaggle_cpi_index_monthly.csv"


@pytest.fixture(scope="module")
def real() -> tuple[tuple[date, ...], np.ndarray]:
    return load_cpi_index(_DATA)


def _yoy(real: tuple[tuple[date, ...], np.ndarray], month: date) -> float:
    months, levels = real
    i = months.index(month)
    return float(100.0 * (levels[i] / levels[i - 12] - 1.0))


def test_the_loader_returns_each_level_against_the_month_it_measures(
    real: tuple[tuple[date, ...], np.ndarray],
) -> None:
    months, levels = real
    assert months[0] == date(1947, 1, 31) and months[-1] == date(2023, 3, 31)
    assert len(months) == len(levels) == 915
    assert levels[0] == pytest.approx(21.48) and levels[-1] == pytest.approx(301.808)


def test_the_file_is_keyed_to_when_each_level_became_knowable() -> None:
    first_lines = _DATA.read_text().splitlines()[:2]
    assert first_lines == ["date,CPI_INDEX_SA", "194702,21.48"], (
        "January 1947 appears on the FEBRUARY row: it is published mid-February"
    )


def test_inflation_computed_from_the_levels_matches_three_known_episodes(
    real: tuple[tuple[date, ...], np.ndarray],
) -> None:
    """Independent facts: year-over-year CPI inflation peaked near 9.1% in June 2022, was about
    +0.1% in December 2008 and fell to about -2.1% in July 2009."""
    assert _yoy(real, date(2022, 6, 30)) == pytest.approx(9.1, abs=0.25)
    assert _yoy(real, date(2008, 12, 31)) == pytest.approx(0.1, abs=0.25)
    assert _yoy(real, date(2009, 7, 31)) == pytest.approx(-2.1, abs=0.25)


def test_months_are_consecutive_and_levels_positive(
    real: tuple[tuple[date, ...], np.ndarray],
) -> None:
    months, levels = real
    indices = [m.year * 12 + m.month for m in months]
    assert all(b - a == 1 for a, b in zip(indices, indices[1:], strict=False))
    assert np.all(np.isfinite(levels)) and np.all(levels > 0)


def test_the_builder_shifts_levels_to_the_month_they_become_knowable() -> None:
    text = "DATE,CPIAUCSL\n2020-01-01,100\n2020-02-01,101\n2020-03-01,102.5\n"
    member = "Consumer Price Index for All Urban Consumers All Items in U.S. City Average.csv"
    grid = build_cpi_index_grid({member: text})
    assert {row: values["CPI_INDEX_SA"] for row, values in grid.rows.items()} == {
        date(2020, 2, 29): 100.0,
        date(2020, 3, 31): 101.0,
        date(2020, 4, 30): 102.5,
    }


def test_the_builder_and_loader_round_trip(tmp_path: Path) -> None:
    text = "DATE,CPIAUCSL\n2021-11-01,270\n2021-12-01,271.5\n2022-01-01,273\n"
    member = "Consumer Price Index for All Urban Consumers All Items in U.S. City Average.csv"
    path = tmp_path / "cpi.csv"
    write_grid_csv(path, build_cpi_index_grid({member: text}))
    months, levels = load_cpi_index(path)
    assert months == (date(2021, 11, 30), date(2021, 12, 31), date(2022, 1, 31))
    assert list(levels) == [270.0, 271.5, 273.0]


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("date,CPI_INDEX_SA\n", "empty"),
        ("date,CPI_INDEX_SA\n202001,100\n202003,101\n", "consecutive"),
        ("date,CPI_INDEX_SA\n202001,100\n202002,nan\n", "finite and positive"),
        ("date,CPI_INDEX_SA\n202001,100\n202002,-5\n", "finite and positive"),
        ("date,CPI_INDEX_SA\n202001,100\n202002,0\n", "finite and positive"),
        ("date,CPI_INDEX_SA\n202001,inf\n", "finite and positive"),
    ],
)
def test_the_loader_refuses_empty_gappy_and_non_finite_files(
    tmp_path: Path, body: str, message: str
) -> None:
    path = tmp_path / "cpi.csv"
    path.write_text(body)
    with pytest.raises(ValueError, match=message):
        load_cpi_index(path)


def test_a_malformed_row_or_missing_column_is_a_parse_error(tmp_path: Path) -> None:
    from prometheus.data_ingestion.snapshot_integrity import SnapshotParseError

    bad_date = tmp_path / "a.csv"
    bad_date.write_text("date,CPI_INDEX_SA\nabcdef,100\n")
    with pytest.raises(SnapshotParseError, match="malformed row"):
        load_cpi_index(bad_date)
    no_column = tmp_path / "b.csv"
    no_column.write_text("date,other\n202001,100\n")
    with pytest.raises(SnapshotParseError, match="missing column"):
        load_cpi_index(no_column)
