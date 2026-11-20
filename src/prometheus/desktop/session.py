"""One local user, one state directory, no network: the desktop application's job engine.

A `LocalSession` is the in-process equivalent of what `service.application` does over HTTP, and it
reuses the same parts rather than copying them:

- `JobStore` -- the transactional SQLite queue (idempotency, quotas, fenced leases, a hash-chained
  append-only audit log);
- `Worker` -- which never runs model code in the calling process: each job gets a fresh child
  process (`prometheus.jobs.child`) with a wall-clock timer, a CPU limit, a file-size limit, no
  core dumps, a scrubbed environment, and a parent-death signal so it cannot outlive the window;
- `ArtifactStore` -- content-addressed, no-clobber, and *verified on every read*: a result file
  that was edited after the fact is reported as such, never displayed.

What it adds is only a fixed local owner and presentation helpers. Because there is no HTTP layer
there is no token to steal and no port to reach; the isolation between the window and the model
code is the child-process boundary above, nothing weaker.

The queue policy below is a constant on purpose: `JobStore` persists the policy it was created with
and refuses to open a store whose stored policy differs, so changing it is a data migration, not a
setting.
"""

from __future__ import annotations

import os
import sys
import time
import uuid
from collections import Counter
from collections.abc import MutableMapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from prometheus.desktop import catalog
from prometheus.desktop.paths import ensure_private_directory
from prometheus.desktop.results import ResultView, build_result_view
from prometheus.evidence.export import export_evidence_bundle
from prometheus.jobs.artifacts import ArtifactError, ArtifactStore
from prometheus.jobs.store import TERMINAL, Job, JobStore, QueuePolicy
from prometheus.jobs.worker import Worker
from prometheus.orchestration.recipes import (
    PreparedRecipe,
    ResourceEstimate,
    ResourceLimits,
    prepare_recipe,
)

LOCAL_OWNER = "desktop"
DESKTOP_POLICY = QueuePolicy(
    max_pending_per_owner=32,
    max_pending_total=64,
    max_running_total=1,
    max_wall_seconds=1800.0,
)
"""One job at a time (the window shows one progress bar, and training saturates the machine),
up to half an hour of wall-clock each."""

THREAD_VARIABLES = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)


class JobsUnavailableError(RuntimeError):
    """Running jobs is not possible on this platform."""


class ResultUnavailableError(LookupError):
    """A job has no result to show, or its stored result failed verification."""


def configure_worker_environment(
    threads: int = 1, environ: MutableMapping[str, str] | None = None
) -> None:
    """Pin the math libraries' thread pools unless the user already chose a number.

    The child's CPU limit counts processor time summed over threads, so a job on a many-core
    machine would otherwise be killed `cores` times sooner than its wall-clock limit says; and one
    thread per pool is the setting every reference result in this repository was produced under
    (`.github/workflows/ci.yml` pins it for the same reason). Called once, at start-up, before any
    job is spawned; a value the user exported is left alone.
    """
    target = os.environ if environ is None else environ
    for name in THREAD_VARIABLES:
        target.setdefault(name, str(threads))


# Each estimate dimension and the limit it is admitted against: the same pairs, in the same
# words, as `orchestration.recipes._admit` (a test pins every pair to a real field on both sides).
ADMISSION_LIMITS = {
    "steps": "max_steps",
    "households": "max_households",
    "training_replicates": "max_training_replicates",
    "test_banks": "max_test_banks",
    "scenarios": "max_scenarios",
    "training_macro_banks": "max_training_macro_banks",
    "train_paths": "max_train_paths",
    "eval_paths": "max_eval_paths",
    "epochs": "max_epochs",
    "batch_size": "max_batch_size",
    "resamples": "max_resamples",
    "path_values": "max_path_values",
    "training_work": "max_training_work",
    "evaluation_work": "max_evaluation_work",
    "bootstrap_work": "max_bootstrap_work",
    "economic_work": "max_economic_work",
}


def heaviest_limit(
    estimate: ResourceEstimate, limits: ResourceLimits
) -> tuple[str, int, int] | None:
    """The estimate dimension closest to its admission limit, as `(name, value, limit)`; `None`
    when nothing is estimated at all."""
    best: tuple[str, int, int] | None = None
    for name, limit_name in ADMISSION_LIMITS.items():
        value, limit = int(getattr(estimate, name)), int(getattr(limits, limit_name))
        if value > 0 and (best is None or value / limit > best[1] / best[2]):
            best = (name, value, limit)
    return best


def admission_summary(estimate: ResourceEstimate, limits: ResourceLimits) -> str:
    """One sentence for a recipe that was admitted: how close it is to the nearest limit."""
    heaviest = heaviest_limit(estimate, limits)
    if heaviest is None:
        return "Admitted."
    name, value, limit = heaviest
    return (
        f"Admitted. Closest to a limit: {name.replace('_', ' ')} {value:,} of {limit:,} "
        f"({value / limit:.1%})."
    )


@dataclass(frozen=True, slots=True)
class JobSummary:
    """One job, ready to show."""

    job_id: str
    kind: str
    title: str
    status: str
    created: datetime
    elapsed_seconds: float
    attempts: int
    cancel_requested: bool
    has_result: bool
    error: str

    @property
    def short_id(self) -> str:
        return self.job_id[:8]

    @property
    def finished(self) -> bool:
        return self.status in TERMINAL


def summarize(job: Job, *, now_ns: int | None = None) -> JobSummary:
    """A job as display facts. A running job's elapsed time runs to `now_ns`; a finished one's
    stops at its last update."""
    end = job.updated_ns if job.status in TERMINAL or now_ns is None else now_ns
    try:
        title = catalog.info(job.kind).title
    except KeyError:
        title = job.kind
    return JobSummary(
        job_id=job.job_id,
        kind=job.kind,
        title=title,
        status=job.status,
        created=datetime.fromtimestamp(job.created_ns / 1e9, UTC).astimezone(),
        elapsed_seconds=max(0.0, (end - job.created_ns) / 1e9),
        attempts=job.attempts,
        cancel_requested=job.cancel_requested,
        has_result=job.artifact_sha256 is not None,
        error=catalog.describe_error(job.error_code),
    )


class LocalSession:
    """The job engine behind the window. Safe to call from the window's thread while a
    `WorkerLoop` runs in another: every store call opens its own SQLite connection."""

    def __init__(
        self,
        root: Path,
        *,
        owner: str = LOCAL_OWNER,
        policy: QueuePolicy = DESKTOP_POLICY,
        limits: ResourceLimits | None = None,
    ) -> None:
        self.root = ensure_private_directory(root)
        self.owner = owner
        self.store = JobStore(self.root / "jobs.sqlite3", policy=policy, limits=limits)
        self.artifacts = ArtifactStore(
            self.root / "artifacts",
            max_bytes=policy.max_artifact_bytes,
            max_total_bytes=policy.max_store_bytes,
        )
        self.worker: Worker | None = (
            Worker(self.store, self.artifacts, worker_id=f"desktop-{uuid.uuid4().hex}")
            if sys.platform == "linux"
            else None
        )

    @property
    def can_run_jobs(self) -> bool:
        return self.worker is not None

    # ------------------------------------------------------------------ submitting

    def validate(self, kind: str, config: dict[str, Any]) -> PreparedRecipe:
        """The recipe exactly as a submission would be judged: typed decoding, then the resource
        limits. Raises `ValueError` with a message fit to show."""
        return prepare_recipe(kind, config, limits=self.store.limits)

    def submit(
        self, kind: str, config: dict[str, Any], *, timeout_seconds: float | None = None
    ) -> Job:
        return self.store.submit(kind, config, owner=self.owner, timeout_seconds=timeout_seconds)

    def cancel(self, job_id: str) -> Job:
        """A queued job is cancelled at once; a running one is stopped by its worker within a
        fraction of a second."""
        return self.store.cancel(job_id, owner=self.owner)

    # ------------------------------------------------------------------ looking

    def get(self, job_id: str) -> Job:
        return self.store.get(job_id, owner=self.owner)

    def jobs(self, limit: int = 200) -> tuple[Job, ...]:
        """The newest `limit` jobs, newest first."""
        collected: list[Job] = []
        cursor: str | None = None
        while True:
            page, cursor = self.store.list_jobs(owner=self.owner, limit=100, cursor=cursor)
            collected.extend(page)
            if cursor is None:
                break
        return tuple(reversed(collected[-limit:]))

    def summaries(self, limit: int = 200) -> tuple[JobSummary, ...]:
        now = time.time_ns()
        return tuple(summarize(job, now_ns=now) for job in self.jobs(limit))

    def counts(self) -> dict[str, int]:
        return dict(Counter(job.status for job in self.jobs(10_000)))

    def audit_head(self) -> str:
        """Recompute the hash chain of every job event; raises `ValueError` if it is broken."""
        return self.store.verify_audit_chain()

    def storage_bytes(self) -> int:
        return self.artifacts.usage_bytes()

    # ------------------------------------------------------------------ working

    def work_once(self) -> Job | None:
        """Claim and run at most one queued job to completion (blocking)."""
        if self.worker is None:
            raise JobsUnavailableError(
                "running jobs needs Linux process controls; this platform cannot"
            )
        return self.worker.run_once()

    # ------------------------------------------------------------------ results

    def _verified_bundle(self, job_id: str) -> tuple[Job, dict[str, Any]]:
        job = self.get(job_id)
        if job.artifact_sha256 is None:
            raise ResultUnavailableError(f"this job has no result (it is {job.status})")
        try:
            bundle = self.artifacts.get(job.artifact_sha256)
        except ArtifactError as exc:
            raise ResultUnavailableError(f"the stored result failed verification: {exc}") from exc
        context = bundle.get("job_context")
        if not isinstance(context, dict) or context.get("job_id") != job.job_id:
            raise ResultUnavailableError("the stored result does not belong to this job")
        return job, bundle

    def result(self, job_id: str) -> ResultView:
        job, bundle = self._verified_bundle(job_id)
        return build_result_view(bundle, title=_title(job.kind))

    def export_result(self, job_id: str, destination: Path) -> Path:
        """Write the verified artifact (the exact bytes' content, re-serialised canonically) to
        `destination`; refuses to overwrite an existing file."""
        _, bundle = self._verified_bundle(job_id)
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(f"{destination} already exists; choose a new name")
        destination.parent.mkdir(parents=True, exist_ok=True)
        export_evidence_bundle(bundle, destination)
        return destination


def _title(kind: str) -> str:
    try:
        return catalog.info(kind).title
    except KeyError:
        return kind
