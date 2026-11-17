"""EXT-11: "perform capital, liquidity and operational risk review" /
"limits and loss budgets signed by accountable officers." VaR/ES/
drawdown reuse `titan.risk_metrics` unchanged -- closing the "not yet
wired to any portfolio, position book or the ledger/economy" gap that
module's own `__init__.py` already names, narrowly, for this package's
own P&L series. "Signed by accountable officers" is represented by
constructing a real `evidence.gate_report.GateDecisionForm` -- the
same type, and the same "no GO without named approvers" validation
LCH-12 already evidences -- not a second, parallel approval type
invented for this one item.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

from prometheus.evidence.gate_report import GateDecisionForm
from prometheus.titan.risk_metrics import (
    historical_expected_shortfall,
    historical_var,
    max_drawdown,
)


@dataclass(frozen=True, slots=True)
class RiskBudgetReport:
    value_at_risk: float
    expected_shortfall: float
    max_drawdown: float
    alpha: float
    approval: GateDecisionForm


def build_risk_budget_report(
    losses: np.ndarray, cumulative_values: np.ndarray, alpha: float, approval: GateDecisionForm
) -> RiskBudgetReport:
    return RiskBudgetReport(
        value_at_risk=historical_var(losses, alpha),
        expected_shortfall=historical_expected_shortfall(losses, alpha),
        max_drawdown=max_drawdown(cumulative_values),
        alpha=alpha,
        approval=approval,
    )


def not_assessed_budget_approval(*, decided_at: date | None = None) -> GateDecisionForm:
    """A real, honestly `NOT ASSESSED` `GateDecisionForm` -- there are
    no real accountable officers on this solo project to sign a GO."""
    return GateDecisionForm(
        gate="trading_readiness-risk-budget",
        artifact_version="0.1.0",
        scope_enabled=(),
        scope_prohibited=(
            "Trading against this budget without real capital and named "
            "accountable-officer sign-off",
        ),
        evidence_index=(),
        open_findings=("No accountable officer has reviewed or signed this budget",),
        scientific_approval=None,
        security_ops_approval=None,
        legal_compliance_assessment=None,
        decision="NOT ASSESSED",
        decided_at=decided_at or date.today(),
        sunset_date=None,
    )
