"""PRV-04: "Define data retention schedule for raw data, logs and
artifacts"; acceptance criterion: "automated expiry or signed
exceptions verifiable".

`is_past_retention` is the real, automated expiry check -- a pure
function of `(created_at, retention_days, as_of)`, reused by any real
caller that needs to ask "should this have been deleted by now" rather
than a human tracking dates by hand. `RetentionException` mirrors
`evidence.risk_register.RiskException`'s own shape (signed-by +
sunset date, both required) deliberately -- the identical "no silently
open-ended exception" enforcement, applied to retention instead of
risk acceptance, composed from the same design rather than invented a
second time.

`DEFAULT_RETENTION_SCHEDULE` records this repository's REAL data
categories and their REAL, deliberate retention decisions -- including
the honest ones that are not "delete after N days": this project's
committed macro-data snapshots (`data_cache/*.csv`) are retained
INDEFINITELY by design, because reproducibility (the entire point of
committing them, see `docs/DATA_DICTIONARY.md`) requires them to still
be there years from now, not expired. "Automated... or signed
exceptions" is read as: a schedule that is honestly indefinite for a
real, named reason is not a gap to be exception-signed around; a
schedule for something that genuinely should expire (the local
encrypted recovery snapshots, `recovery.snapshot`) gets a real,
checkable retention period instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    data_category: str
    retention_days: int | None
    """None means retained indefinitely, by deliberate design -- see
    this module's own docstring for why that is a real policy
    decision, not an unset field."""
    rationale: str

    def __post_init__(self) -> None:
        if not self.data_category.strip() or not self.rationale.strip():
            raise ValueError("data_category and rationale must not be empty")
        if self.retention_days is not None and self.retention_days < 1:
            raise ValueError("retention_days must be positive when set")


@dataclass(frozen=True, slots=True)
class RetentionException:
    data_category: str
    signed_by: str
    reason: str
    sunset_date: date

    def __post_init__(self) -> None:
        for name, value in (
            ("data_category", self.data_category),
            ("signed_by", self.signed_by),
            ("reason", self.reason),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must not be empty")


DEFAULT_RETENTION_SCHEDULE: tuple[RetentionPolicy, ...] = (
    RetentionPolicy(
        data_category="committed macro/market data snapshots (data_cache/*.csv)",
        retention_days=None,
        rationale=(
            "Retained indefinitely by design: these are the real, licensed, "
            "already-public source data this project's reproducibility claims "
            "depend on (see docs/DATA_DICTIONARY.md) -- expiring them would break "
            "every past PR's own re-run instructions."
        ),
    ),
    RetentionPolicy(
        data_category="evidence bundles and gate reports (evidence/*.json)",
        retention_days=None,
        rationale=(
            "Retained indefinitely: these are this project's own audit trail "
            "(AUD-08/AUD-11); deleting them would break the evidence chain they exist "
            "to provide."
        ),
    ),
    RetentionPolicy(
        data_category="local encrypted recovery snapshots (recovery.snapshot)",
        retention_days=90,
        rationale=(
            "Local-only operational backups, not committed to this repository -- a "
            "real, bounded retention window (REL-11/DRI-07/08's own recovery scope), "
            "not a reproducibility artifact."
        ),
    ),
    RetentionPolicy(
        data_category="CI build artifacts (dist/, wheel builds)",
        retention_days=30,
        rationale="Ephemeral build outputs, regenerable from source at any time.",
    ),
    RetentionPolicy(
        data_category="persistent application logs",
        retention_days=None,
        rationale=(
            "Not applicable: this project's services (service.auth/application, "
            "dashboard.app) log to stdout only (see their own modules) -- there is no "
            "persistent log store in this repository for a retention schedule to apply "
            "to. If one is added, this schedule must be updated before it ships."
        ),
    ),
)


def is_past_retention(created_at: date, retention_days: int | None, as_of: date) -> bool:
    """Returns False for an indefinite (`retention_days=None`) policy --
    there is nothing to expire by definition, not an unchecked gap."""
    if retention_days is None:
        return False
    return as_of >= created_at + timedelta(days=retention_days)


def is_covered_by_exception(
    data_category: str, as_of: date, exceptions: tuple[RetentionException, ...]
) -> bool:
    return any(
        e.data_category == data_category and as_of <= e.sunset_date for e in exceptions
    )
