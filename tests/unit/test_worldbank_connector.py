"""Tests use REAL World Bank API responses, captured live (4 pages, a
genuine `country=USA;IDN;CHN` / `indicator=NY.GDP.MKTP.KD.ZG` /
`date=2015:2020` query) during this connector's own pre-implementation
verification -- not hand-typed fake JSON -- embedded here as string
literals so the test suite stays hermetic (no live network call during
`pytest`) while still exercising the parser against data it did not
invent. Edge cases the real capture happened not to contain (a missing
value, an empty result, a malformed response) are covered by separate,
explicitly hand-constructed fixtures below.
"""

import hashlib
import json
from datetime import date

import pytest

from prometheus.data_ingestion.transport import HttpResponse
from prometheus.data_ingestion.worldbank import (
    WorldBankResponseError,
    fetch_world_bank_indicator,
)
from prometheus.econosim.pit import FutureDataError, PointInTimeStore, require_eligible

_REAL_PAGE_1 = b'[{"page":1,"pages":4,"per_page":5,"total":18,"sourceid":"2","lastupdated":"2026-10-08"},[{"indicator":{"id":"NY.GDP.MKTP.KD.ZG","value":"GDP growth (annual %)"},"country":{"id":"CN","value":"China"},"countryiso3code":"CHN","date":"2020","value":2.33950385203023,"unit":"","obs_status":"","decimal":1},{"indicator":{"id":"NY.GDP.MKTP.KD.ZG","value":"GDP growth (annual %)"},"country":{"id":"CN","value":"China"},"countryiso3code":"CHN","date":"2019","value":6.06737806333672,"unit":"","obs_status":"","decimal":1},{"indicator":{"id":"NY.GDP.MKTP.KD.ZG","value":"GDP growth (annual %)"},"country":{"id":"CN","value":"China"},"countryiso3code":"CHN","date":"2018","value":6.757806142324,"unit":"","obs_status":"","decimal":1},{"indicator":{"id":"NY.GDP.MKTP.KD.ZG","value":"GDP growth (annual %)"},"country":{"id":"CN","value":"China"},"countryiso3code":"CHN","date":"2017","value":6.89123916636191,"unit":"","obs_status":"","decimal":1},{"indicator":{"id":"NY.GDP.MKTP.KD.ZG","value":"GDP growth (annual %)"},"country":{"id":"CN","value":"China"},"countryiso3code":"CHN","date":"2016","value":6.7736886867727,"unit":"","obs_status":"","decimal":1}]]'  # noqa: E501

_REAL_PAGE_2 = b'[{"page":2,"pages":4,"per_page":5,"total":18,"sourceid":"2","lastupdated":"2026-10-08"},[{"indicator":{"id":"NY.GDP.MKTP.KD.ZG","value":"GDP growth (annual %)"},"country":{"id":"CN","value":"China"},"countryiso3code":"CHN","date":"2015","value":6.98162255562367,"unit":"","obs_status":"","decimal":1},{"indicator":{"id":"NY.GDP.MKTP.KD.ZG","value":"GDP growth (annual %)"},"country":{"id":"ID","value":"Indonesia"},"countryiso3code":"IDN","date":"2020","value":-2.06551182934165,"unit":"","obs_status":"","decimal":1},{"indicator":{"id":"NY.GDP.MKTP.KD.ZG","value":"GDP growth (annual %)"},"country":{"id":"ID","value":"Indonesia"},"countryiso3code":"IDN","date":"2019","value":5.01928768046282,"unit":"","obs_status":"","decimal":1},{"indicator":{"id":"NY.GDP.MKTP.KD.ZG","value":"GDP growth (annual %)"},"country":{"id":"ID","value":"Indonesia"},"countryiso3code":"IDN","date":"2018","value":5.17429153955024,"unit":"","obs_status":"","decimal":1},{"indicator":{"id":"NY.GDP.MKTP.KD.ZG","value":"GDP growth (annual %)"},"country":{"id":"ID","value":"Indonesia"},"countryiso3code":"IDN","date":"2017","value":5.06978590134916,"unit":"","obs_status":"","decimal":1}]]'  # noqa: E501

_REAL_PAGE_3 = b'[{"page":3,"pages":4,"per_page":5,"total":18,"sourceid":"2","lastupdated":"2026-10-08"},[{"indicator":{"id":"NY.GDP.MKTP.KD.ZG","value":"GDP growth (annual %)"},"country":{"id":"ID","value":"Indonesia"},"countryiso3code":"IDN","date":"2016","value":5.03306918280177,"unit":"","obs_status":"","decimal":1},{"indicator":{"id":"NY.GDP.MKTP.KD.ZG","value":"GDP growth (annual %)"},"country":{"id":"ID","value":"Indonesia"},"countryiso3code":"IDN","date":"2015","value":4.87632230022123,"unit":"","obs_status":"","decimal":1},{"indicator":{"id":"NY.GDP.MKTP.KD.ZG","value":"GDP growth (annual %)"},"country":{"id":"US","value":"United States"},"countryiso3code":"USA","date":"2020","value":-2.081375977796,"unit":"","obs_status":"","decimal":1},{"indicator":{"id":"NY.GDP.MKTP.KD.ZG","value":"GDP growth (annual %)"},"country":{"id":"US","value":"United States"},"countryiso3code":"USA","date":"2019","value":2.58382533052225,"unit":"","obs_status":"","decimal":1},{"indicator":{"id":"NY.GDP.MKTP.KD.ZG","value":"GDP growth (annual %)"},"country":{"id":"US","value":"United States"},"countryiso3code":"USA","date":"2018","value":2.96650506701943,"unit":"","obs_status":"","decimal":1}]]'  # noqa: E501

_REAL_PAGE_4 = b'[{"page":4,"pages":4,"per_page":5,"total":18,"sourceid":"2","lastupdated":"2026-10-08"},[{"indicator":{"id":"NY.GDP.MKTP.KD.ZG","value":"GDP growth (annual %)"},"country":{"id":"US","value":"United States"},"countryiso3code":"USA","date":"2017","value":2.45762230126449,"unit":"","obs_status":"","decimal":1},{"indicator":{"id":"NY.GDP.MKTP.KD.ZG","value":"GDP growth (annual %)"},"country":{"id":"US","value":"United States"},"countryiso3code":"USA","date":"2016","value":1.81945147909089,"unit":"","obs_status":"","decimal":1},{"indicator":{"id":"NY.GDP.MKTP.KD.ZG","value":"GDP growth (annual %)"},"country":{"id":"US","value":"United States"},"countryiso3code":"USA","date":"2015","value":2.94555045227337,"unit":"","obs_status":"","decimal":1}]]'  # noqa: E501

_REAL_PAGES = [_REAL_PAGE_1, _REAL_PAGE_2, _REAL_PAGE_3, _REAL_PAGE_4]


class _ScriptedTransport:
    """Returns one canned `HttpResponse` per call, in order; records
    every (url, params) it was called with for assertions."""

    def __init__(self, bodies: list[bytes]) -> None:
        self._bodies = list(bodies)
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(self, url: str, params: dict[str, str]) -> HttpResponse:
        self.calls.append((url, dict(params)))
        body = self._bodies.pop(0)
        return HttpResponse(status_code=200, body=body)


class _ConstantTransport:
    """Always returns the same body -- used to test the pagination
    safety cap, where the loop must eventually give up rather than spin
    forever."""

    def __init__(self, body: bytes) -> None:
        self.body = body
        self.call_count = 0

    def get(self, url: str, params: dict[str, str]) -> HttpResponse:
        self.call_count += 1
        return HttpResponse(status_code=200, body=self.body)


def test_rejects_invalid_inputs() -> None:
    transport = _ScriptedTransport([])
    with pytest.raises(ValueError):
        fetch_world_bank_indicator(transport, [], "NY.GDP.MKTP.KD.ZG")
    with pytest.raises(ValueError):
        fetch_world_bank_indicator(transport, ["USA"], "")
    with pytest.raises(ValueError):
        fetch_world_bank_indicator(transport, ["USA"], "NY.GDP.MKTP.KD.ZG", per_page=0)


def test_parses_all_pages_of_a_real_captured_response() -> None:
    transport = _ScriptedTransport(_REAL_PAGES)
    result = fetch_world_bank_indicator(
        transport, ["USA", "IDN", "CHN"], "NY.GDP.MKTP.KD.ZG", per_page=5, date_range="2015:2020"
    )

    assert result.pages_fetched == 4
    assert len(result.observations) == 18  # 3 countries x 6 years, no gaps in this range
    assert len(transport.calls) == 4
    for _url, params in transport.calls:
        assert params["format"] == "json"
        assert params["date"] == "2015:2020"

    expected_hash = hashlib.sha256(b"".join(_REAL_PAGES)).hexdigest()
    assert result.raw_hash == expected_hash
    assert all(obs.raw_hash == expected_hash for obs in result.observations)

    china_2020 = next(
        obs
        for obs in result.observations
        if obs.series_id == "NY.GDP.MKTP.KD.ZG:CHN" and obs.observation_at == date(2020, 12, 31)
    )
    assert china_2020.value == pytest.approx(2.33950385203023)
    assert china_2020.published_at == date(2026, 10, 8)
    assert china_2020.frequency == "A"
    assert china_2020.source_license == "CC-BY-4.0 (World Bank Open Data)"


def test_observations_feed_the_point_in_time_store_correctly() -> None:
    """A real integration check, not just a parsing check: the fetched
    observations must behave correctly once recorded into
    `econosim.pit.PointInTimeStore` -- ineligible before `published_at`,
    eligible on and after it."""
    transport = _ScriptedTransport(_REAL_PAGES)
    result = fetch_world_bank_indicator(transport, ["USA", "IDN", "CHN"], "NY.GDP.MKTP.KD.ZG")

    store = PointInTimeStore()
    for obs in result.observations:
        store.record(obs)

    sample = result.observations[0]
    with pytest.raises(FutureDataError):
        require_eligible(store, sample.series_id, sample.observation_at, date(2026, 1, 1))
    recovered = require_eligible(store, sample.series_id, sample.observation_at, date(2026, 11, 4))
    assert recovered == sample


def test_rows_with_a_null_value_are_skipped_not_fabricated() -> None:
    body = json.dumps(
        [
            {"page": 1, "pages": 1, "per_page": 10, "total": 2, "lastupdated": "2026-01-01"},
            [
                {"countryiso3code": "USA", "date": "2020", "value": 1.5},
                {"countryiso3code": "USA", "date": "2021", "value": None},
            ],
        ]
    ).encode()
    transport = _ScriptedTransport([body])
    result = fetch_world_bank_indicator(transport, ["USA"], "X")
    assert len(result.observations) == 1
    assert result.observations[0].observation_at == date(2020, 12, 31)


def test_null_rows_field_means_zero_observations_not_an_error() -> None:
    body = json.dumps(
        [{"page": 1, "pages": 1, "per_page": 10, "total": 0, "lastupdated": "2026-01-01"}, None]
    ).encode()
    transport = _ScriptedTransport([body])
    result = fetch_world_bank_indicator(transport, ["USA"], "NONEXISTENT.INDICATOR")
    assert result.observations == ()
    assert result.pages_fetched == 1


def test_malformed_top_level_shape_raises() -> None:
    body = json.dumps({"not": "a list of two things"}).encode()
    transport = _ScriptedTransport([body])
    with pytest.raises(WorldBankResponseError):
        fetch_world_bank_indicator(transport, ["USA"], "X")


def test_invalid_json_raises() -> None:
    transport = _ScriptedTransport([b"not json at all{{{"])
    with pytest.raises(WorldBankResponseError):
        fetch_world_bank_indicator(transport, ["USA"], "X")


def test_missing_lastupdated_raises() -> None:
    body = json.dumps([{"page": 1, "pages": 1, "per_page": 10, "total": 0}, []]).encode()
    transport = _ScriptedTransport([body])
    with pytest.raises(WorldBankResponseError, match="lastupdated"):
        fetch_world_bank_indicator(transport, ["USA"], "X")


def test_pagination_safety_cap_prevents_an_infinite_loop() -> None:
    """A response that always claims there are far more pages than any
    sane query would have must not spin the pagination loop forever --
    the safety cap raises instead."""
    metadata = {
        "page": 1, "pages": 1_000_000, "per_page": 10, "total": 0, "lastupdated": "2026-01-01"
    }
    body = json.dumps([metadata, []]).encode()
    transport = _ConstantTransport(body)
    with pytest.raises(WorldBankResponseError, match="safety cap"):
        fetch_world_bank_indicator(transport, ["USA"], "X")
