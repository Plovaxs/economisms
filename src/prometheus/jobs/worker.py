"""Single-host isolated workers: deadlines, cancellation and fenced publication.

Parent processes never call a model-training function. Each attempt uses a
fresh process and trusted fixed entry point. Shapes/work are admitted by
policy; hard wall/CPU/file bounds apply to the child. Hard RSS/cgroup limits
and authenticated network serving remain separate platform requirements.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

from prometheus.evidence.contracts import read_evidence_bundle, verified_payload
from prometheus.experiments.manifest import compute_result_hash, runtime_provenance
from prometheus.jobs.artifacts import ArtifactError, ArtifactStore
from prometheus.jobs.store import ERROR_CODES, Job, JobLease, JobStore, LeaseLost


def _child_environment() -> dict[str, str]:
    allowed = {
        "PATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "PYTHONPATH",
        "LD_LIBRARY_PATH",
        "TMPDIR",
        "OMP_NUM_THREADS",
        "OMP_DYNAMIC",
        "OMP_PROC_BIND",
        "OMP_PLACES",
        "MKL_NUM_THREADS",
        "MKL_DYNAMIC",
        "OPENBLAS_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "KMP_AFFINITY",
        "KMP_DUPLICATE_LIB_OK",
        "GOMP_CPU_AFFINITY",
        "CUDA_VISIBLE_DEVICES",
        "PYTHONHASHSEED",
    }
    return {name: value for name, value in os.environ.items() if name in allowed}


def _stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5.0)


class Worker:
    def __init__(self, store: JobStore, artifacts: ArtifactStore, *, worker_id: str) -> None:
        if sys.platform != "linux":
            raise ValueError("isolated workers require Linux parent-death process controls")
        if (
            artifacts.max_bytes != store.policy.max_artifact_bytes
            or artifacts.max_total_bytes != store.policy.max_store_bytes
        ):
            raise ValueError("worker artifact limits differ from the persisted queue policy")
        self.store, self.artifacts, self.worker_id = store, artifacts, worker_id
        self.staging = store.path.parent / "staging"
        self.staging.mkdir(mode=0o700, exist_ok=True)

    @staticmethod
    def _context(lease: JobLease) -> dict[str, object]:
        job = lease.job
        return {
            "schema_version": 1,
            "job_id": job.job_id,
            "trace_id": job.trace_id,
            "recipe_sha256": job.recipe_sha256,
            "attempt": job.attempts,
            "kind": job.kind,
        }

    def _accept_output(self, lease: JobLease, path: Path) -> Job:
        if path.stat().st_size > self.store.policy.max_artifact_bytes:
            raise ArtifactError("worker output exceeds configured artifact budget")
        bundle = read_evidence_bundle(path, require_integrity=True)
        kind, payload, _ = verified_payload(bundle, require_integrity=True)
        if kind != lease.job.kind or bundle.get("job_context") != self._context(lease):
            raise ArtifactError("worker output is not bound to the current job request")
        if bundle["runtime"] != lease.job.runtime:
            raise ArtifactError("worker output runtime differs from the submitted snapshot")
        current = self.store.heartbeat(lease)
        if current.cancel_requested:
            return self.store.finish(lease, "cancelled")
        artifact = self.artifacts.put(bundle)
        self.store.heartbeat(lease)
        if payload.get("valid") is False:
            return self.store.finish(
                lease,
                "failed",
                artifact_sha256=artifact.content_sha256,
                result_hash=artifact.result_hash,
                error_code="invalid_simulation",
            )
        return self.store.finish(
            lease,
            "succeeded",
            artifact_sha256=artifact.content_sha256,
            result_hash=artifact.result_hash,
        )

    def clean_staging(self) -> int:
        removed = 0
        for directory in self.staging.iterdir():
            match = re.fullmatch(r"([0-9a-f-]{36})-([0-9a-f]{32})-[a-z0-9_]+", directory.name)
            if match is None or directory.is_symlink() or not directory.is_dir():
                continue
            active = self.store.lease_activity(match[1], match[2])
            if active is False:
                shutil.rmtree(directory)
                removed += 1
        return removed

    def run_once(self) -> Job | None:
        self.store.recover_expired()
        self.clean_staging()
        lease = self.store.claim(self.worker_id)
        if lease is None:
            return None
        job = lease.job
        try:
            expected = compute_result_hash({"kind": job.kind, "config": job.config})
            if expected != job.recipe_sha256:
                return self.store.finish(lease, "failed", error_code="execution_rejected")
            if runtime_provenance() != job.runtime:
                return self.store.finish(lease, "failed", error_code="environment_mismatch")
            with tempfile.TemporaryDirectory(
                prefix=f"{job.job_id}-{lease.token}-", dir=self.staging
            ) as directory:
                root = Path(directory)
                request_path = root / "request.json"
                output = root / "result.json"
                request_path.write_text(
                    json.dumps(
                        {
                            "kind": job.kind,
                            "config": job.config,
                            "limits": asdict(self.store.limits),
                            "job_context": self._context(lease),
                        }
                    ),
                    encoding="utf-8",
                )
                command = [
                    sys.executable,
                    "-m",
                    "prometheus.jobs.child",
                    "--input",
                    str(request_path),
                    "--output",
                    str(output),
                    "--timeout",
                    str(job.timeout_seconds),
                    "--max-file-bytes",
                    str(self.store.policy.max_artifact_bytes),
                    "--parent-pid",
                    str(os.getpid()),
                ]
                deadline = time.monotonic() + job.timeout_seconds
                interval = min(0.1, self.store.policy.lease_seconds / 5)
                heartbeat_at = time.monotonic()
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                    env=_child_environment(),
                )
                try:
                    while True:
                        observed_job = self.store.get(job.job_id, owner=job.owner)
                        if (
                            observed_job.status != "running"
                            or observed_job.attempts != job.attempts
                        ):
                            raise LeaseLost("job attempt was superseded")
                        if observed_job.cancel_requested:
                            _stop(process)
                            return self.store.finish(lease, "cancelled")
                        if time.monotonic() >= heartbeat_at:
                            current = self.store.heartbeat(lease)
                            if current.cancel_requested:
                                _stop(process)
                                return self.store.finish(lease, "cancelled")
                            heartbeat_at = time.monotonic() + self.store.policy.lease_seconds / 3
                        if time.monotonic() >= deadline:
                            _stop(process)
                            return self.store.finish(lease, "timed_out", error_code="wall_timeout")
                        code = process.poll()
                        if code is not None:
                            break
                        time.sleep(interval)
                    current = self.store.heartbeat(lease)
                    if current.cancel_requested:
                        return self.store.finish(lease, "cancelled")
                    if code != 0:
                        if code in (-signal.SIGALRM, -signal.SIGXCPU):
                            return self.store.finish(
                                lease,
                                "timed_out",
                                error_code="cpu_timeout"
                                if code == -signal.SIGXCPU
                                else "wall_timeout",
                            )
                        error = "worker_failed"
                        error_path = output.with_suffix(".error.json")
                        if error_path.exists() and error_path.stat().st_size <= 1024:
                            try:
                                detail = read_evidence_bundle(error_path)
                                if detail.get("error_code") in ERROR_CODES:
                                    error = detail["error_code"]
                            except (ValueError, OSError, TypeError):
                                pass
                        return self.store.finish(lease, "failed", error_code=error)
                    return self._accept_output(lease, output)
                finally:
                    _stop(process)
        except LeaseLost:
            current = self.store.get(job.job_id, owner=job.owner)
            if current.status == "running" and current.cancel_requested:
                try:
                    return self.store.finish(lease, "cancelled")
                except LeaseLost:
                    pass
            return current
        except (ValueError, TypeError, OSError):
            try:
                return self.store.finish(lease, "failed", error_code="artifact_invalid")
            except LeaseLost:
                return self.store.get(job.job_id, owner=job.owner)
