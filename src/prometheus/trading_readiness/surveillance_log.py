"""EXT-08: "implement trading surveillance, recordkeeping and
retention" / "legally appropriate controls reviewed by compliance."
The RECORDKEEPING mechanism is real: every order attempt, accepted or
rejected, is recorded append-only, with a required retention date.
"Reviewed by compliance" is not met -- there is no compliance function
on this solo project to review it (see this package's own `__init__.py`
and CHECKLIST_STATUS.md's EXT-08 row for exactly what remains unmet).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Literal

from prometheus.trading_readiness.orders import Order

Decision = Literal["accepted", "rejected"]


@dataclass(frozen=True, slots=True)
class SurveillanceEntry:
    order: Order
    decision: Decision
    reason: str
    actor: str
    at: datetime

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError("reason must not be empty")
        if not self.actor:
            raise ValueError("actor must not be empty")


@dataclass(slots=True)
class SurveillanceLog:
    retention_until: date
    _entries: list[SurveillanceEntry] = field(default_factory=list, init=False)

    def record(
        self,
        order: Order,
        decision: Decision,
        reason: str,
        actor: str,
        *,
        at: datetime | None = None,
    ) -> None:
        """The only way an entry enters this log -- there is no
        corresponding mutate or delete method anywhere in this class."""
        self._entries.append(
            SurveillanceEntry(order, decision, reason, actor, at or datetime.now(UTC))
        )

    @property
    def entries(self) -> tuple[SurveillanceEntry, ...]:
        return tuple(self._entries)
