"""A validated gate decision form (section 16's "Gate decision form";
section 13's phased program; section 19's final-release checklist).

Field names mirror the blueprint's own template. A record with
decision="GO" or "CONDITIONAL" cannot be constructed without naming every
required approver and a sunset (re-review) date -- there is no code path
that produces a GO record silently missing its evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

Decision = Literal["GO", "CONDITIONAL", "NO-GO", "NOT ASSESSED"]

_VALID_DECISIONS = {"GO", "CONDITIONAL", "NO-GO", "NOT ASSESSED"}


@dataclass(frozen=True, slots=True)
class GateDecisionForm:
    gate: str
    artifact_version: str
    scope_enabled: tuple[str, ...]
    scope_prohibited: tuple[str, ...]
    evidence_index: tuple[str, ...]
    open_findings: tuple[str, ...]
    scientific_approval: str | None
    security_ops_approval: str | None
    legal_compliance_assessment: str | None
    decision: Decision
    decided_at: date
    sunset_date: date | None

    def __post_init__(self) -> None:
        if not isinstance(self.gate, str) or not self.gate.strip():
            raise ValueError("gate must not be empty")
        if not self.scope_prohibited:
            raise ValueError(
                "scope_prohibited must explicitly list excluded operations "
                "(e.g. live trading) -- it cannot be empty"
            )
        if not isinstance(self.decision, str) or self.decision not in _VALID_DECISIONS:
            raise ValueError(f"decision must be one of {sorted(_VALID_DECISIONS)}")
        for name, value in (
            ("scientific_approval", self.scientific_approval),
            ("security_ops_approval", self.security_ops_approval),
            ("legal_compliance_assessment", self.legal_compliance_assessment),
        ):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{name} requires named text or None")
        if type(self.decided_at) is not date or (
            self.sunset_date is not None and type(self.sunset_date) is not date
        ):
            raise ValueError("gate decision and sunset require calendar dates")
        if self.sunset_date is not None and self.sunset_date < self.decided_at:
            raise ValueError("sunset_date cannot precede decided_at")
        if self.decision in ("GO", "CONDITIONAL"):
            missing = [
                name
                for name, value in (
                    ("scientific_approval", self.scientific_approval),
                    ("security_ops_approval", self.security_ops_approval),
                )
                if not value
            ]
            if missing:
                raise ValueError(
                    f"decision={self.decision!r} requires these approvals to be "
                    f"named, but they are missing: {missing}"
                )
            if self.sunset_date is None:
                raise ValueError(
                    f"decision={self.decision!r} requires an explicit sunset_date "
                    "(re-review deadline)"
                )
