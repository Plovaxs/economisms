import pytest

from prometheus.evidence.numerical_event_monitor import monitor_call
from prometheus.evidence.severity_matrix import (
    SeverityMatrix,
    SeverityMatrixEntry,
    UnknownIncidentCategoryError,
)
from prometheus.jobs.store import ERROR_CODES


def test_entry_rejects_an_empty_category() -> None:
    with pytest.raises(ValueError, match="category"):
        SeverityMatrixEntry(category="", severity="P0", owner="a", approved_by="b")


def test_entry_rejects_an_empty_owner() -> None:
    with pytest.raises(ValueError, match="owner"):
        SeverityMatrixEntry(category="x", severity="P0", owner="", approved_by="b")


def test_entry_rejects_an_empty_approved_by() -> None:
    with pytest.raises(ValueError, match="approved_by"):
        SeverityMatrixEntry(category="x", severity="P0", owner="a", approved_by="")


def test_matrix_rejects_duplicate_categories() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        SeverityMatrix(
            entries=(
                SeverityMatrixEntry("x", "P0", "a", "lead"),
                SeverityMatrixEntry("x", "P1", "b", "lead"),
            )
        )


def test_lookup_raises_for_an_unconfigured_category() -> None:
    matrix = SeverityMatrix(entries=())
    with pytest.raises(UnknownIncidentCategoryError, match="worker_failed"):
        matrix.lookup("worker_failed")


# A real severity matrix covering REAL incident categories this
# repository's own job queue (jobs.store.ERROR_CODES) and numerical
# event monitor (evidence.numerical_event_monitor's EventKind values)
# already produce -- not invented category names. "cpu_timeout" is
# DELIBERATELY left out, to confirm the raise fires on an actual real
# category gap, not a typo'd string.
_REAL_MATRIX = SeverityMatrix(
    entries=(
        SeverityMatrixEntry("worker_failed", "P1", "platform-oncall", "risk-lead"),
        SeverityMatrixEntry("infrastructure_error", "P0", "platform-oncall", "risk-lead"),
        SeverityMatrixEntry("model_error", "P1", "quant-oncall", "risk-lead"),
        SeverityMatrixEntry("execution_rejected", "P2", "platform-oncall", "risk-lead"),
        SeverityMatrixEntry("solver_failure", "P0", "quant-oncall", "risk-lead"),
        SeverityMatrixEntry("non_finite_result", "P0", "quant-oncall", "risk-lead"),
        SeverityMatrixEntry("pricing_deviation", "P0", "risk-oncall", "risk-lead"),
    )
)


def test_real_job_error_codes_resolve_to_a_configured_severity_and_owner() -> None:
    """Grounded against REAL `jobs.store.ERROR_CODES` members, not
    synthetic category names."""
    assert "worker_failed" in ERROR_CODES  # sanity: a real error code
    entry = _REAL_MATRIX.lookup("worker_failed")
    assert entry.severity == "P1"
    assert entry.owner == "platform-oncall"

    infra_entry = _REAL_MATRIX.lookup("infrastructure_error")
    assert infra_entry.severity == "P0"


def test_a_real_solver_failure_event_kind_resolves_to_a_configured_severity() -> None:
    """Grounded against a REAL `evidence.numerical_event_monitor` event
    kind produced by actually monitoring a failing call, not a
    hand-typed string."""

    def failing() -> None:
        raise RuntimeError("the solver diverged")

    event = monitor_call(failing, owner="quant-oncall")
    assert event is not None
    entry = _REAL_MATRIX.lookup(event.kind)
    assert entry.severity == "P0"
    assert entry.owner == "quant-oncall"


def test_a_real_but_unconfigured_error_code_raises_a_genuine_gap() -> None:
    """The discriminating half: `cpu_timeout` IS a real member of
    `jobs.store.ERROR_CODES`, deliberately left out of `_REAL_MATRIX`
    above -- confirming `lookup` catches an actual, real coverage gap,
    not merely a nonexistent/typo'd category."""
    assert "cpu_timeout" in ERROR_CODES  # sanity: this really is a real code
    with pytest.raises(UnknownIncidentCategoryError, match="cpu_timeout"):
        _REAL_MATRIX.lookup("cpu_timeout")


def test_every_real_error_code_can_be_classified_or_explicitly_flagged_as_a_gap() -> None:
    """A real coverage sweep: every actual `ERROR_CODES` member either
    resolves to a configured entry, or is confirmed (not assumed) to
    be an intentional gap in `_REAL_MATRIX` for this test's purposes."""
    configured = {entry.category for entry in _REAL_MATRIX.entries}
    deliberately_unconfigured_for_this_test = ERROR_CODES - configured
    assert deliberately_unconfigured_for_this_test == {
        "invalid_simulation", "environment_mismatch", "wall_timeout", "lease_expired",
        "artifact_invalid", "cpu_timeout", "restore_interrupted",
    }
