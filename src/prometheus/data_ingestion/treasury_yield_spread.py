"""The real US Treasury 10-Year/3-Month yield-curve spread, monthly-
averaged -- the Estrella-Mishkin / NY Fed recession-probability
model's own indicator (a yield-curve inversion: short rates above long
rates), closing a real, disclosed gap in RECESSIONNET's own feature
set: neither the Kenneth French factors nor the Kaggle macro snapshot
include any direct measure of the yield curve, despite it being one of
the most-studied real recession predictors in the macro-finance
literature. See `orchestration.recessionnet_yield_curve_run` for where
this feeds a real RECESSIONNET variant.

This is deliberately a SEPARATE, narrower module from
`data_ingestion.treasury_yield_curve` (DAT-04/PR-146), not an
extension of it or a duplicate: that module is a live, multi-tenor
(11 tenors) connector with recorded day-count/holiday conventions,
fetching via FRED's `fredgraph.csv` export -- which was unreachable
from this environment both at that module's original implementation
time (its own docstring) and independently reconfirmed unreachable
here (a direct timeout, re-checked before writing this module).
`home.treasury.gov`'s own public CSV endpoint was independently
confirmed REACHABLE instead (real data fetched and sanity-checked
against three well-known historical inversions: 2000-07 before the
2001 recession, 2007-01 before the Dec 2007 recession, and the
widely-reported August 2019 inversion before the Feb 2020 recession --
see the committed snapshot's own `.meta.json`). Rather than touch
DAT-04's own scope, conventions, or tests, this module fetches only
the two tenors a recession-prediction feature actually needs (3-Month,
10-Year) from that different, currently-reachable primary source, and
commits the result as an already-derived snapshot -- the same
"no live network call at demo/test time" convention
`data_ingestion.kaggle_macro`/`us_cpi_monthly.csv` already use, so
this module needs no egress-allowlist entry of its own.

The committed `data_cache/treasury_yield_spread_monthly.csv` covers
1990-01 through 2023-12 -- `home.treasury.gov`'s CSV endpoint returns
nothing before 1990 (confirmed by direct request), roughly nine years
later than the Kaggle macro snapshot's own 1981-12 start. See its own
`.meta.json` for exact provenance and the monthly-averaging method.
"""

from __future__ import annotations

import calendar
import csv
from datetime import date
from pathlib import Path

from prometheus.econosim.pit import MacroObservation

TREASURY_YIELD_SPREAD_SOURCE_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/"
    "interest-rates/daily-treasury-rates.csv"
)
TREASURY_YIELD_SPREAD_SOURCE_LICENSE = "US Government work, public domain"
YIELD_SPREAD_SERIES_IDS: tuple[str, ...] = (
    "TREASURY_3MO",
    "TREASURY_10YR",
    "TREASURY_10Y_3M_SPREAD",
)


def load_treasury_yield_spread_observations(path: Path) -> list[MacroObservation]:
    """Loads the committed monthly grid into `MacroObservation`s, one
    per (month, series). `published_at` is set equal to
    `observation_at`: Treasury publishes each business day's par yield
    curve rates same-day, so a given month's average is honestly
    knowable by that month's own end -- no lag re-keying needed, unlike
    `kaggle_macro.py`'s GDP/claims series."""
    observations: list[MacroObservation] = []
    with path.open() as f:
        for row in csv.DictReader(f):
            year, month = int(row["date"][:4]), int(row["date"][4:6])
            observation_at = date(year, month, calendar.monthrange(year, month)[1])
            for series_id in YIELD_SPREAD_SERIES_IDS:
                observations.append(
                    MacroObservation(
                        series_id=series_id,
                        observation_at=observation_at,
                        published_at=observation_at,
                        value=float(row[series_id]),
                        source_url=TREASURY_YIELD_SPREAD_SOURCE_URL,
                        source_license=TREASURY_YIELD_SPREAD_SOURCE_LICENSE,
                        frequency="M",
                    )
                )
    return observations
