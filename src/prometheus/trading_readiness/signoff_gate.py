"""EXT-12: "obtain multi-function final authorization for any live
orders" / "trading, risk, compliance, IT security and legal sign-off."
Generalizes `evidence.model_registry.SinglePersonApprovalError`'s
existing 2-identity distinctness check (`approved_by == actor`, CIQ-08)
from 2 identities to 5 named, pairwise-distinct roles. Validation lives
directly in `ArmingDecision.__post_init__`, the same place
`evidence.gate_report.GateDecisionForm` puts its own "no GO without
named approvers" check -- there is no code path that constructs an
`ArmingDecision` with a missing or duplicated role, not merely a
separate function that happens to check this first.

Because no real individuals occupy these 5 roles on a solo research
project, this gate is honestly, permanently un-armable in practice --
that absence is the safety property this module records, not a gap in
it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

_ROLES = ("trading", "risk", "compliance", "security", "legal")


class InsufficientSignoffError(ValueError):
    """Raised when a role's sign-off is missing, or two roles are
    signed off by the same name."""


@dataclass(frozen=True, slots=True)
class ArmingDecision:
    trading: str
    risk: str
    compliance: str
    security: str
    legal: str
    armed_at: datetime

    def __post_init__(self) -> None:
        names = {role: getattr(self, role) for role in _ROLES}
        missing = sorted(role for role, name in names.items() if not name)
        if missing:
            raise InsufficientSignoffError(f"missing sign-off for: {', '.join(missing)}")
        seen: dict[str, str] = {}
        duplicates: list[str] = []
        for role, name in names.items():
            if name in seen:
                duplicates.append(f"{seen[name]!r} and {role!r} both signed off as {name!r}")
            else:
                seen[name] = role
        if duplicates:
            raise InsufficientSignoffError(
                f"sign-offs must be pairwise distinct: {'; '.join(duplicates)}"
            )

    @property
    def roles(self) -> tuple[str, ...]:
        return _ROLES


def arm(
    *,
    trading: str,
    risk: str,
    compliance: str,
    security: str,
    legal: str,
    at: datetime | None = None,
) -> ArmingDecision:
    """The convenience constructor: `ArmingDecision` itself enforces
    every invariant, this just supplies `at`'s "or now" default."""
    return ArmingDecision(
        trading=trading,
        risk=risk,
        compliance=compliance,
        security=security,
        legal=legal,
        armed_at=at or datetime.now(UTC),
    )
