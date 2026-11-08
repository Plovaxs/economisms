from pathlib import Path

import pytest

from prometheus.evidence.queue_metrics import (
    QueueMetrics,
    QueueThresholds,
    classify_queue_health,
    compute_queue_metrics,
)
from prometheus.jobs.store import Job, JobStore
from prometheus.orchestration.recipes import default_recipe


class _Clock:
    def __init__(self) -> None:
        self.value = 1_000_000_000_000

    def __call__(self) -> int:
        self.value += 1
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += int(seconds * 1e9)


def _make_job(status: str, created_ns: int, updated_ns: int, job_id: str = "j") -> Job:
    return Job(
        job_id=job_id,
        owner="alice",
        trace_id="t",
        kind="economy",
        config_json="{}",
        recipe_sha256="0" * 64,
        runtime_json="{}",
        estimate_json="{}",
        status=status,
        created_ns=created_ns,
        updated_ns=updated_ns,
        attempts=1,
        cancel_requested=status == "cancelled",
        timeout_seconds=60.0,
        artifact_sha256=None,
        result_hash=None,
        error_code=None,
        diagnostic_id=None,
        version=1,
    )


def test_compute_queue_metrics_on_an_empty_queue() -> None:
    metrics = compute_queue_metrics([])
    assert metrics == QueueMetrics(
        queue_depth=0,
        running_count=0,
        cancellation_count=0,
        median_runtime_seconds=None,
        p95_runtime_seconds=None,
    )


def test_compute_queue_metrics_counts_each_status_independently() -> None:
    jobs = [
        _make_job("queued", 0, 0, "q1"),
        _make_job("queued", 0, 0, "q2"),
        _make_job("running", 0, 0, "r1"),
        _make_job("cancelled", 0, 0, "c1"),
        _make_job("succeeded", 0, 5_000_000_000, "s1"),
    ]
    metrics = compute_queue_metrics(jobs)
    assert metrics.queue_depth == 2
    assert metrics.running_count == 1
    assert metrics.cancellation_count == 1


def test_compute_queue_metrics_runtime_is_updated_minus_created_in_seconds() -> None:
    jobs = [_make_job("succeeded", 0, 5_000_000_000, "s1")]
    metrics = compute_queue_metrics(jobs)
    assert metrics.median_runtime_seconds == pytest.approx(5.0)
    assert metrics.p95_runtime_seconds == pytest.approx(5.0)


def test_compute_queue_metrics_cancelled_jobs_contribute_to_the_runtime_distribution_too() -> None:
    """A cancelled job is still TERMINAL -- it had a real lifespan in
    the system -- so it counts toward the runtime distribution AND is
    separately tallied as a cancellation, matching this item's literal
    three distinct measures."""
    jobs = [_make_job("cancelled", 0, 2_000_000_000, "c1")]
    metrics = compute_queue_metrics(jobs)
    assert metrics.cancellation_count == 1
    assert metrics.median_runtime_seconds == pytest.approx(2.0)


def test_compute_queue_metrics_queued_and_running_jobs_do_not_contribute_a_runtime() -> None:
    jobs = [_make_job("queued", 0, 0, "q1"), _make_job("running", 0, 0, "r1")]
    metrics = compute_queue_metrics(jobs)
    assert metrics.median_runtime_seconds is None
    assert metrics.p95_runtime_seconds is None


def test_queue_thresholds_rejects_warning_queue_depth_above_critical() -> None:
    with pytest.raises(ValueError, match="warning_queue_depth"):
        QueueThresholds(
            warning_queue_depth=10,
            critical_queue_depth=5,
            warning_p95_runtime_seconds=1.0,
            critical_p95_runtime_seconds=2.0,
        )


def test_queue_thresholds_rejects_warning_runtime_above_critical() -> None:
    with pytest.raises(ValueError, match="warning_p95_runtime_seconds"):
        QueueThresholds(
            warning_queue_depth=1,
            critical_queue_depth=2,
            warning_p95_runtime_seconds=10.0,
            critical_p95_runtime_seconds=5.0,
        )


_THRESHOLDS = QueueThresholds(
    warning_queue_depth=5,
    critical_queue_depth=10,
    warning_p95_runtime_seconds=30.0,
    critical_p95_runtime_seconds=120.0,
)


def test_classify_queue_health_ok_when_under_every_threshold() -> None:
    metrics = QueueMetrics(
        queue_depth=1, running_count=1, cancellation_count=0,
        median_runtime_seconds=1.0, p95_runtime_seconds=1.0,
    )
    assert classify_queue_health(metrics, _THRESHOLDS) == "ok"


def test_classify_queue_health_warning_on_queue_depth_alone() -> None:
    metrics = QueueMetrics(
        queue_depth=5, running_count=0, cancellation_count=0,
        median_runtime_seconds=1.0, p95_runtime_seconds=1.0,
    )
    assert classify_queue_health(metrics, _THRESHOLDS) == "warning"


def test_classify_queue_health_critical_on_queue_depth_alone() -> None:
    metrics = QueueMetrics(
        queue_depth=10, running_count=0, cancellation_count=0,
        median_runtime_seconds=1.0, p95_runtime_seconds=1.0,
    )
    assert classify_queue_health(metrics, _THRESHOLDS) == "critical"


def test_classify_queue_health_warning_on_runtime_alone_with_an_ok_queue_depth() -> None:
    metrics = QueueMetrics(
        queue_depth=0, running_count=0, cancellation_count=0,
        median_runtime_seconds=35.0, p95_runtime_seconds=35.0,
    )
    assert classify_queue_health(metrics, _THRESHOLDS) == "warning"


def test_classify_queue_health_critical_on_runtime_alone_even_with_empty_queue() -> None:
    metrics = QueueMetrics(
        queue_depth=0, running_count=0, cancellation_count=0,
        median_runtime_seconds=130.0, p95_runtime_seconds=130.0,
    )
    assert classify_queue_health(metrics, _THRESHOLDS) == "critical"


def test_classify_queue_health_worst_of_queue_depth_and_runtime() -> None:
    """Queue depth alone is only 'warning', but p95 runtime alone is
    'critical' -- the worse of the two must win."""
    metrics = QueueMetrics(
        queue_depth=5, running_count=0, cancellation_count=0,
        median_runtime_seconds=130.0, p95_runtime_seconds=130.0,
    )
    assert classify_queue_health(metrics, _THRESHOLDS) == "critical"


def test_classify_queue_health_a_none_p95_never_contributes_a_severity() -> None:
    """An empty/all-queued queue (no terminal jobs yet) must not be
    treated as a runtime problem just because there is no data."""
    metrics = QueueMetrics(
        queue_depth=0, running_count=0, cancellation_count=0,
        median_runtime_seconds=None, p95_runtime_seconds=None,
    )
    assert classify_queue_health(metrics, _THRESHOLDS) == "ok"


def test_real_job_store_lifecycle_produces_the_expected_metrics(tmp_path: Path) -> None:
    """Grounded against a REAL `JobStore`, not only hand-built `Job`
    fixtures: submit/claim/cancel/finish with a deterministic injected
    clock, confirming the metrics match exactly what that real
    lifecycle produced."""
    clock = _Clock()
    store = JobStore(tmp_path / "jobs.sqlite3", clock=clock)
    config = default_recipe("economy")

    store.submit("economy", config, owner="alice")  # job A
    clock.advance(1.0)
    lease_a = store.claim("worker-1")
    assert lease_a is not None
    clock.advance(10.0)
    store.finish(lease_a, "succeeded", artifact_sha256="a" * 64, result_hash="b" * 64)

    store.submit("economy", config, owner="alice")  # job B
    clock.advance(1.0)
    lease_b = store.claim("worker-1")
    assert lease_b is not None
    clock.advance(20.0)
    store.finish(lease_b, "succeeded", artifact_sha256="c" * 64, result_hash="d" * 64)

    cancelled = store.submit("economy", config, owner="alice")  # job C
    store.cancel(cancelled.job_id, owner="alice")

    store.submit("economy", config, owner="alice")  # job D, left queued
    store.submit("economy", config, owner="alice")  # job E
    assert store.claim("worker-2") is not None  # job E, left running

    jobs, _ = store.list_jobs(owner="alice", limit=100)
    assert len(jobs) == 5
    metrics = compute_queue_metrics(jobs)

    assert metrics.queue_depth == 1
    assert metrics.running_count == 1
    assert metrics.cancellation_count == 1
    assert metrics.median_runtime_seconds == pytest.approx(11.0, abs=0.01)
    assert metrics.p95_runtime_seconds == pytest.approx(20.0, abs=0.01)

    thresholds = QueueThresholds(
        warning_queue_depth=1,
        critical_queue_depth=5,
        warning_p95_runtime_seconds=15.0,
        critical_p95_runtime_seconds=100.0,
    )
    assert classify_queue_health(metrics, thresholds) == "warning"
