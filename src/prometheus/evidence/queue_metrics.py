"""Job queue depth, runtime and cancellation metrics with warning/
critical thresholds (OPS-04: "Measure job queue depth, runtimes and
cancellation count"; acceptance criterion: "Metrics dashboard with
warning/critical thresholds").

`compute_queue_metrics` takes a `Sequence[jobs.store.Job]` -- the SAME
real, already-persisted job records `JobStore.list_jobs` returns --
rather than querying storage itself, the same "measure from
already-constructed data" separation `experiments.latency_benchmark`
already uses for its own load reports. "Runtime" is each TERMINAL job's
`updated_ns - created_ns`: total time in the system until it reached a
final state (`succeeded`/`failed`/`cancelled`/`timed_out`), not merely
time spent actively running, since that is what `Job`'s own two real
timestamp fields can honestly support without inventing a third,
unrecorded one. `cancellation_count` is reported separately, matching
this item's literal three-part "queue depth, runtimes and cancellation
count," not folded into the runtime distribution's meaning.

Confirmed against a REAL `JobStore` lifecycle (submit, claim, cancel,
finish) with a deterministic injected clock, not only hand-built `Job`
fixtures: a queued, a running, a cancelled, and two succeeded jobs with
distinct real elapsed times produce exactly the queue depth, running
count, cancellation count and runtime percentiles the lifecycle
actually produced.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np

from prometheus.jobs.store import TERMINAL, Job

Severity = Literal["ok", "warning", "critical"]


@dataclass(frozen=True, slots=True)
class QueueMetrics:
    queue_depth: int
    running_count: int
    cancellation_count: int
    median_runtime_seconds: float | None
    p95_runtime_seconds: float | None


@dataclass(frozen=True, slots=True)
class QueueThresholds:
    warning_queue_depth: int
    critical_queue_depth: int
    warning_p95_runtime_seconds: float
    critical_p95_runtime_seconds: float

    def __post_init__(self) -> None:
        if self.warning_queue_depth > self.critical_queue_depth:
            raise ValueError("warning_queue_depth must not exceed critical_queue_depth")
        if self.warning_p95_runtime_seconds > self.critical_p95_runtime_seconds:
            raise ValueError(
                "warning_p95_runtime_seconds must not exceed critical_p95_runtime_seconds"
            )


def compute_queue_metrics(jobs: Sequence[Job]) -> QueueMetrics:
    queue_depth = sum(1 for job in jobs if job.status == "queued")
    running_count = sum(1 for job in jobs if job.status == "running")
    cancellation_count = sum(1 for job in jobs if job.status == "cancelled")
    runtimes_seconds = [
        (job.updated_ns - job.created_ns) / 1e9 for job in jobs if job.status in TERMINAL
    ]
    median = float(np.percentile(runtimes_seconds, 50)) if runtimes_seconds else None
    p95 = float(np.percentile(runtimes_seconds, 95)) if runtimes_seconds else None
    return QueueMetrics(
        queue_depth=queue_depth,
        running_count=running_count,
        cancellation_count=cancellation_count,
        median_runtime_seconds=median,
        p95_runtime_seconds=p95,
    )


def classify_queue_health(metrics: QueueMetrics, thresholds: QueueThresholds) -> Severity:
    """Worst-of: queue depth and p95 runtime are each classified
    independently against `thresholds`, and the more severe of the two
    wins. A `None` p95 (no terminal jobs yet) never contributes a
    severity -- an empty queue is not evidence of a problem."""
    severity: Severity = "ok"
    if metrics.queue_depth >= thresholds.critical_queue_depth:
        severity = "critical"
    elif metrics.queue_depth >= thresholds.warning_queue_depth:
        severity = "warning"

    if metrics.p95_runtime_seconds is not None:
        if metrics.p95_runtime_seconds >= thresholds.critical_p95_runtime_seconds:
            severity = "critical"
        elif (
            metrics.p95_runtime_seconds >= thresholds.warning_p95_runtime_seconds
            and severity == "ok"
        ):
            severity = "warning"
    return severity
