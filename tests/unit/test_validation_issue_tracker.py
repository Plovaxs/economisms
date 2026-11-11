from __future__ import annotations

import importlib
from datetime import date

import pytest

from prometheus.evidence.validation_issue_tracker import (
    REAL_FINDINGS,
    ValidationFinding,
    open_p0_findings,
    overdue_open_findings,
)


def test_every_real_finding_has_severity_owner_expiry_and_disposition() -> None:
    """MGR-10's own acceptance wording, checked directly against the
    real tracked findings rather than merely asserted in prose."""
    assert len(REAL_FINDINGS) >= 2
    for finding in REAL_FINDINGS:
        assert finding.severity
        assert finding.owner.strip()
        assert isinstance(finding.expiry_date, date)
        assert finding.disposition in ("open", "remediated", "accepted_risk")


def test_both_real_findings_are_remediated_with_real_regression_tests_cited() -> None:
    for finding in REAL_FINDINGS:
        assert finding.disposition == "remediated"
        assert "test_" in finding.remediation_evidence


def test_the_rsample_finding_cites_a_regression_test_that_really_exists() -> None:
    """The finding's `remediation_evidence` is a claim about another
    test file; confirm the named function genuinely exists there
    (and is therefore collected and run by the same `pytest` invocation
    that runs this file), rather than trusting the citation as prose."""
    module = importlib.import_module("tests.unit.test_hedging_rl_agent")
    test_fn = module.test_the_policy_mean_head_receives_a_genuinely_nonzero_gradient
    assert callable(test_fn)


def test_the_lifespan_finding_cites_a_regression_test_that_really_exists() -> None:
    module = importlib.import_module("tests.unit.test_dashboard_app")
    test_fn = module.test_the_app_completes_a_real_asgi_lifespan_handshake
    assert callable(test_fn)


def test_expiry_date_must_not_precede_opened_date() -> None:
    with pytest.raises(ValueError, match="expiry_date"):
        ValidationFinding(
            finding_id="x",
            component_id="c",
            description="d",
            severity="low",
            owner="o",
            opened_date=date(2026, 1, 2),
            expiry_date=date(2026, 1, 1),
            disposition="open",
            remediation_evidence="n/a",
        )


def test_a_remediated_finding_requires_remediation_evidence() -> None:
    with pytest.raises(ValueError, match="remediation_evidence"):
        ValidationFinding(
            finding_id="x",
            component_id="c",
            description="d",
            severity="low",
            owner="o",
            opened_date=date(2026, 1, 1),
            expiry_date=date(2026, 1, 1),
            disposition="remediated",
            remediation_evidence="   ",
        )


def test_overdue_open_findings_flags_only_open_findings_past_their_expiry() -> None:
    findings = (
        ValidationFinding(
            finding_id="open-overdue",
            component_id="c",
            description="d",
            severity="medium",
            owner="o",
            opened_date=date(2026, 1, 1),
            expiry_date=date(2026, 1, 10),
            disposition="open",
            remediation_evidence="n/a",
        ),
        ValidationFinding(
            finding_id="open-not-yet-due",
            component_id="c",
            description="d",
            severity="medium",
            owner="o",
            opened_date=date(2026, 1, 1),
            expiry_date=date(2026, 2, 1),
            disposition="open",
            remediation_evidence="n/a",
        ),
        ValidationFinding(
            finding_id="remediated-overdue-irrelevant",
            component_id="c",
            description="d",
            severity="medium",
            owner="o",
            opened_date=date(2026, 1, 1),
            expiry_date=date(2026, 1, 10),
            disposition="remediated",
            remediation_evidence="fixed",
        ),
    )
    overdue = overdue_open_findings(findings, as_of=date(2026, 1, 20))
    assert [f.finding_id for f in overdue] == ["open-overdue"]


def test_no_p0_severity_finding_is_open_in_the_real_tracker() -> None:
    """LCH-03's own acceptance wording: "open P0 model findings closed
    or formally blocked." The one critical-severity (P0, via
    alert_routing's own canonical taxonomy) finding this repository
    has on record is already remediated."""
    assert open_p0_findings() == ()
    assert any(f.severity == "critical" for f in REAL_FINDINGS)


def test_open_p0_findings_flags_a_real_open_critical_finding() -> None:
    findings = (
        ValidationFinding(
            finding_id="open-critical",
            component_id="c",
            description="d",
            severity="critical",
            owner="o",
            opened_date=date(2026, 1, 1),
            expiry_date=date(2026, 2, 1),
            disposition="open",
            remediation_evidence="n/a",
        ),
        ValidationFinding(
            finding_id="open-high-not-p0",
            component_id="c",
            description="d",
            severity="high",
            owner="o",
            opened_date=date(2026, 1, 1),
            expiry_date=date(2026, 2, 1),
            disposition="open",
            remediation_evidence="n/a",
        ),
    )
    assert [f.finding_id for f in open_p0_findings(findings)] == ["open-critical"]
