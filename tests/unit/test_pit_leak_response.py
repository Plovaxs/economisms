from datetime import date

import pytest

from prometheus.econosim.pit import MacroObservation, PointInTimeStore
from prometheus.evidence.pit_leak_response import (
    DataAccess,
    RevokedRun,
    detect_leak,
    recompute,
    revoke_run,
    trace_affected_runs,
)

SERIES = "GDP_NOWCAST"
OBSERVATION_AT = date(2026, 3, 31)  # Q1 2026
EARLY_PUBLISHED_AT = date(2026, 4, 15)  # first nowcast estimate
REVISION_PUBLISHED_AT = date(2026, 6, 1)  # later, revised estimate


def _store_with_a_real_revision() -> PointInTimeStore:
    """A real two-vintage series: an early nowcast (100.0), later
    revised (105.0) -- the exact shape a point-in-time leak exploits
    (using the revised value before it was actually published)."""
    store = PointInTimeStore()
    store.record(
        MacroObservation(
            series_id=SERIES, observation_at=OBSERVATION_AT,
            published_at=EARLY_PUBLISHED_AT, value=100.0, revision_id="r0",
        )
    )
    store.record(
        MacroObservation(
            series_id=SERIES, observation_at=OBSERVATION_AT,
            published_at=REVISION_PUBLISHED_AT, value=105.0, revision_id="r1",
        )
    )
    return store


def test_a_run_using_the_correctly_eligible_value_has_no_leak() -> None:
    store = _store_with_a_real_revision()
    access = DataAccess(
        run_id="run-clean", series_id=SERIES, observation_at=OBSERVATION_AT,
        as_of=date(2026, 4, 20), value_used=100.0,
    )
    assert detect_leak(access, store) is None


def test_a_run_using_the_not_yet_published_revised_value_is_a_genuine_leak() -> None:
    """The discriminating case: `as_of` is BEFORE the revision was
    published, yet the run claims it used the revised (105.0) value --
    a real point-in-time leak, confirmed against the real store."""
    store = _store_with_a_real_revision()
    access = DataAccess(
        run_id="run-leaky", series_id=SERIES, observation_at=OBSERVATION_AT,
        as_of=date(2026, 4, 20), value_used=105.0,
    )
    finding = detect_leak(access, store)
    assert finding is not None
    assert finding.correct_value == 100.0
    assert "used 105.0" in finding.reason


def test_a_run_using_any_value_before_anything_was_eligible_is_a_leak() -> None:
    store = _store_with_a_real_revision()
    access = DataAccess(
        run_id="run-too-early", series_id=SERIES, observation_at=OBSERVATION_AT,
        as_of=date(2026, 4, 1), value_used=100.0,
    )
    finding = detect_leak(access, store)
    assert finding is not None
    assert finding.correct_value is None
    assert "nothing was eligible" in finding.reason


def test_trace_affected_runs_identifies_exactly_the_leaky_run_ids() -> None:
    store = _store_with_a_real_revision()
    accesses = [
        DataAccess("run-clean", SERIES, OBSERVATION_AT, date(2026, 4, 20), 100.0),
        DataAccess("run-leaky", SERIES, OBSERVATION_AT, date(2026, 4, 20), 105.0),
        DataAccess("run-also-clean", SERIES, OBSERVATION_AT, date(2026, 7, 1), 105.0),
    ]
    affected = trace_affected_runs(accesses, store)
    assert affected == frozenset({"run-leaky"})


def test_revoke_run_rejects_an_empty_reason() -> None:
    with pytest.raises(ValueError, match="reason"):
        RevokedRun(run_id="r", reason="", owner="o", revoked_at=date(2026, 1, 1))


def test_revoke_run_rejects_an_empty_owner() -> None:
    with pytest.raises(ValueError, match="owner"):
        RevokedRun(run_id="r", reason="leak", owner="", revoked_at=date(2026, 1, 1))


def test_revoke_run_constructs_a_real_revocation_record() -> None:
    revoked = revoke_run(
        "run-leaky", "point-in-time leak detected", owner="risk-lead",
        revoked_at=date(2026, 4, 21),
    )
    assert revoked.run_id == "run-leaky"
    assert revoked.owner == "risk-lead"


def test_recompute_uses_the_correct_value_producing_a_different_result() -> None:
    """Confirms recomputation genuinely changes the outcome: the
    leaked run's own (wrong) result would have been 105.0 * 2 = 210.0,
    but recompute uses the CORRECT 100.0, giving 200.0."""
    store = _store_with_a_real_revision()
    leaked_access = DataAccess("run-leaky", SERIES, OBSERVATION_AT, date(2026, 4, 20), 105.0)
    finding = detect_leak(leaked_access, store)
    assert finding is not None

    leaked_result = leaked_access.value_used * 2
    recomputed_result = recompute(finding, lambda value: value * 2)

    assert leaked_result == pytest.approx(210.0)
    assert recomputed_result == pytest.approx(200.0)
    assert recomputed_result != leaked_result


def test_recompute_raises_when_nothing_was_ever_eligible() -> None:
    store = _store_with_a_real_revision()
    access = DataAccess("run-too-early", SERIES, OBSERVATION_AT, date(2026, 4, 1), 100.0)
    finding = detect_leak(access, store)
    assert finding is not None
    with pytest.raises(ValueError, match="no eligible value"):
        recompute(finding, lambda value: value)
