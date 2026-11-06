"""Agent and hedge decision audit log (AUD-05: "capture agent and
hedge decisions with timestamps"; acceptance criterion: "action follows
observed state in audit replay").

Deliberately domain-agnostic: `econosim` agents are timestamped by
calendar `date` (see `econosim.time_engine.Clock.current_date`), while
`hedging.online.OnlineHedgeAccount` is timestamped by a discrete,
`dt`-spaced step clock with no calendar mapping at all -- rather than
force one specific time type onto both (or, worse, silently assume
every caller is in one domain), every timestamp here is a single
`float` "clock reading" on whichever axis the caller's own domain uses,
as long as it is a single, globally comparable, monotonically
increasing number: a calendar date maps onto it via `date.toordinal()`,
a discrete hedging step via `step_index` (or `step_index * dt`) --
documented here, not reinvented per caller.

`DecisionLogEntry` records one action: who took it (`actor_id`), what
it was (`action`, a short description -- deliberately a free-form
string rather than a structured payload, since an agent's action and a
hedge policy's action have no shared schema), when the state it was
based on was OBSERVED (`observed_at`), and when the action was actually
DECIDED (`decided_at`). Construction does not itself reject a
causally-impossible entry (`decided_at < observed_at`) -- consistent
with `econosim.leakage_linter`'s own detective, not preventive, design:
an audit log's job is to faithfully record what a real system actually
did, including a violation if one genuinely occurred, not to make bad
history unconstructable. `audit_replay` is the actual verification
step: it returns every entry whose `decided_at` precedes its own
`observed_at` as a `CausalityViolation` -- "action follows observed
state in audit replay," confirmed by a separate, independent pass over
the log, not merely assumed from how entries were appended.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DecisionLogEntry:
    actor_id: str
    action: str
    observed_at: float
    decided_at: float

    def __post_init__(self) -> None:
        if not self.actor_id:
            raise ValueError("actor_id must not be empty")
        if not self.action:
            raise ValueError("action must not be empty")


@dataclass(frozen=True, slots=True)
class CausalityViolation:
    actor_id: str
    action: str
    observed_at: float
    decided_at: float

    def __str__(self) -> str:
        return (
            f"actor {self.actor_id!r} action {self.action!r}: decided_at "
            f"{self.decided_at} precedes observed_at {self.observed_at} -- this action "
            "was timestamped as having happened before the state it was based on "
            "was ever observed"
        )


def audit_replay(entries: Sequence[DecisionLogEntry]) -> list[CausalityViolation]:
    """Every entry in `entries` whose `decided_at` precedes its own
    `observed_at` -- an empty list means every action in the log
    genuinely followed the state it claims to have observed, replayed
    and confirmed, not merely assumed."""
    return [
        CausalityViolation(e.actor_id, e.action, e.observed_at, e.decided_at)
        for e in entries
        if e.decided_at < e.observed_at
    ]
