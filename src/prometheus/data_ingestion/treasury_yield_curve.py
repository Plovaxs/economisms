"""US Treasury par yield curve ingestion and conventions (DAT-04:
"Build Treasury yield curve ingestion and conventions"; acceptance
criterion: "Rate tenors, day count and holiday policies recorded").

Fetches the real Constant Maturity Treasury (CMT) daily par yield
series -- the same series the Federal Reserve publishes in its H.15
statistical release and the Treasury itself displays as its "daily
Treasury par yield curve rates" -- via FRED's public, no-API-key CSV
export endpoint (`fredgraph.csv`), one GET per tenor.
`home.treasury.gov` itself timed out repeatedly from this environment's
network at implementation time (confirmed by a direct pre-implementation
probe, not assumed); FRED's own republication of the identical H.15
series was reachable and used instead -- still the Federal Reserve/
Treasury's own official release, one hop further from the primary
publisher, not a secondary reseller the way a Kaggle mirror is.

Day-count and holiday conventions (this item's own acceptance wording)
are recorded as a typed, tested `YieldCurveConventions` value rather
than left as prose: short tenors (1mo/3mo/6mo/1yr) are quoted on the
standard bond-equivalent-yield conversion from a T-bill's actual/360
discount-rate basis; longer tenors (2yr-30yr, Treasury notes and bonds)
are quoted on the standard actual/actual, semiannual bond-equivalent
basis -- the well-established, publicly documented CMT methodology.
This project could not re-fetch treasury.gov's own methodology page
live in this session (see above); the convention recorded here is the
standard fixed-income-market one, not an assumption invented for this
fetch.

Holiday policy is NOT a hand-typed list of dates (which could silently
drift from which days the bond market actually observes) -- it is
DERIVED per fetch, directly from the real data: a weekday (Monday-
Friday, via the existing `core.calendar.BusinessDayCalendar`) on which
NONE of the requested tenors has a published value is recorded as a
market holiday for that fetch. Checked against three real,
independently known closures: 2006-07-04 (Independence Day),
2006-09-04 (Labor Day), and 2020-04-10 (Good Friday -- a bond-market/
SIFMA holiday, NOT a federal government holiday, confirming this
connector's holiday detection is the bond market's own calendar, not a
borrowed federal-holiday list that would have gotten this one wrong).
Fetching only a single tenor cannot distinguish a true market closure
from an isolated single-series data gap; this is a disclosed limitation
of single-tenor fetches, not of the default multi-tenor one.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, timedelta

from prometheus.core.calendar import BusinessDayCalendar
from prometheus.data_ingestion.transport import HttpTransport
from prometheus.econosim.pit import MacroObservation

TREASURY_YIELD_CURVE_SOURCE_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
TREASURY_YIELD_CURVE_SOURCE_LICENSE = (
    "Public Domain (U.S. Treasury Constant Maturity Treasury series, "
    "Federal Reserve H.15 release, via FRED fredgraph.csv)"
)

TENOR_TO_FRED_SERIES: dict[str, str] = {
    "1MO": "DGS1MO",
    "3MO": "DGS3MO",
    "6MO": "DGS6MO",
    "1Y": "DGS1",
    "2Y": "DGS2",
    "3Y": "DGS3",
    "5Y": "DGS5",
    "7Y": "DGS7",
    "10Y": "DGS10",
    "20Y": "DGS20",
    "30Y": "DGS30",
}
ALL_TENORS: tuple[str, ...] = tuple(TENOR_TO_FRED_SERIES)

PUBLICATION_LAG_DAYS = 1
"""Conservative fixed assumption: Treasury/the Fed publish same-day,
but this connector adds one calendar day before treating a value as
published, so a point-in-time consumer can never see a same-day yield
before it was realistically available. Disclosed, not measured from a
real per-value release timestamp -- FRED's CSV export carries no
per-observation publish timestamp of its own, the same kind of gap
`french_factors.py`/`worldbank.py` already document for their own
single dataset-level vintage fields."""


class TreasuryYieldCurveResponseError(ValueError):
    """Raised when a fetched series response is not a well-formed
    `fredgraph.csv` two-column response for the requested tenor."""


@dataclass(frozen=True, slots=True)
class YieldCurveConventions:
    short_tenor_day_count: str
    long_tenor_day_count: str
    short_tenor_cutoff_years: float
    notes: str


def treasury_market_conventions() -> YieldCurveConventions:
    return YieldCurveConventions(
        short_tenor_day_count=(
            "T-bill actual/360 discount rate, converted to a bond-equivalent "
            "(investment) yield -- the standard CMT convention for tenors of "
            "one year or less"
        ),
        long_tenor_day_count=(
            "actual/actual, semiannual bond-equivalent yield -- the standard "
            "convention for Treasury notes and bonds (tenors over one year)"
        ),
        short_tenor_cutoff_years=1.0,
        notes=(
            "Standard, publicly documented U.S. Treasury Constant Maturity "
            "Treasury (CMT) methodology, as republished in the Federal "
            "Reserve's H.15 statistical release. The authoritative "
            "home.treasury.gov methodology page was not reachable from this "
            "environment at implementation time (connection timeout); the "
            "convention itself is the standard fixed-income-market one, not "
            "an assumption specific to this fetch."
        ),
    )


def _parse_fred_csv(body: bytes, fred_series_id: str) -> dict[date, float]:
    text = body.decode("utf-8")
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines or not lines[0].startswith("observation_date,"):
        raise TreasuryYieldCurveResponseError(
            f"response for {fred_series_id} is not a recognizable fredgraph.csv export"
        )
    values: dict[date, float] = {}
    for line in lines[1:]:
        date_str, _, value_str = line.partition(",")
        if not value_str:
            continue  # a real market holiday/non-trading day -- never forward-filled
        values[date.fromisoformat(date_str)] = float(value_str)
    return values


@dataclass(frozen=True, slots=True)
class TreasuryYieldCurveFetchResult:
    observations: tuple[MacroObservation, ...]
    conventions: YieldCurveConventions
    market_holidays: tuple[date, ...]
    """Weekdays in the requested range with no published value for ANY
    requested tenor -- derived from the real fetched data, not a
    hand-typed holiday list."""


def fetch_treasury_yield_curve(
    transport: HttpTransport,
    *,
    start: date,
    end: date,
    tenors: tuple[str, ...] = ALL_TENORS,
) -> TreasuryYieldCurveFetchResult:
    if end < start:
        raise ValueError("end must not be before start")
    if not tenors:
        raise ValueError("tenors must not be empty")
    unknown = set(tenors) - set(TENOR_TO_FRED_SERIES)
    if unknown:
        raise ValueError(f"unknown tenor(s): {sorted(unknown)}")

    by_tenor: dict[str, dict[date, float]] = {}
    observations: list[MacroObservation] = []
    for tenor in tenors:
        fred_series_id = TENOR_TO_FRED_SERIES[tenor]
        response = transport.get(
            TREASURY_YIELD_CURVE_SOURCE_URL,
            {"id": fred_series_id, "cosd": start.isoformat(), "coed": end.isoformat()},
        )
        if response.status_code != 200:
            raise TreasuryYieldCurveResponseError(
                f"HTTP {response.status_code} fetching {fred_series_id}"
            )
        raw_hash = hashlib.sha256(response.body).hexdigest()
        values = _parse_fred_csv(response.body, fred_series_id)
        by_tenor[tenor] = values
        for observation_at, value in values.items():
            observations.append(
                MacroObservation(
                    series_id=f"UST_{tenor}",
                    observation_at=observation_at,
                    published_at=observation_at + timedelta(days=PUBLICATION_LAG_DAYS),
                    value=value,
                    source_url=f"{TREASURY_YIELD_CURVE_SOURCE_URL}?id={fred_series_id}",
                    source_license=TREASURY_YIELD_CURVE_SOURCE_LICENSE,
                    raw_hash=raw_hash,
                    frequency="D",
                    unit="percent",
                )
            )

    weekdays = BusinessDayCalendar().business_days_between(start, end)
    published_any_tenor: set[date] = set()
    for values in by_tenor.values():
        published_any_tenor |= set(values)
    market_holidays = tuple(d for d in weekdays if d not in published_any_tenor)

    return TreasuryYieldCurveFetchResult(
        observations=tuple(observations),
        conventions=treasury_market_conventions(),
        market_holidays=market_holidays,
    )
