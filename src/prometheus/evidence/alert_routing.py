"""Actionable alert routing with a severity taxonomy (OPS-10: "Define
actionable alert routing and severity taxonomy"; acceptance criterion:
"Each P0/P1 alert maps to human owner and escalation").

Unifies the different "ok"/"warning"/"critical"-style severities this
repository's own OPS modules already produce
(`evidence.queue_metrics.classify_queue_health`,
`evidence.resource_utilization.classify_utilization`, and
`evidence.model_monitoring.MonitoringSignal.triggered`) into ONE
canonical P0/P1/P2 taxonomy via `canonical_severity`/
`severity_from_triggered`, and ENFORCES -- not merely documents --
this item's own acceptance criterion: `route_alert` raises
`UnroutedSeverityError` if asked to route a P0 or P1 severity with no
configured human owner and escalation contact, rather than silently
returning an alert with no one responsible. A P2 (informational) alert
with no configured route is not an error -- the acceptance criterion
names only P0/P1 -- `route_alert` simply returns `None` for it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Severity = Literal["P0", "P1", "P2"]

_LEGACY_SEVERITY_MAP: dict[str, Severity] = {"critical": "P0", "warning": "P1", "ok": "P2"}


def canonical_severity(legacy: str) -> Severity:
    try:
        return _LEGACY_SEVERITY_MAP[legacy]
    except KeyError:
        raise ValueError(f"unrecognized severity {legacy!r}") from None


def severity_from_triggered(triggered: bool) -> Severity:
    return "P1" if triggered else "P2"


class UnroutedSeverityError(ValueError):
    """Raised when a P0/P1 alert has no configured human owner and
    escalation contact to route to."""


@dataclass(frozen=True, slots=True)
class AlertRoute:
    severity: Severity
    owner: str
    escalation_contact: str

    def __post_init__(self) -> None:
        if not self.owner:
            raise ValueError("owner must not be empty")
        if not self.escalation_contact:
            raise ValueError("escalation_contact must not be empty")


@dataclass(frozen=True, slots=True)
class RoutingTable:
    routes: tuple[AlertRoute, ...]

    def __post_init__(self) -> None:
        severities = [route.severity for route in self.routes]
        if len(severities) != len(set(severities)):
            raise ValueError("routing table must not have duplicate severities")


def route_alert(severity: Severity, table: RoutingTable) -> AlertRoute | None:
    for route in table.routes:
        if route.severity == severity:
            return route
    if severity in ("P0", "P1"):
        raise UnroutedSeverityError(
            f"{severity} alert has no configured human owner and escalation contact"
        )
    return None
