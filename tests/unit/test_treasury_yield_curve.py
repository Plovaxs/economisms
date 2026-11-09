"""Tests use REAL FRED `fredgraph.csv` responses -- captured live for
three specific tenors/windows during this connector's own
pre-implementation verification (a direct `urllib` probe run before any
production code was written, confirming `home.treasury.gov` itself
times out from this environment while `fred.stlouisfed.org` is
reachable) -- embedded here verbatim as plain-text literals (these
responses are small CSV text, not binary, so no base64 wrapping is
needed the way `test_french_factors.py`'s zip archive needed it).

The three captured windows were deliberately chosen to double as real,
independently-known-event sanity checks: the 2006 DGS10/DGS2 window
spans the 2-year/10-year inversion that preceded the 2008 recession
(DGS10 - DGS2 = 4.79 - 4.86 = -0.07 on 2006-08-25, a genuine, dated
inversion, not a hand-asserted number), and the 2020 DGS3MO window
spans the COVID-19 emergency rate cut (yield = 0.00 on 2020-03-25 and
2020-03-26). All three windows also each contain one real market-
closure gap -- 2006-07-04, 2006-09-04, and 2020-04-10 respectively --
used to confirm `fetch_treasury_yield_curve`'s holiday derivation
against real, independently known closures without hand-typing a
federal-holiday list.
"""

from datetime import date

import pytest

from prometheus.data_ingestion.transport import HttpResponse
from prometheus.data_ingestion.treasury_yield_curve import (
    ALL_TENORS,
    TREASURY_YIELD_CURVE_SOURCE_LICENSE,
    TREASURY_YIELD_CURVE_SOURCE_URL,
    TreasuryYieldCurveResponseError,
    fetch_treasury_yield_curve,
    treasury_market_conventions,
)

# Real fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10&cosd=2006-06-01&coed=2006-09-30
_DGS10_2006_CSV = """observation_date,DGS10
2006-06-01,5.11
2006-06-02,5.00
2006-06-05,5.02
2006-06-06,5.01
2006-06-07,5.02
2006-06-08,5.00
2006-06-09,4.98
2006-06-12,4.99
2006-06-13,4.97
2006-06-14,5.05
2006-06-15,5.10
2006-06-16,5.13
2006-06-19,5.14
2006-06-20,5.15
2006-06-21,5.16
2006-06-22,5.20
2006-06-23,5.23
2006-06-26,5.25
2006-06-27,5.21
2006-06-28,5.25
2006-06-29,5.22
2006-06-30,5.15
2006-07-03,5.15
2006-07-04,
2006-07-05,5.23
2006-07-06,5.19
2006-07-07,5.14
2006-07-10,5.13
2006-07-11,5.10
2006-07-12,5.10
2006-07-13,5.08
2006-07-14,5.07
2006-07-17,5.07
2006-07-18,5.13
2006-07-19,5.06
2006-07-20,5.03
2006-07-21,5.05
2006-07-24,5.05
2006-07-25,5.07
2006-07-26,5.04
2006-07-27,5.07
2006-07-28,5.00
2006-07-31,4.99
2006-08-01,4.99
2006-08-02,4.96
2006-08-03,4.96
2006-08-04,4.91
2006-08-07,4.93
2006-08-08,4.93
2006-08-09,4.92
2006-08-10,4.93
2006-08-11,4.97
2006-08-14,5.00
2006-08-15,4.93
2006-08-16,4.87
2006-08-17,4.87
2006-08-18,4.84
2006-08-21,4.82
2006-08-22,4.82
2006-08-23,4.82
2006-08-24,4.81
2006-08-25,4.79
2006-08-28,4.80
2006-08-29,4.79
2006-08-30,4.76
2006-08-31,4.74
2006-09-01,4.73
2006-09-04,
2006-09-05,4.78
2006-09-06,4.80
2006-09-07,4.80
2006-09-08,4.78
2006-09-11,4.80
2006-09-12,4.78
2006-09-13,4.77
2006-09-14,4.79
2006-09-15,4.80
2006-09-18,4.81
2006-09-19,4.74
2006-09-20,4.73
2006-09-21,4.65
2006-09-22,4.60
2006-09-25,4.56
2006-09-26,4.59
2006-09-27,4.60
2006-09-28,4.63
2006-09-29,4.64
"""

# Real fred.stlouisfed.org/graph/fredgraph.csv?id=DGS2&cosd=2006-06-01&coed=2006-09-30
_DGS2_2006_CSV = """observation_date,DGS2
2006-06-01,5.04
2006-06-02,4.92
2006-06-05,4.99
2006-06-06,4.99
2006-06-07,5.02
2006-06-08,5.01
2006-06-09,5.01
2006-06-12,5.02
2006-06-13,5.02
2006-06-14,5.11
2006-06-15,5.14
2006-06-16,5.16
2006-06-19,5.19
2006-06-20,5.19
2006-06-21,5.20
2006-06-22,5.23
2006-06-23,5.27
2006-06-26,5.27
2006-06-27,5.24
2006-06-28,5.29
2006-06-29,5.21
2006-06-30,5.16
2006-07-03,5.17
2006-07-04,
2006-07-05,5.24
2006-07-06,5.22
2006-07-07,5.17
2006-07-10,5.17
2006-07-11,5.17
2006-07-12,5.17
2006-07-13,5.12
2006-07-14,5.08
2006-07-17,5.12
2006-07-18,5.19
2006-07-19,5.12
2006-07-20,5.06
2006-07-21,5.08
2006-07-24,5.10
2006-07-25,5.11
2006-07-26,5.06
2006-07-27,5.07
2006-07-28,4.98
2006-07-31,4.97
2006-08-01,4.97
2006-08-02,4.97
2006-08-03,4.98
2006-08-04,4.91
2006-08-07,4.96
2006-08-08,4.91
2006-08-09,4.91
2006-08-10,4.93
2006-08-11,4.96
2006-08-14,5.01
2006-08-15,4.94
2006-08-16,4.87
2006-08-17,4.89
2006-08-18,4.87
2006-08-21,4.85
2006-08-22,4.87
2006-08-23,4.87
2006-08-24,4.88
2006-08-25,4.86
2006-08-28,4.88
2006-08-29,4.87
2006-08-30,4.83
2006-08-31,4.79
2006-09-01,4.77
2006-09-04,
2006-09-05,4.80
2006-09-06,4.82
2006-09-07,4.82
2006-09-08,4.80
2006-09-11,4.83
2006-09-12,4.82
2006-09-13,4.80
2006-09-14,4.83
2006-09-15,4.87
2006-09-18,4.88
2006-09-19,4.79
2006-09-20,4.81
2006-09-21,4.71
2006-09-22,4.67
2006-09-25,4.63
2006-09-26,4.68
2006-09-27,4.66
2006-09-28,4.68
2006-09-29,4.71
"""

# Real fred.stlouisfed.org/graph/fredgraph.csv?id=DGS3MO&cosd=2020-03-01&coed=2020-05-31
_DGS3MO_2020_CSV = """observation_date,DGS3MO
2020-03-02,1.13
2020-03-03,0.95
2020-03-04,0.72
2020-03-05,0.62
2020-03-06,0.45
2020-03-09,0.33
2020-03-10,0.44
2020-03-11,0.42
2020-03-12,0.33
2020-03-13,0.28
2020-03-16,0.24
2020-03-17,0.19
2020-03-18,0.02
2020-03-19,0.04
2020-03-20,0.05
2020-03-23,0.02
2020-03-24,0.01
2020-03-25,0.00
2020-03-26,0.00
2020-03-27,0.03
2020-03-30,0.12
2020-03-31,0.11
2020-04-01,0.09
2020-04-02,0.09
2020-04-03,0.10
2020-04-06,0.15
2020-04-07,0.14
2020-04-08,0.22
2020-04-09,0.25
2020-04-10,
2020-04-13,0.26
2020-04-14,0.20
2020-04-15,0.14
2020-04-16,0.14
2020-04-17,0.12
2020-04-20,0.12
2020-04-21,0.11
2020-04-22,0.12
2020-04-23,0.11
2020-04-24,0.12
2020-04-27,0.12
2020-04-28,0.11
2020-04-29,0.10
2020-04-30,0.09
2020-05-01,0.12
2020-05-04,0.13
2020-05-05,0.13
2020-05-06,0.12
2020-05-07,0.11
2020-05-08,0.12
2020-05-11,0.12
2020-05-12,0.13
2020-05-13,0.13
2020-05-14,0.12
2020-05-15,0.12
2020-05-18,0.13
2020-05-19,0.13
2020-05-20,0.12
2020-05-21,0.12
2020-05-22,0.12
2020-05-25,
2020-05-26,0.14
2020-05-27,0.15
2020-05-28,0.15
2020-05-29,0.14
"""


class _MultiSeriesTransport:
    """Routes each GET by its `id` param to a scripted real response --
    `fetch_treasury_yield_curve` makes one GET per tenor, so a single
    fixed-body fake (as `test_french_factors.py` uses) cannot serve a
    multi-tenor fetch."""

    def __init__(self, bodies_by_series_id: dict[str, str], *, status_code: int = 200) -> None:
        self._bodies = bodies_by_series_id
        self._status_code = status_code
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(self, url: str, params: dict[str, str]) -> HttpResponse:
        self.calls.append((url, dict(params)))
        series_id = params["id"]
        if series_id not in self._bodies:
            raise AssertionError(f"unexpected series id requested: {series_id}")
        return HttpResponse(
            status_code=self._status_code, body=self._bodies[series_id].encode("utf-8")
        )


def test_fetches_real_2y_and_10y_data_and_confirms_the_2006_inversion() -> None:
    transport = _MultiSeriesTransport({"DGS10": _DGS10_2006_CSV, "DGS2": _DGS2_2006_CSV})
    result = fetch_treasury_yield_curve(
        transport, start=date(2006, 6, 1), end=date(2006, 9, 30), tenors=("10Y", "2Y")
    )
    by_series_and_date = {(o.series_id, o.observation_at): o.value for o in result.observations}
    ten_year = by_series_and_date[("UST_10Y", date(2006, 8, 25))]
    two_year = by_series_and_date[("UST_2Y", date(2006, 8, 25))]
    assert ten_year == 4.79
    assert two_year == 4.86
    # The real, dated 2-year/10-year inversion that preceded the 2008
    # recession -- computed from the fetched data, not hand-asserted.
    assert ten_year - two_year < 0


def test_fetches_real_3mo_data_and_confirms_the_2020_covid_rate_cut() -> None:
    transport = _MultiSeriesTransport({"DGS3MO": _DGS3MO_2020_CSV})
    result = fetch_treasury_yield_curve(
        transport, start=date(2020, 3, 1), end=date(2020, 5, 31), tenors=("3MO",)
    )
    by_date = {o.observation_at: o.value for o in result.observations}
    assert by_date[date(2020, 3, 25)] == 0.00
    assert by_date[date(2020, 3, 26)] == 0.00


def test_market_holidays_are_derived_from_real_data_not_a_hand_typed_list() -> None:
    """Independence Day 2006, Labor Day 2006 and Good Friday 2020 (a
    bond-market/SIFMA holiday, NOT a federal government one -- a case
    a borrowed federal-holiday list would have gotten wrong) are all
    recovered purely from real published-value gaps."""
    transport = _MultiSeriesTransport({"DGS10": _DGS10_2006_CSV, "DGS2": _DGS2_2006_CSV})
    result = fetch_treasury_yield_curve(
        transport, start=date(2006, 6, 1), end=date(2006, 9, 30), tenors=("10Y", "2Y")
    )
    assert date(2006, 7, 4) in result.market_holidays
    assert date(2006, 9, 4) in result.market_holidays

    transport_2020 = _MultiSeriesTransport({"DGS3MO": _DGS3MO_2020_CSV})
    result_2020 = fetch_treasury_yield_curve(
        transport_2020, start=date(2020, 3, 1), end=date(2020, 5, 31), tenors=("3MO",)
    )
    assert date(2020, 4, 10) in result_2020.market_holidays
    # A real trading weekday the data actually covers must NOT be
    # misclassified as a holiday.
    assert date(2020, 3, 25) not in result_2020.market_holidays


def test_published_at_is_strictly_after_observation_at_per_the_pit_schema() -> None:
    transport = _MultiSeriesTransport({"DGS3MO": _DGS3MO_2020_CSV})
    result = fetch_treasury_yield_curve(
        transport, start=date(2020, 3, 1), end=date(2020, 5, 31), tenors=("3MO",)
    )
    for obs in result.observations:
        assert obs.published_at > obs.observation_at


def test_conventions_record_both_short_and_long_tenor_day_count_rules() -> None:
    conventions = treasury_market_conventions()
    assert "actual/360" in conventions.short_tenor_day_count
    assert "actual/actual" in conventions.long_tenor_day_count
    assert conventions.short_tenor_cutoff_years == 1.0


def test_rejects_an_end_date_before_the_start_date() -> None:
    transport = _MultiSeriesTransport({})
    with pytest.raises(ValueError, match="end must not be before start"):
        fetch_treasury_yield_curve(transport, start=date(2020, 1, 2), end=date(2020, 1, 1))


def test_rejects_an_unknown_tenor() -> None:
    transport = _MultiSeriesTransport({})
    with pytest.raises(ValueError, match="unknown tenor"):
        fetch_treasury_yield_curve(
            transport, start=date(2020, 1, 1), end=date(2020, 1, 2), tenors=("99Y",)
        )


def test_rejects_empty_tenors() -> None:
    transport = _MultiSeriesTransport({})
    with pytest.raises(ValueError, match="tenors must not be empty"):
        fetch_treasury_yield_curve(
            transport, start=date(2020, 1, 1), end=date(2020, 1, 2), tenors=()
        )


def test_rejects_a_non_200_response() -> None:
    transport = _MultiSeriesTransport({"DGS10": _DGS10_2006_CSV}, status_code=503)
    with pytest.raises(TreasuryYieldCurveResponseError, match="503"):
        fetch_treasury_yield_curve(
            transport, start=date(2006, 6, 1), end=date(2006, 9, 30), tenors=("10Y",)
        )


def test_rejects_an_unrecognizable_response_body() -> None:
    transport = _MultiSeriesTransport({"DGS10": "not,a,fred,csv\n1,2,3,4\n"})
    with pytest.raises(TreasuryYieldCurveResponseError, match="DGS10"):
        fetch_treasury_yield_curve(
            transport, start=date(2006, 6, 1), end=date(2006, 9, 30), tenors=("10Y",)
        )


def test_all_eleven_tenors_are_declared_and_requestable() -> None:
    assert len(ALL_TENORS) == 11
    assert {"1MO", "3MO", "6MO", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"} == set(
        ALL_TENORS
    )


def test_source_url_and_license_constants_are_declared_for_the_inventory() -> None:
    assert TREASURY_YIELD_CURVE_SOURCE_URL == "https://fred.stlouisfed.org/graph/fredgraph.csv"
    assert "Public Domain" in TREASURY_YIELD_CURVE_SOURCE_LICENSE
