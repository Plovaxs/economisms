from datetime import date

from prometheus.econosim.leakage_linter import (
    lint_future_timestamp_usage,
    lint_pit_store_usage,
)
from prometheus.econosim.pit import MacroObservation, PointInTimeStore


def test_lint_future_timestamp_usage_is_clean_when_nothing_is_used_early() -> None:
    usages = [
        ("CPI@2026-09", date(2026, 10, 10), date(2026, 10, 15)),
        ("GDP@2026-Q3", date(2026, 10, 1), date(2026, 10, 1)),  # exactly on the boundary: OK
    ]
    report = lint_future_timestamp_usage(usages)
    assert report.clean
    assert report.n_checked == 2
    assert report.violations == ()


def test_lint_future_timestamp_usage_flags_a_genuine_future_timestamp() -> None:
    usages = [
        ("CPI@2026-09", date(2026, 10, 10), date(2026, 10, 15)),  # fine
        ("GDP@2026-Q3", date(2026, 11, 1), date(2026, 10, 15)),  # leak: used 17 days early
    ]
    report = lint_future_timestamp_usage(usages)
    assert not report.clean
    assert report.n_checked == 2
    assert len(report.violations) == 1
    assert report.violations[0].feature_id == "GDP@2026-Q3"
    assert report.violations[0].decision_time == date(2026, 10, 15)
    assert "before it existed" in str(report.violations[0])


def test_lint_future_timestamp_usage_flags_every_violation_not_just_the_first() -> None:
    usages = [
        ("A", date(2026, 2, 1), date(2026, 1, 1)),
        ("B", date(2026, 3, 1), date(2026, 1, 1)),
        ("C", date(2025, 1, 1), date(2026, 1, 1)),  # fine
    ]
    report = lint_future_timestamp_usage(usages)
    assert len(report.violations) == 2
    assert {v.feature_id for v in report.violations} == {"A", "B"}


def test_lint_pit_store_usage_is_clean_for_a_legitimately_eligible_request() -> None:
    store = PointInTimeStore()
    store.record(
        MacroObservation(
            series_id="CPI", observation_at=date(2026, 9, 1), published_at=date(2026, 10, 10),
            value=3.1,
        )
    )
    report = lint_pit_store_usage(store, [("CPI", date(2026, 9, 1), date(2026, 10, 15))])
    assert report.clean


def test_lint_pit_store_usage_flags_a_decision_time_before_publication() -> None:
    """The same future-data scenario `pit.py`'s own
    `test_as_of_returns_none_before_publication` exercises directly on
    `as_of`, here checked through the linter's batch-audit interface."""
    store = PointInTimeStore()
    store.record(
        MacroObservation(
            series_id="CPI", observation_at=date(2026, 9, 1), published_at=date(2026, 10, 15),
            value=3.1,
        )
    )
    report = lint_pit_store_usage(store, [("CPI", date(2026, 9, 1), date(2026, 10, 14))])
    assert not report.clean
    assert report.violations[0].feature_id == "CPI@2026-09-01"
    assert "CPI" in report.violations[0].detail


def test_lint_pit_store_usage_flags_a_never_recorded_series() -> None:
    store = PointInTimeStore()
    report = lint_pit_store_usage(store, [("UNEMPLOYMENT", date(2026, 1, 1), date(2026, 2, 1))])
    assert not report.clean


def test_lint_pit_store_usage_respects_asof_eligible_at_ingestion_lag() -> None:
    """Published is not enough on its own -- a request made after
    publication but before this system's own ingestion-lag cutoff
    (`asof_eligible_at`) must still be flagged, matching
    `MacroObservation.effective_eligible_at`'s own convention."""
    store = PointInTimeStore()
    store.record(
        MacroObservation(
            series_id="CPI",
            observation_at=date(2026, 9, 1),
            published_at=date(2026, 10, 10),
            asof_eligible_at=date(2026, 10, 20),
            value=3.1,
        )
    )
    report = lint_pit_store_usage(store, [("CPI", date(2026, 9, 1), date(2026, 10, 15))])
    assert not report.clean  # published, but not yet ingestion-eligible

    report_ok = lint_pit_store_usage(store, [("CPI", date(2026, 9, 1), date(2026, 10, 21))])
    assert report_ok.clean


def test_lint_pit_store_usage_mixes_clean_and_leaked_requests_in_one_batch() -> None:
    store = PointInTimeStore()
    store.record(
        MacroObservation(
            series_id="CPI", observation_at=date(2026, 9, 1), published_at=date(2026, 10, 10),
            value=3.1,
        )
    )
    store.record(
        MacroObservation(
            series_id="GDP", observation_at=date(2026, 7, 1), published_at=date(2026, 10, 1),
            value=2.0,
        )
    )
    report = lint_pit_store_usage(
        store,
        [
            ("CPI", date(2026, 9, 1), date(2026, 10, 15)),  # clean
            ("GDP", date(2026, 7, 1), date(2026, 9, 1)),  # leak: used before publication
        ],
    )
    assert report.n_checked == 2
    assert len(report.violations) == 1
    assert report.violations[0].feature_id == "GDP@2026-07-01"
