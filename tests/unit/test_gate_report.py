from datetime import date

import pytest

from prometheus.evidence.gate_report import GateDecisionForm


def _valid_form_kwargs(**overrides):
    kwargs = dict(
        gate="R0",
        artifact_version="0.1.0",
        scope_enabled=("local simulation",),
        scope_prohibited=("live trading",),
        evidence_index=("CHECKLIST_STATUS.md",),
        open_findings=(),
        scientific_approval=None,
        security_ops_approval=None,
        legal_compliance_assessment=None,
        decision="NO-GO",
        decided_at=date(2026, 1, 1),
        sunset_date=None,
    )
    kwargs.update(overrides)
    return kwargs


def test_no_go_requires_no_approvers() -> None:
    form = GateDecisionForm(**_valid_form_kwargs())
    assert form.decision == "NO-GO"


def test_empty_gate_rejected() -> None:
    with pytest.raises(ValueError):
        GateDecisionForm(**_valid_form_kwargs(gate=""))


def test_empty_scope_prohibited_rejected() -> None:
    """A gate record that doesn't explicitly list what's excluded (e.g.
    live trading) is not a usable safety boundary."""
    with pytest.raises(ValueError):
        GateDecisionForm(**_valid_form_kwargs(scope_prohibited=()))


def test_invalid_decision_value_rejected() -> None:
    with pytest.raises(ValueError):
        GateDecisionForm(**_valid_form_kwargs(decision="MAYBE"))  # type: ignore[arg-type]


def test_go_without_approvers_rejected() -> None:
    with pytest.raises(ValueError):
        GateDecisionForm(
            **_valid_form_kwargs(
                decision="GO",
                scientific_approval=None,
                security_ops_approval=None,
                sunset_date=date(2026, 6, 1),
            )
        )


def test_go_without_sunset_date_rejected() -> None:
    with pytest.raises(ValueError):
        GateDecisionForm(
            **_valid_form_kwargs(
                decision="GO",
                scientific_approval="Dr. A",
                security_ops_approval="Mr. B",
                sunset_date=None,
            )
        )


def test_go_with_full_evidence_succeeds() -> None:
    form = GateDecisionForm(
        **_valid_form_kwargs(
            decision="GO",
            scientific_approval="Dr. A",
            security_ops_approval="Mr. B",
            sunset_date=date(2026, 6, 1),
        )
    )
    assert form.decision == "GO"


def test_conditional_also_requires_full_evidence() -> None:
    with pytest.raises(ValueError):
        GateDecisionForm(**_valid_form_kwargs(decision="CONDITIONAL"))


def test_boolean_approval_cannot_impersonate_a_named_approver():
    with pytest.raises(ValueError, match="named text"):
        GateDecisionForm(
            **_valid_form_kwargs(
                decision="GO",
                scientific_approval=True,
                security_ops_approval="Reviewer",
                sunset_date=date(2026, 6, 1),
            )
        )


def test_gate_sunset_cannot_precede_the_decision_date():
    with pytest.raises(ValueError, match="precede"):
        GateDecisionForm(**_valid_form_kwargs(sunset_date=date(2025, 1, 1)))
