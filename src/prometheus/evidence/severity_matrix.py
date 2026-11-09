"""Severity matrix for incorrect pricing, risk and data-integrity
incidents (DRI-01: "Define severity matrix for incorrect pricing,
risk and data breaches"; acceptance criterion: "SEV tiers and
response ownership approved").

Reuses `evidence.alert_routing`'s own P0/P1/P2 taxonomy rather than
inventing a second, parallel severity vocabulary. "Approved" is NOT
independently verified by any organizational authority this single-
maintainer repository does not have -- `approved_by` is a required,
caller-supplied field with no default, the same "no silently-
defaulted field" reasoning `evidence.model_registry`'s own
`approved_by` field and `evidence.ops_inventory`'s `owner` field
already use, so the matrix never claims an approval it was not
deliberately told.

`SeverityMatrix.lookup` raises `UnknownIncidentCategoryError` for any
category not in the matrix -- the entire point of a severity matrix
is that every real incident category is classified BEFORE it occurs,
not improvised after. Demonstrated in this module's own tests against
REAL incident category strings already defined elsewhere in this
repository -- `jobs.store.ERROR_CODES` and
`evidence.numerical_event_monitor`'s `EventKind` values -- not
invented category names, including a real category deliberately left
out of the matrix to confirm the raise fires on an actual gap.
"""

from __future__ import annotations

from dataclasses import dataclass

from prometheus.evidence.alert_routing import Severity


class UnknownIncidentCategoryError(ValueError):
    """Raised when a category has no entry in the severity matrix."""


@dataclass(frozen=True, slots=True)
class SeverityMatrixEntry:
    category: str
    severity: Severity
    owner: str
    approved_by: str

    def __post_init__(self) -> None:
        if not self.category:
            raise ValueError("category must not be empty")
        if not self.owner:
            raise ValueError("owner must not be empty")
        if not self.approved_by:
            raise ValueError("approved_by must not be empty")


@dataclass(frozen=True, slots=True)
class SeverityMatrix:
    entries: tuple[SeverityMatrixEntry, ...]

    def __post_init__(self) -> None:
        categories = [entry.category for entry in self.entries]
        if len(categories) != len(set(categories)):
            raise ValueError("severity matrix must not have duplicate categories")

    def lookup(self, category: str) -> SeverityMatrixEntry:
        for entry in self.entries:
            if entry.category == category:
                return entry
        raise UnknownIncidentCategoryError(
            f"{category!r} has no entry in the severity matrix -- every real incident "
            "category must be classified before it occurs, not improvised after"
        )
