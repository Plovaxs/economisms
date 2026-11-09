"""Risk acceptance register (GOV-12: "maintain risk acceptance authority
and expiration"; acceptance criterion: "every material exception has
approver and sunset date").

This is a MORE GENERAL mechanism than `evidence.gate_report.GateDecisionForm`
(LCH-12), which already enforces an approver + `sunset_date` but only for
the single top-level release-gate decision. GOV-12's acceptance wording is
about "every material exception" -- any individually accepted risk a PR or
design decision takes on (a disclosed substitution, a deliberately
unimplemented control, a known limitation accepted rather than fixed), not
just the one gate record. `RiskException` applies the identical
enforced-at-construction pattern (`approver`/`sunset_date` are required,
non-optional fields -- there is no code path that constructs one silently
missing either) to that broader class of exceptions, reusing
`experiments.manifest.compute_result_hash` for a content-addressed id the
same way `holdout_manifest`/`dataset_fingerprint` already do, rather than
inventing a second id scheme.

`RiskRegister.active_as_of` is the real behavior this exists for, not just
storage: it partitions exceptions into still-active and expired as of a
given date, so a caller (e.g. a release-gate check) can ask "is anything
being silently relied on past its own stated expiration" instead of a
sunset date being a field nobody ever reads back.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from prometheus.experiments.manifest import compute_result_hash


@dataclass(frozen=True, slots=True)
class RiskException:
    description: str
    """What is being accepted, specifically -- not a category label."""
    approver: str
    """Who accepted this risk. A single-maintainer repository names the
    maintainer role, not a fabricated second identity -- see GOV-03's own
    disclosed limitation in `CHECKLIST_STATUS.md` for why this register
    does not claim multi-person accountability it does not have."""
    accepted_at: date
    sunset_date: date
    """Required, not optional: an exception with no re-review date is
    exactly the silent, open-ended risk acceptance this item exists to
    prevent."""
    mitigation: str = ""
    """What reduces the risk in the meantime, if anything. Empty string is
    a legitimate, honest value -- "no mitigation, risk accepted as-is" is
    a real, statable position, not an error."""

    def __post_init__(self) -> None:
        for name, value in (
            ("description", self.description),
            ("approver", self.approver),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must not be empty")
        if type(self.accepted_at) is not date or type(self.sunset_date) is not date:
            raise ValueError("accepted_at and sunset_date must be calendar dates")
        if self.sunset_date < self.accepted_at:
            raise ValueError("sunset_date cannot precede accepted_at")

    @property
    def exception_id(self) -> str:
        return compute_result_hash(
            {
                "description": self.description,
                "approver": self.approver,
                "accepted_at": self.accepted_at,
                "sunset_date": self.sunset_date,
            }
        )

    def is_active(self, as_of: date) -> bool:
        return self.accepted_at <= as_of <= self.sunset_date


@dataclass(frozen=True, slots=True)
class RiskRegister:
    exceptions: tuple[RiskException, ...]

    def active_as_of(self, as_of: date) -> tuple[RiskException, ...]:
        return tuple(e for e in self.exceptions if e.is_active(as_of))

    def inactive_as_of(self, as_of: date) -> tuple[RiskException, ...]:
        """Not currently active -- either expired (past `sunset_date`) or
        not yet started (before `accepted_at`); `is_active` is the single
        source of truth for which, so this never duplicates that logic."""
        return tuple(e for e in self.exceptions if not e.is_active(as_of))
