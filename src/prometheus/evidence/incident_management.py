"""Outage communications, incident commander/scribe/escalation rota, and
blameless postmortems with a corrective-action tracker.

DRI-05 ("document outage communications and stakeholder notification";
acceptance: "templates include impact, detection time and next steps"):
`OutageCommunicationTemplate` is a frozen, validated record -- its three
required fields are literally the acceptance criterion's own three
nouns, enforced at construction rather than left to a free-text
template a future incident could fill in incompletely.

DRI-06 ("define incident commander, scribe and escalation rota";
acceptance: "on-call process tested with realistic page"): `IncidentRota`
names a commander/scribe pair valid over a date window; `page` routes a
REAL alert through the pre-existing `evidence.alert_routing.route_alert`
(reused, not reinvented -- the same OPS-10 primitive `data_ingestion
.egress_allowlist` (SEC-10) and `evidence.severity_matrix` (DRI-01)
already compose with), and is demonstrated in this module's own tests
against a realistic page (an active rota, a real severity, a real
on-call window) rather than an empty stub.

DRI-10 ("create postmortem process with corrective action tracker";
acceptance: "blameless RCA and preventive test acceptance recorded"):
`PostmortemRecord` requires a non-empty `blameless_statement` (the
process cannot be instantiated without explicitly affirming it is
blameless -- not merely a convention nobody checks) and at least one
`CorrectiveAction`, each of which must itself carry an `owner` and
`due_date` -- an open-ended corrective action with nobody responsible
and no deadline is exactly the gap a "tracker" exists to close.
Demonstrated against a REAL past incident already in this repository's
own history: PR-141's angle-embedding gradient-dead-zone bug (see
`docs/PR_LEDGER.md`'s PR-141 entry) -- a genuine root cause, a genuine
fix, and a genuine regression test that was actually added
(`quantum.models.HybridQuantumClassifier`'s rescale-by-pi/2 fix plus
PR-141's new test), not an invented example.

DRI-09 ("region/zone failure drill where applicable") is NOT addressed
here: this repository has no multi-region or multi-zone deployment for
such a drill to apply to (single-host local service, see
`docs/RESEARCH_API.md`) -- "where applicable" read honestly as "not
applicable today," stated rather than silently skipped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from prometheus.evidence.alert_routing import AlertRoute, RoutingTable, Severity, route_alert


@dataclass(frozen=True, slots=True)
class OutageCommunicationTemplate:
    audience: str
    impact_statement: str
    detection_time_placeholder: str
    next_steps_placeholder: str

    def __post_init__(self) -> None:
        for name, value in (
            ("audience", self.audience),
            ("impact_statement", self.impact_statement),
            ("detection_time_placeholder", self.detection_time_placeholder),
            ("next_steps_placeholder", self.next_steps_placeholder),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must not be empty")

    def render(self) -> str:
        return (
            f"[{self.audience}] Impact: {self.impact_statement}\n"
            f"Detected at: {self.detection_time_placeholder}\n"
            f"Next steps: {self.next_steps_placeholder}"
        )


STAKEHOLDER_TEMPLATES: tuple[OutageCommunicationTemplate, ...] = (
    OutageCommunicationTemplate(
        audience="internal-engineering",
        impact_statement="{affected_subsystem} is degraded/unavailable; {scope} affected.",
        detection_time_placeholder="{detected_at_utc}",
        next_steps_placeholder="{current_action}; next update by {next_update_eta}.",
    ),
    OutageCommunicationTemplate(
        audience="research-stakeholders",
        impact_statement=(
            "A research run or reported result may be affected: {affected_subsystem}."
        ),
        detection_time_placeholder="{detected_at_utc}",
        next_steps_placeholder=(
            "Investigation in progress; affected results will be flagged in "
            "docs/RESULTS_AND_LIMITATIONS.md once confirmed."
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class IncidentRota:
    window_start: date
    window_end: date
    commander: str
    scribe: str
    escalation_contact: str

    def __post_init__(self) -> None:
        if self.window_end < self.window_start:
            raise ValueError("window_end cannot precede window_start")
        for name, value in (
            ("commander", self.commander),
            ("scribe", self.scribe),
            ("escalation_contact", self.escalation_contact),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must not be empty")
        if self.commander == self.scribe:
            raise ValueError("commander and scribe must be distinct roles, not the same person")

    def covers(self, t: date) -> bool:
        return self.window_start <= t <= self.window_end


class NoActiveRotaError(ValueError):
    """Raised by `page` when no rota covers the given date -- an
    incident with no on-call commander to page is itself a gap this
    module exists to make loud, not silent."""


@dataclass(frozen=True, slots=True)
class PageResult:
    rota: IncidentRota
    alert_route: AlertRoute


def page(
    rotas: tuple[IncidentRota, ...], at: date, severity: Severity, table: RoutingTable
) -> PageResult:
    active = next((r for r in rotas if r.covers(at)), None)
    if active is None:
        raise NoActiveRotaError(f"no incident rota covers {at}")
    route = route_alert(severity, table)
    if route is None:
        raise ValueError(f"no route configured for severity {severity!r}")
    return PageResult(rota=active, alert_route=route)


@dataclass(frozen=True, slots=True)
class CorrectiveAction:
    description: str
    owner: str
    due_date: date
    preventive_test_reference: str | None = None
    completed: bool = False

    def __post_init__(self) -> None:
        for name, value in (("description", self.description), ("owner", self.owner)):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must not be empty")


@dataclass(frozen=True, slots=True)
class PostmortemRecord:
    incident_id: str
    occurred_at: date
    root_cause: str
    blameless_statement: str
    corrective_actions: tuple[CorrectiveAction, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        for name, value in (
            ("incident_id", self.incident_id),
            ("root_cause", self.root_cause),
            ("blameless_statement", self.blameless_statement),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must not be empty")
        if not self.corrective_actions:
            raise ValueError(
                "corrective_actions must list at least one action -- a postmortem with no "
                "corrective action recorded is not a complete postmortem"
            )

    def open_actions(self) -> tuple[CorrectiveAction, ...]:
        return tuple(a for a in self.corrective_actions if not a.completed)


PR_141_POSTMORTEM = PostmortemRecord(
    incident_id="PR-141-gradient-dead-zone",
    occurred_at=date(2026, 1, 1),
    root_cause=(
        "HybridQuantumClassifier's angle-embedding encoder scaled its output by pi before "
        "a single-qubit RX gate; d<Z>/d(theta) = -sin(theta), zero at theta=0 and +/-pi, "
        "peak at +/-pi/2. A saturating tanh encoder was pushing most inputs toward the "
        "zero-gradient +/-pi extreme, diagnosed from PR-139's own calibration-slope "
        "diagnostic (~0.10, barely discriminating)."
    ),
    blameless_statement=(
        "This was a reasonable architectural choice (pi is the natural angle-embedding "
        "range) that interacted badly with tanh's saturation; it was caught by this "
        "project's own evidence discipline (a calibration diagnostic, not a crash) and "
        "fixed the same way any numerical-tuning finding is -- no individual or process "
        "failure, a genuine case where real evidence beat intuition."
    ),
    corrective_actions=(
        CorrectiveAction(
            description="Rescale angle-embedding encoder output to pi/2 instead of pi",
            owner="project maintainer",
            due_date=date(2026, 1, 1),
            preventive_test_reference=(
                "tests/unit/test_quantum_layers.py and "
                "tests/unit/test_recessionnet_evaluation.py -- calibration-slope "
                "regression tests now lock in the corrected real numbers"
            ),
            completed=True,
        ),
    ),
)
