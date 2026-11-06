"""DAT-09: "enforce train/validation/test temporal partition on
features... automated leakage linter catches future timestamps."

`econosim.pit`'s `build_feature_vector`/`require_eligible` already fail
closed, AT ACCESS TIME, for a caller that goes through them (FP-03's
"no-future-data fixture"). This module is the complementary, DETECTIVE
half: an automated linter run over a BATCH of (feature_id, data_as_of,
decision_time) usage records -- however they were produced, whether or
not the original code even went through `econosim.pit` -- that flags
every one where data became available strictly after the decision it
was used in. It exists because a live, access-time gate only protects
callers that call it; an after-the-fact audit of what a completed run
actually used is a genuine, independent safety net, not a restatement
of the same check.

`lint_future_timestamp_usage` is the general-purpose core (any
"timestamp vs. decision time" pair, independent of the PIT store).
`lint_pit_store_usage` adapts it to `PointInTimeStore`, re-deriving
eligibility through the store's own public `as_of` predicate -- the
SAME one `require_eligible`/`build_feature_vector` already gate on
live -- rather than reaching into the store's internal records
directly: `PointInTimeStore`'s own docstring is explicit that it
deliberately exposes no "give me everything regardless of date"
accessor, precisely so a caller cannot bypass the point-in-time rule,
and an audit tool is not an exception to that -- it earns its answer
through the same gate every other caller must.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from prometheus.econosim.pit import PointInTimeStore


@dataclass(frozen=True, slots=True)
class LeakageViolation:
    feature_id: str
    decision_time: date
    detail: str

    def __str__(self) -> str:
        return f"{self.feature_id!r} at decision_time {self.decision_time}: {self.detail}"


@dataclass(frozen=True, slots=True)
class LeakageLintReport:
    violations: tuple[LeakageViolation, ...]
    n_checked: int

    @property
    def clean(self) -> bool:
        return len(self.violations) == 0


def lint_future_timestamp_usage(
    usages: Sequence[tuple[str, date, date]],
) -> LeakageLintReport:
    """Each usage is (feature_id, data_as_of, decision_time): flags every
    one where data_as_of > decision_time -- data used in a decision made
    before that data existed."""
    violations = tuple(
        LeakageViolation(
            feature_id=feature_id,
            decision_time=decision_time,
            detail=(
                f"data as-of {data_as_of} is strictly after its decision "
                f"time {decision_time} -- used before it existed"
            ),
        )
        for feature_id, data_as_of, decision_time in usages
        if data_as_of > decision_time
    )
    return LeakageLintReport(violations=violations, n_checked=len(usages))


def lint_pit_store_usage(
    store: PointInTimeStore,
    requests: Sequence[tuple[str, date, date]],
) -> LeakageLintReport:
    """Each request is (series_id, observation_at, decision_time): flags
    every one where `store.as_of(series_id, observation_at,
    decision_time)` returns `None` -- nothing was eligible for that
    series/period as of that decision time, so any value a caller
    claims to have used for it could only have come from a future-dated
    (or never-recorded) source. An after-the-fact AUDIT of a batch of
    usage records, however they were produced, not a live gate."""
    violations = []
    for series_id, observation_at, decision_time in requests:
        if store.as_of(series_id, observation_at, decision_time) is None:
            violations.append(
                LeakageViolation(
                    feature_id=f"{series_id}@{observation_at.isoformat()}",
                    decision_time=decision_time,
                    detail=(
                        f"no vintage of {series_id!r} for period {observation_at} "
                        f"was eligible as of {decision_time}"
                    ),
                )
            )
    return LeakageLintReport(violations=tuple(violations), n_checked=len(requests))
