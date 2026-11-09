"""Corrupt-data and point-in-time leak response: trace, revoke,
recompute (DRI-04: "Create corrupt-data and point-in-time leak
response"; acceptance criterion: "Affected runs traced, revoked and
recomputed").

Uses ONLY `econosim.pit.PointInTimeStore`'s own sanctioned `as_of`
query -- never bypassing its deliberate "no give me everything"
accessor, the same discipline `econosim.data_quality` (DAT-11)
already established for monitoring.

A `DataAccess` is what a run CLAIMS it used: which value, for which
series and observation date, as of which decision date. `detect_leak`
re-queries the store for what was ACTUALLY eligible at that same
`as_of` and compares -- a genuine mismatch (the run used a value that
was not yet eligible, or used ANY value when nothing should have been
eligible yet) is a real point-in-time leak, not a logging
discrepancy. `trace_affected_runs` sweeps a collection of `DataAccess`
entries, potentially from many runs, and reports exactly which
`run_id`s have at least one genuine leak.

`recompute` re-runs the caller's computation with the CORRECT,
store-sanctioned value from a `LeakFinding` in place of the leaked
run's own value -- confirmed in this module's tests to produce a
genuinely different (correct) result from the leaked run's own
(wrong) one, not merely re-executed with the same bad input.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import TypeVar

from prometheus.econosim.pit import PointInTimeStore

_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class DataAccess:
    run_id: str
    series_id: str
    observation_at: date
    as_of: date
    value_used: float


@dataclass(frozen=True, slots=True)
class LeakFinding:
    access: DataAccess
    correct_value: float | None
    reason: str


def detect_leak(access: DataAccess, store: PointInTimeStore) -> LeakFinding | None:
    eligible = store.as_of(access.series_id, access.observation_at, access.as_of)
    if eligible is None:
        return LeakFinding(
            access=access,
            correct_value=None,
            reason=(
                f"a value ({access.value_used}) was used for {access.series_id!r} as of "
                f"{access.as_of}, but nothing was eligible yet at that date"
            ),
        )
    if eligible.value != access.value_used:
        return LeakFinding(
            access=access,
            correct_value=eligible.value,
            reason=(
                f"used {access.value_used}, but only {eligible.value} was eligible for "
                f"{access.series_id!r} as of {access.as_of}"
            ),
        )
    return None


def trace_affected_runs(
    accesses: Sequence[DataAccess], store: PointInTimeStore
) -> frozenset[str]:
    return frozenset(
        access.run_id for access in accesses if detect_leak(access, store) is not None
    )


@dataclass(frozen=True, slots=True)
class RevokedRun:
    run_id: str
    reason: str
    owner: str
    revoked_at: date

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError("reason must not be empty")
        if not self.owner:
            raise ValueError("owner must not be empty")


def revoke_run(run_id: str, reason: str, *, owner: str, revoked_at: date) -> RevokedRun:
    return RevokedRun(run_id=run_id, reason=reason, owner=owner, revoked_at=revoked_at)


def recompute(finding: LeakFinding, compute_fn: Callable[[float], _T]) -> _T:
    if finding.correct_value is None:
        raise ValueError("cannot recompute: no eligible value exists to recompute with")
    return compute_fn(finding.correct_value)
