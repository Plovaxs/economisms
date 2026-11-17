from __future__ import annotations

import numpy as np
import pytest

from prometheus.evidence.gate_report import GateDecisionForm
from prometheus.titan.risk_metrics import (
    historical_expected_shortfall,
    historical_var,
    max_drawdown,
)
from prometheus.trading_readiness.capital_risk_budget import (
    build_risk_budget_report,
    not_assessed_budget_approval,
)

_LOSSES = np.array([10.0, 20.0, 5.0, 50.0, 15.0, 30.0, 8.0, 100.0, 12.0, 25.0])
_CUMULATIVE_VALUES = np.array([100.0, 90.0, 110.0, 60.0, 80.0])


def test_the_reports_figures_match_direct_titan_risk_metrics_calls() -> None:
    approval = not_assessed_budget_approval()
    report = build_risk_budget_report(_LOSSES, _CUMULATIVE_VALUES, 0.90, approval)
    assert report.value_at_risk == historical_var(_LOSSES, 0.90)
    assert report.expected_shortfall == historical_expected_shortfall(_LOSSES, 0.90)
    assert report.max_drawdown == max_drawdown(_CUMULATIVE_VALUES)


def test_not_assessed_budget_approval_is_a_real_not_assessed_gate_decision() -> None:
    approval = not_assessed_budget_approval()
    assert isinstance(approval, GateDecisionForm)
    assert approval.decision == "NOT ASSESSED"
    assert approval.scientific_approval is None
    assert approval.security_ops_approval is None


def test_a_go_decision_still_requires_named_approvers_the_existing_constraint() -> None:
    """The same, already-tested GateDecisionForm constraint
    (test_gate_report.py), now exercised from this new call site: a
    GO/CONDITIONAL decision cannot be constructed without naming real
    approvers -- there is no special case for a risk budget."""
    with pytest.raises(ValueError, match="requires these approvals"):
        GateDecisionForm(
            gate="trading_readiness-risk-budget",
            artifact_version="0.1.0",
            scope_enabled=(),
            scope_prohibited=("placeholder",),
            evidence_index=(),
            open_findings=(),
            scientific_approval=None,
            security_ops_approval=None,
            legal_compliance_assessment=None,
            decision="GO",
            decided_at=not_assessed_budget_approval().decided_at,
            sunset_date=not_assessed_budget_approval().decided_at,
        )
