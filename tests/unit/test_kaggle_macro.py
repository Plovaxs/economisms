from datetime import date
from pathlib import Path

import pytest

from prometheus.data_ingestion.kaggle_macro import (
    KAGGLE_SERIES_IDS,
    KAGGLE_SOURCE_LICENSE,
    load_kaggle_us_macro_observations,
)
from prometheus.econosim.pit import MacroObservation

_CSV_PATH = Path(__file__).resolve().parents[2] / "data_cache" / "kaggle_us_macro_monthly.csv"


def _write_tiny_csv(tmp_path: Path) -> Path:
    path = tmp_path / "tiny.csv"
    path.write_text(
        "date,GDP_YOY,CLAIMS_YOY,FEDFUNDS,M2_YOY,NASDAQ_YOY\n"
        "200801,2.1,5.0,4.25,6.0,-10.0\n"
        "200802,1.9,7.5,3.00,6.2,-12.5\n"
    )
    return path


def test_load_kaggle_us_macro_observations_on_a_tiny_fixture(tmp_path: Path) -> None:
    path = _write_tiny_csv(tmp_path)
    observations = load_kaggle_us_macro_observations(path)
    assert len(observations) == 2 * len(KAGGLE_SERIES_IDS)
    assert all(isinstance(o, MacroObservation) for o in observations)
    assert all(o.series_id in KAGGLE_SERIES_IDS for o in observations)
    assert all(o.source_license == KAGGLE_SOURCE_LICENSE for o in observations)
    assert all(o.published_at == o.observation_at for o in observations)

    gdp = next(
        o for o in observations if o.series_id == "KAGGLE_GDP_YOY" and o.observation_at.month == 1
    )
    assert gdp.value == pytest.approx(2.1)
    assert gdp.observation_at == date(2008, 1, 31)

    nasdaq_feb = next(
        o
        for o in observations
        if o.series_id == "KAGGLE_NASDAQ_YOY" and o.observation_at.month == 2
    )
    assert nasdaq_feb.value == pytest.approx(-12.5)


def test_load_kaggle_us_macro_observations_on_the_real_committed_snapshot() -> None:
    """The actual committed file this repository ships -- confirms it
    still parses and that the two real, independently-checkable sanity
    points from its own prep step (the 2008 financial-crisis NASDAQ
    crash and the 2020 COVID unemployment-claims spike) are present
    and correctly signed."""
    observations = load_kaggle_us_macro_observations(_CSV_PATH)
    assert len(observations) > 0
    assert all(o.series_id in KAGGLE_SERIES_IDS for o in observations)

    nasdaq_2008_10 = next(
        o
        for o in observations
        if o.series_id == "KAGGLE_NASDAQ_YOY" and o.observation_at == date(2008, 10, 31)
    )
    assert nasdaq_2008_10.value < -30.0  # real financial-crisis crash, confirmed negative and large

    claims_2020_04 = next(
        o
        for o in observations
        if o.series_id == "KAGGLE_CLAIMS_YOY" and o.observation_at == date(2020, 4, 30)
    )
    assert claims_2020_04.value > 200.0  # real COVID unemployment-claims spike
