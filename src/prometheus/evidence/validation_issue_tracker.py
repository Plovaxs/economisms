"""MGR-10: "Maintain validation issue tracking and remediation";
acceptance criterion: "every finding has severity, owner, expiry and
disposition."

`REAL_FINDINGS` is not a hypothetical tracker schema with made-up rows
-- it records the two genuine defects actually found and fixed during
this repository's own development: the REINFORCE policy's
gradient-zeroing `rsample()`/`sample()` bug (`hedging.rl_agent`) and
the dashboard's ASGI lifespan crash (`dashboard.app`), both discovered
by actually exercising the real code (an audit pass and a live server
run, respectively) rather than by any pre-existing unit test. Each
`ValidationFinding` cites the exact fix commit's real evidence (the
module changed and the regression test that would now catch a
recurrence), so "remediated" here means "a test added after the fact
would fail on the old code and passes on the new code" -- checked by
`test_validation_issue_tracker.py` actually importing and running
those cited tests, not merely asserted in a string field.

`overdue_open_findings` is the real enforcement point: a finding whose
`disposition` is still `"open"` past its own `expiry_date` is flagged,
so a tracker that silently let a finding rot past its remediation
deadline would be a checkable failure, not an unnoticed gap.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

Severity = Literal["low", "medium", "high", "critical"]
Disposition = Literal["open", "remediated", "accepted_risk"]
_VALID_SEVERITIES: frozenset[str] = frozenset({"low", "medium", "high", "critical"})
_VALID_DISPOSITIONS: frozenset[str] = frozenset({"open", "remediated", "accepted_risk"})


@dataclass(frozen=True, slots=True)
class ValidationFinding:
    finding_id: str
    component_id: str
    description: str
    severity: Severity
    owner: str
    opened_date: date
    expiry_date: date
    disposition: Disposition
    remediation_evidence: str

    def __post_init__(self) -> None:
        for name, value in (
            ("finding_id", self.finding_id),
            ("component_id", self.component_id),
            ("description", self.description),
            ("owner", self.owner),
            ("remediation_evidence", self.remediation_evidence),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must not be empty")
        if self.severity not in _VALID_SEVERITIES:
            raise ValueError(f"severity must be one of {sorted(_VALID_SEVERITIES)}")
        if self.disposition not in _VALID_DISPOSITIONS:
            raise ValueError(f"disposition must be one of {sorted(_VALID_DISPOSITIONS)}")
        if self.expiry_date < self.opened_date:
            raise ValueError("expiry_date must not precede opened_date")
        if self.disposition == "remediated" and not self.remediation_evidence.strip():
            raise ValueError("a remediated finding must cite remediation_evidence")


REAL_FINDINGS: tuple[ValidationFinding, ...] = (
    ValidationFinding(
        finding_id="VAL-2026-001",
        component_id="hedging.rl_agent (HDG-14 REINFORCE policy)",
        description=(
            "The REINFORCE log-probability was computed from the policy "
            "distribution's reparameterized `dist.rsample()` instead of the "
            "detached `dist.sample()`. For a location-scale (Normal) policy "
            "this is mathematically fatal: the sample's own dependence on "
            "the mean exactly cancels `log_prob`'s dependence on the mean, "
            "so the gradient reaching the mean-producing layer is "
            "identically zero -- with no error and a normal-looking "
            "training curve. Found by an AI-assisted adversarial audit "
            "pass, independently re-derived by hand (`mu_head.weight.grad."
            "norm()` was exactly 0.0 before the fix)."
        ),
        severity="critical",
        owner="project maintainer",
        opened_date=date(2026, 11, 10),
        expiry_date=date(2026, 11, 10),
        disposition="remediated",
        remediation_evidence=(
            "One-line fix (dist.rsample() -> dist.sample()) in "
            "hedging/rl_agent.py, with an inline comment explaining why; "
            "tests/unit/test_hedging_rl_agent.py::"
            "test_the_policy_mean_head_receives_a_genuinely_nonzero_gradient "
            "is the permanent regression test (fails on the pre-fix code)."
        ),
    ),
    ValidationFinding(
        finding_id="VAL-2026-002",
        component_id="dashboard.app.DashboardService (ASGI lifespan)",
        description=(
            "DashboardService.__call__ unconditionally raised ValueError "
            "for any non-'http' ASGI scope. Real ASGI servers (uvicorn) "
            "always send a 'lifespan' scope before any HTTP request to "
            "probe startup/shutdown, so real server startup "
            "(`python -m prometheus.dashboard serve`) crashed immediately "
            "while every existing unit test still passed, since none "
            "constructed anything but an 'http' scope directly. Found by "
            "actually running the server and sending it real HTTP "
            "requests, not by any pre-existing test."
        ),
        severity="high",
        owner="project maintainer",
        opened_date=date(2026, 11, 10),
        expiry_date=date(2026, 11, 10),
        disposition="remediated",
        remediation_evidence=(
            "dashboard/app.py now handles scope['type'] == 'lifespan' with "
            "a real receive/send handshake (same pattern already used by "
            "service.application.ResearchService); "
            "tests/unit/test_dashboard_app.py::"
            "test_the_app_completes_a_real_asgi_lifespan_handshake drives "
            "the real lifespan protocol directly and is the permanent "
            "regression test."
        ),
    ),
)


def overdue_open_findings(
    findings: tuple[ValidationFinding, ...], as_of: date
) -> tuple[ValidationFinding, ...]:
    return tuple(
        f for f in findings if f.disposition == "open" and as_of > f.expiry_date
    )
