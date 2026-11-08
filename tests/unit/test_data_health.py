"""`measure_staleness` tests, plus a demonstration that "failed ingest
counts" (OPS-06's other half) is already covered by reusing
`evidence.inference_metrics.run_inference_benchmark` against a real
connector -- no second, duplicate failure-tracking function exists.
"""

from datetime import date

import pytest

from prometheus.data_ingestion.french_factors import fetch_french_factors
from prometheus.data_ingestion.transport import HttpResponse
from prometheus.econosim.pit import MacroObservation
from prometheus.evidence.data_health import StalenessReport, measure_staleness
from prometheus.evidence.inference_metrics import run_inference_benchmark


def _obs(series_id: str, observation_at: date) -> MacroObservation:
    return MacroObservation(
        series_id=series_id,
        observation_at=observation_at,
        published_at=observation_at,
        value=1.0,
    )


def test_rejects_an_empty_series_id() -> None:
    with pytest.raises(ValueError, match="series_id"):
        measure_staleness("", [_obs("X", date(2026, 1, 1))], date(2026, 1, 1), max_age_days=5)


def test_rejects_a_negative_max_age_days() -> None:
    with pytest.raises(ValueError, match="max_age_days"):
        measure_staleness(
            "X", [_obs("X", date(2026, 1, 1))], date(2026, 1, 1), max_age_days=-1
        )


def test_rejects_a_series_id_with_no_matching_observations() -> None:
    with pytest.raises(ValueError, match="X"):
        measure_staleness(
            "X", [_obs("Y", date(2026, 1, 1))], date(2026, 1, 1), max_age_days=5
        )


def test_rejects_an_as_of_before_the_latest_observation() -> None:
    with pytest.raises(ValueError, match="as_of"):
        measure_staleness(
            "X", [_obs("X", date(2026, 1, 10))], date(2026, 1, 1), max_age_days=5
        )


def test_a_series_exactly_at_the_threshold_is_not_yet_stale() -> None:
    report = measure_staleness(
        "X", [_obs("X", date(2026, 1, 1))], date(2026, 1, 6), max_age_days=5
    )
    assert report.age_days == 5
    assert report.is_stale is False


def test_a_series_one_day_past_the_threshold_is_stale() -> None:
    report = measure_staleness(
        "X", [_obs("X", date(2026, 1, 1))], date(2026, 1, 7), max_age_days=5
    )
    assert report.age_days == 6
    assert report.is_stale is True


def test_the_most_recent_of_several_vintages_is_used() -> None:
    observations = [
        _obs("X", date(2026, 1, 1)),
        _obs("X", date(2026, 3, 1)),
        _obs("X", date(2026, 2, 1)),
    ]
    report = measure_staleness("X", observations, date(2026, 3, 1), max_age_days=0)
    assert report.latest_observation_at == date(2026, 3, 1)


def test_unrelated_series_ids_in_the_same_sequence_are_ignored() -> None:
    observations = [_obs("X", date(2026, 1, 1)), _obs("Y", date(2026, 6, 1))]
    report = measure_staleness("X", observations, date(2026, 1, 1), max_age_days=0)
    assert report.latest_observation_at == date(2026, 1, 1)


def test_report_is_constructible_directly() -> None:
    report = StalenessReport(
        series_id="X", latest_observation_at=date(2026, 1, 1), as_of=date(2026, 1, 1),
        age_days=0, is_stale=False,
    )
    assert report.is_stale is False


class _StaticTransport:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def get(self, url: str, params: dict[str, str]) -> HttpResponse:
        return HttpResponse(status_code=200, body=self.body)


def _real_french_factors_zip() -> bytes:
    import base64

    from tests.unit.test_french_factors import _REAL_FRENCH_FACTORS_ZIP_B64

    return base64.b64decode(_REAL_FRENCH_FACTORS_ZIP_B64)


def test_a_real_alert_exercise_detects_a_stale_critical_series() -> None:
    """The acceptance criterion's own 'alert exercise': fetch the REAL
    captured Kenneth French archive, then confirm the staleness alert
    fires when `as_of` is far past the latest real observation, and
    does NOT fire right at that observation's own date."""
    result = fetch_french_factors(_StaticTransport(_real_french_factors_zip()))

    fresh = measure_staleness(
        "FF3_Mkt-RF", result.observations, date(2026, 9, 30), max_age_days=45
    )
    assert fresh.is_stale is False

    stale = measure_staleness(
        "FF3_Mkt-RF", result.observations, date(2027, 6, 30), max_age_days=45
    )
    assert stale.is_stale is True


class _FlakyThenRealTransport:
    """Fails with HTTP 503 the first `fail_times` calls, then returns
    the real captured archive -- a genuinely flaky real connector, not
    a fabricated failure count."""

    def __init__(self, fail_times: int, body: bytes) -> None:
        self.fail_times = fail_times
        self.body = body
        self.calls = 0

    def get(self, url: str, params: dict[str, str]) -> HttpResponse:
        self.calls += 1
        if self.calls <= self.fail_times:
            return HttpResponse(status_code=503, body=b"")
        return HttpResponse(status_code=200, body=self.body)


def test_failed_ingest_counts_are_already_covered_by_run_inference_benchmark() -> None:
    """OPS-06's second half ('failed ingest counts') needs no new
    function: wrapping a real connector call in the EXISTING
    `run_inference_benchmark` already produces a real failure count,
    grounded against a genuinely flaky transport, not a toy lambda."""
    transport = _FlakyThenRealTransport(fail_times=3, body=_real_french_factors_zip())

    def attempt() -> None:
        fetch_french_factors(transport)

    report = run_inference_benchmark("french_factors_ingest", "data_ingestion.french_factors",
                                      attempt, 10)
    assert report.n_failures == 3
    assert report.failure_rate == pytest.approx(0.3)
