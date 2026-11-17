"""EXT-05: "implement market access permission separation and kill
switch" / "trading pathway defaults disabled and can be halted
externally." Modeled directly on
`econosim.monetary_operations.MonetaryOperationsStepHooks`'s existing
`_risk_frozen` one-way circuit breaker (PR-036): "set once... and never
automatically cleared." There is no corresponding `untrip`/`reset`/
`clear` method anywhere in this class -- not merely unused, absent --
so once tripped, a `KillSwitch` cannot be un-tripped by any code this
package defines.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class TripEvent:
    reason: str
    at: datetime


class KillSwitchTrippedError(ValueError):
    """Raised by `KillSwitch.check` once tripped -- call this before any
    gated operation (an order submission, arming `signoff_gate`)."""


@dataclass(slots=True)
class KillSwitch:
    _trips: list[TripEvent] = field(default_factory=list, init=False)

    @property
    def is_tripped(self) -> bool:
        return len(self._trips) > 0

    @property
    def trips(self) -> tuple[TripEvent, ...]:
        """The complete, append-only trip history -- not just the first
        or most recent cause. Tripping twice is idempotent with respect
        to `is_tripped` (stays `True`); it is not idempotent with
        respect to this history, which records every call."""
        return tuple(self._trips)

    def trip(self, reason: str, *, at: datetime | None = None) -> None:
        if not reason:
            raise ValueError("reason must not be empty")
        self._trips.append(TripEvent(reason, at or datetime.now(UTC)))

    def check(self) -> None:
        if self.is_tripped:
            first = self._trips[0]
            raise KillSwitchTrippedError(
                f"trading pathway is tripped ({len(self._trips)} trip event(s)); "
                f"first cause: {first.reason!r} at {first.at.isoformat()}"
            )
