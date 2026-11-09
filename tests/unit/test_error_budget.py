import pytest

from prometheus.evidence.error_budget import evaluate_error_budget, record_error_budget_action
from prometheus.evidence.security_scan import evaluate_release_gate
from prometheus.evidence.slo_definitions import ServiceLevelObjective
from prometheus.experiments.latency_benchmark import LoadReport, build_load_report

_SLO = ServiceLevelObjective(
    service_name="metadata-api",
    sli_description="p95 latency for GET /v1/jobs",
    endpoint="GET /v1/jobs",
    target_p95_seconds=0.5,
    workload_assumption="concurrency 8, read-heavy",
    approved_by="platform-lead",
)


def _report(latency_seconds: float) -> LoadReport:
    return build_load_report(
        "GET /v1/jobs", {"GET /v1/jobs": 20}, concurrency=8,
        latencies_seconds=[latency_seconds] * 20,
    )


def test_evaluate_error_budget_rejects_an_empty_reports_sequence() -> None:
    with pytest.raises(ValueError, match="reports"):
        evaluate_error_budget(_SLO, [], max_allowed_breach_rate=0.1)


def test_evaluate_error_budget_rejects_an_out_of_range_breach_rate() -> None:
    with pytest.raises(ValueError, match="max_allowed_breach_rate"):
        evaluate_error_budget(_SLO, [_report(0.1)], max_allowed_breach_rate=1.5)


def test_a_window_of_all_passing_reports_never_exhausts_the_budget() -> None:
    reports = [_report(0.1) for _ in range(10)]
    status = evaluate_error_budget(_SLO, reports, max_allowed_breach_rate=0.0)
    assert status.n_breaches == 0
    assert status.budget_exhausted is False


def test_a_real_mixed_window_counts_breaches_exactly() -> None:
    """8 reports meet the real SLO (p95 0.1s < 0.5s target), 2 real
    reports breach it (p95 0.9s > 0.5s target) -- an exact, known
    breach rate of 0.2, not an estimate."""
    reports = [_report(0.1) for _ in range(8)] + [_report(0.9) for _ in range(2)]
    status = evaluate_error_budget(_SLO, reports, max_allowed_breach_rate=0.1)
    assert status.n_measurements == 10
    assert status.n_breaches == 2
    assert status.breach_rate == pytest.approx(0.2)
    assert status.budget_exhausted is True


def test_the_same_breach_rate_stays_within_a_looser_budget() -> None:
    reports = [_report(0.1) for _ in range(8)] + [_report(0.9) for _ in range(2)]
    status = evaluate_error_budget(_SLO, reports, max_allowed_breach_rate=0.3)
    assert status.budget_exhausted is False


def test_record_error_budget_action_rejects_an_empty_owner() -> None:
    reports = [_report(0.9) for _ in range(5)]
    status = evaluate_error_budget(_SLO, reports, max_allowed_breach_rate=0.0)
    with pytest.raises(ValueError, match="owner"):
        record_error_budget_action(status, owner="")


def test_record_error_budget_action_is_none_when_the_budget_is_not_exhausted() -> None:
    reports = [_report(0.1) for _ in range(10)]
    status = evaluate_error_budget(_SLO, reports, max_allowed_breach_rate=0.1)
    assert record_error_budget_action(status, owner="platform-oncall") is None


def test_a_real_budget_breach_actually_blocks_the_existing_release_gate() -> None:
    """The acceptance criterion's own 'triggers release freeze': a
    real exhausted error budget produces a finding that, fed into the
    EXISTING `evaluate_release_gate` (CIQ-05, the same gate DAT-13's
    license_scan already composes through), genuinely blocks release."""
    reports = [_report(0.1) for _ in range(8)] + [_report(0.9) for _ in range(2)]
    status = evaluate_error_budget(_SLO, reports, max_allowed_breach_rate=0.1)
    finding = record_error_budget_action(status, owner="platform-oncall")
    assert finding is not None

    decision = evaluate_release_gate([finding])
    assert decision.blocked is True
    assert decision.unapproved_findings == (finding,)


def test_approving_the_finding_is_the_corrective_review_action_that_lifts_the_freeze() -> None:
    """'...or corrective review': approving the exact finding id is
    the corrective-review action, using the gate's own existing
    'unless approved' mechanism -- not a second, parallel one."""
    reports = [_report(0.1) for _ in range(8)] + [_report(0.9) for _ in range(2)]
    status = evaluate_error_budget(_SLO, reports, max_allowed_breach_rate=0.1)
    finding = record_error_budget_action(status, owner="platform-oncall")
    assert finding is not None

    decision = evaluate_release_gate([finding], approved_finding_ids=[finding.finding_id])
    assert decision.blocked is False
