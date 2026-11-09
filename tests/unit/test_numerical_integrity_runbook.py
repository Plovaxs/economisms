from datetime import datetime, timedelta

import numpy as np
import pytest

from prometheus.evidence.numerical_event_monitor import monitor_call
from prometheus.evidence.numerical_integrity_runbook import (
    RunbookStep,
    run_numerical_integrity_runbook,
)
from prometheus.stochastica.gbm import simulate_gbm_paths


class _Clock:
    """A deterministic, strictly-incrementing clock so timeline
    ordering is verified exactly, not merely checked for 'some
    timestamps exist'."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> datetime:
        self.calls += 1
        return datetime(2026, 1, 1) + timedelta(seconds=self.calls)


def test_runbook_step_rejects_an_empty_detail() -> None:
    with pytest.raises(ValueError, match="detail"):
        RunbookStep(name="isolate", at=datetime(2026, 1, 1), detail="")


def test_a_genuinely_flaky_call_recovers_on_re_evaluation() -> None:
    """Grounded against a REAL callable whose behavior genuinely
    changes between the triggering call and the re-evaluation call --
    not a call that trivially always fails or always succeeds."""
    state = {"calls": 0}

    def flaky() -> None:
        state["calls"] += 1
        if state["calls"] <= 1:
            raise RuntimeError("transient failure")

    event = monitor_call(flaky, owner="quant-oncall")
    assert event is not None  # sanity: the triggering call really did fail
    assert event.kind == "solver_failure"

    clock = _Clock()
    result = run_numerical_integrity_runbook(event, flaky, clock=clock)

    assert result.re_evaluation_succeeded is True
    assert [step.name for step in result.timeline] == ["isolate", "invalidate", "re_evaluate"]
    assert "succeeded" in result.timeline[-1].detail


def test_a_persistently_failing_call_still_fails_on_re_evaluation() -> None:
    """Grounded against this repository's own REAL extreme-drift GBM
    guard (the same one `test_gbm.py`/`test_numerical_event_monitor.py`
    already confirm raises a clear error): re-evaluation genuinely
    still fails, because the underlying parameter combination has no
    computable answer, not because the runbook assumed it would."""
    rng = np.random.default_rng(0)

    def always_fails() -> np.ndarray:
        return simulate_gbm_paths(100.0, 1e300, 0.2, 1.0, n_steps=10, n_paths=10, rng=rng)

    event = monitor_call(always_fails, owner="quant-oncall")
    assert event is not None
    assert event.kind == "solver_failure"

    clock = _Clock()
    result = run_numerical_integrity_runbook(event, always_fails, clock=clock)

    assert result.re_evaluation_succeeded is False
    assert "still fails" in result.timeline[-1].detail


def test_the_timeline_is_in_strictly_increasing_chronological_order() -> None:
    clock = _Clock()

    def succeeds() -> None:
        return None

    event = monitor_call(lambda: (_ for _ in ()).throw(RuntimeError("x")), owner="t")
    assert event is not None
    result = run_numerical_integrity_runbook(event, succeeds, clock=clock)

    timestamps = [step.at for step in result.timeline]
    assert timestamps == sorted(timestamps)
    assert len(set(timestamps)) == len(timestamps)  # strictly increasing, no ties
    assert clock.calls == 3  # exactly one clock read per step, no extras


def test_isolate_and_invalidate_steps_reference_the_real_triggering_event() -> None:
    event = monitor_call(lambda: (_ for _ in ()).throw(ValueError("bad input")), owner="risk-lead")
    assert event is not None
    clock = _Clock()
    result = run_numerical_integrity_runbook(event, lambda: None, clock=clock)

    isolate_step = result.timeline[0]
    assert event.kind in isolate_step.detail
    assert "risk-lead" in result.timeline[1].detail
    assert result.event == event
