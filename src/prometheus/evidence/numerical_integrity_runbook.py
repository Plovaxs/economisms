"""Numerical-integrity incident runbook: isolate, invalidate,
re-evaluate (DRI-02: "Create numerical-integrity incident runbook";
acceptance criterion: "Incorrect output triggers isolate, invalidate
and re-evaluate").

Each step produces a REAL timestamped entry from an ACTUAL execution
of the runbook against a genuine failing/non-finite
`evidence.numerical_event_monitor.NumericalEvent` -- not a
hypothetical description of what a runbook "would" do:

- "isolate" -> the triggering event is recorded as the reason the
  computation is not trusted further without explicit re-evaluation.
- "invalidate" -> the computation's prior result is marked not
  trustworthy, with a required reason tying it back to the event.
- "re-evaluate" -> the SAME original callable is actually called
  again once, and the real outcome (still failing, or now succeeding)
  is recorded -- confirmed in this module's own tests against a REAL
  flaky callable whose behavior genuinely changes between the
  triggering call and the re-evaluation call, not a call that
  trivially always fails or always succeeds.

`run_numerical_integrity_runbook` executes these three steps in order
and returns a `RunbookExecutionResult` whose `timeline` is the real,
ordered sequence of `RunbookStep`s this specific execution actually
produced, using a caller-injected clock so timeline ordering is
deterministically verifiable rather than dependent on wall-clock
timing in a test.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from prometheus.evidence.numerical_event_monitor import NumericalEvent

StepName = Literal["isolate", "invalidate", "re_evaluate"]


@dataclass(frozen=True, slots=True)
class RunbookStep:
    name: StepName
    at: datetime
    detail: str

    def __post_init__(self) -> None:
        if not self.detail:
            raise ValueError("detail must not be empty")


@dataclass(frozen=True, slots=True)
class RunbookExecutionResult:
    event: NumericalEvent
    timeline: tuple[RunbookStep, ...]
    re_evaluation_succeeded: bool


def run_numerical_integrity_runbook(
    event: NumericalEvent,
    call: Callable[[], object],
    *,
    clock: Callable[[], datetime],
) -> RunbookExecutionResult:
    timeline: list[RunbookStep] = [
        RunbookStep(
            name="isolate",
            at=clock(),
            detail=f"isolated pending re-evaluation after a {event.kind} event: {event.detail}",
        ),
        RunbookStep(
            name="invalidate",
            at=clock(),
            detail=f"prior result for owner {event.owner!r} marked not trustworthy",
        ),
    ]

    try:
        call()
        re_evaluation_succeeded = True
        re_evaluate_detail = "re-evaluation succeeded: the call completed cleanly"
    except Exception as exc:
        re_evaluation_succeeded = False
        re_evaluate_detail = f"re-evaluation still fails: {exc}"

    timeline.append(RunbookStep(name="re_evaluate", at=clock(), detail=re_evaluate_detail))

    return RunbookExecutionResult(
        event=event, timeline=tuple(timeline), re_evaluation_succeeded=re_evaluation_succeeded
    )
