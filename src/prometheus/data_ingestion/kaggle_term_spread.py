"""The US Treasury 10-Year minus 3-Month par-yield spread (the Estrella-Mishkin /
NY Fed recession indicator), monthly-averaged, from a Kaggle dataset of daily
Treasury yields (`guillemservera/us-treasury-yields-daily`, CC BY-NC 4.0).

Why a second source for a series `treasury_yield_spread` already provides:
`home.treasury.gov`'s CSV starts in 1990, while this Kaggle copy carries the 3M
yield from 1981-09, which lets the yield-curve recession experiments use the
whole 1981-12 .. 2023-01 range of the Kaggle macro snapshot instead of 1990+.
Verified when it was added: on the 408 months both sources cover (1990-01 ..
2023-12) the two spreads differ by at most 0.0093 percentage points.

LICENCE NOTE: CC BY-NC 4.0 is a NON-COMMERCIAL licence. The derived
`data_cache/kaggle_term_spread_monthly.csv` inherits that restriction (attribution
and non-commercial use); this research repository is a course project.

Committed as an already-derived snapshot (`kaggle_build.build_term_spread_grid`),
so loading makes no network call. Publication lag 0: Treasury publishes each
day's par yields the same day, so the month's mean is knowable at month-end.
"""

from __future__ import annotations

import calendar
from datetime import date
from pathlib import Path

from prometheus.data_ingestion.snapshot_integrity import verified_dict_reader
from prometheus.econosim.pit import MacroObservation

KAGGLE_TERM_SPREAD_SOURCE_URL = (
    "https://www.kaggle.com/datasets/guillemservera/us-treasury-yields-daily"
)
KAGGLE_TERM_SPREAD_SOURCE_LICENSE = (
    "CC BY-NC 4.0 (Kaggle: guillemservera/us-treasury-yields-daily; non-commercial use)"
)
TERM_SPREAD_SERIES_ID = "KAGGLE_TERM_SPREAD_10Y3M"
TERM_SPREAD_COLUMN = "TERM_SPREAD_10Y3M"


def load_term_spread_observations(path: Path) -> list[MacroObservation]:
    observations: list[MacroObservation] = []
    for row in verified_dict_reader(path, required=("date", TERM_SPREAD_COLUMN)):
        year, month = int(row["date"][:4]), int(row["date"][4:6])
        observation_at = date(year, month, calendar.monthrange(year, month)[1])
        observations.append(
            MacroObservation(
                series_id=TERM_SPREAD_SERIES_ID,
                observation_at=observation_at,
                published_at=observation_at,
                value=float(row[TERM_SPREAD_COLUMN]),
                source_url=KAGGLE_TERM_SPREAD_SOURCE_URL,
                source_license=KAGGLE_TERM_SPREAD_SOURCE_LICENSE,
                frequency="M",
            )
        )
    return observations
