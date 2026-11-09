"""Error budget actions with service ownership (REL-12: "Record
error budget actions and service ownership"; acceptance criterion:
"Breaches trigger release freeze or corrective review").

Composes REL-01's `ServiceLevelObjective`/`slo_is_met` over a WINDOW
of real `LoadReport`s (REL-02) rather than a single snapshot: the
"error budget" is how many of a caller-supplied sequence of real
reports fail to meet the SLO, against a caller-configured allowed
breach rate. When consumption exceeds that budget,
`record_error_budget_action` raises a REAL `evaluate_release_gate`
(CIQ-05) finding -- the SAME scanner-agnostic gate `evidence.security_scan.license_scan`
(DAT-13) already composes through -- so a genuine error-budget breach
actually blocks release through existing, already-evidenced gating
machinery, not a new, parallel mechanism. "Corrective review" is the
gate's own existing "unless approved" half: approving the finding's
exact id is the corrective-review action, recorded the same way any
other scan finding's approval already is.

`owner` is a required field with no default, so a "corrective review"
action always has someone accountable to assign it to.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from prometheus.evidence.security_scan import ScanFinding
from prometheus.evidence.slo_definitions import ServiceLevelObjective, slo_is_met
from prometheus.experiments.latency_benchmark import LoadReport


@dataclass(frozen=True, slots=True)
class ErrorBudgetStatus:
    service_name: str
    n_measurements: int
    n_breaches: int
    breach_rate: float
    max_allowed_breach_rate: float
    budget_exhausted: bool


def evaluate_error_budget(
    slo: ServiceLevelObjective,
    reports: Sequence[LoadReport],
    *,
    max_allowed_breach_rate: float,
) -> ErrorBudgetStatus:
    if not reports:
        raise ValueError("reports must not be empty")
    if not 0.0 <= max_allowed_breach_rate <= 1.0:
        raise ValueError("max_allowed_breach_rate must be in [0, 1]")
    n_breaches = sum(0 if slo_is_met(slo, report) else 1 for report in reports)
    breach_rate = n_breaches / len(reports)
    return ErrorBudgetStatus(
        service_name=slo.service_name,
        n_measurements=len(reports),
        n_breaches=n_breaches,
        breach_rate=breach_rate,
        max_allowed_breach_rate=max_allowed_breach_rate,
        budget_exhausted=breach_rate > max_allowed_breach_rate,
    )


def record_error_budget_action(status: ErrorBudgetStatus, *, owner: str) -> ScanFinding | None:
    if not owner:
        raise ValueError("owner must not be empty")
    if not status.budget_exhausted:
        return None
    return ScanFinding(
        scanner="error_budget",
        severity="high",
        location=f"{status.service_name}:{owner}",
        description=(
            f"error budget exhausted: {status.n_breaches}/{status.n_measurements} "
            f"measurements breached the SLO ({status.breach_rate:.1%} > "
            f"{status.max_allowed_breach_rate:.1%} allowed) -- release freeze or "
            "corrective review required"
        ),
    )
