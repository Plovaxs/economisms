"""Transactional local research queue with idempotency and fenced worker leases.

SQLite rollback journaling + FULL synchronous commits; single-host only.
Hash-chained append-only events are consistency evidence, not signatures or
protection from a privileged database owner rewriting/truncating the file.
"""

from __future__ import annotations

import base64
import json
import math
import os
import re
import sqlite3
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from prometheus.evidence.integrity import is_sha256
from prometheus.evidence.jsonio import strict_json_loads
from prometheus.experiments.manifest import compute_result_hash, runtime_provenance
from prometheus.orchestration.recipes import ResourceLimits, prepare_recipe

TERMINAL = frozenset({"succeeded", "failed", "cancelled", "timed_out"})
STATUSES = TERMINAL | {"queued", "running"}
ERROR_CODES = frozenset(
    {
        "worker_failed",
        "invalid_simulation",
        "environment_mismatch",
        "wall_timeout",
        "lease_expired",
        "artifact_invalid",
        "execution_rejected",
        "model_error",
        "infrastructure_error",
        "cpu_timeout",
        "restore_interrupted",
    }
)


class JobError(ValueError):
    pass


class JobNotFound(JobError):
    pass


class JobStorageError(JobError):
    pass


class IdempotencyConflict(JobError):
    pass


class QuotaExceeded(JobError):
    pass


class LeaseLost(JobError):
    pass


def _label(value: str, name: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9._:@-]{1,128}", value) is None:
        raise JobError(f"{name} requires a bounded opaque identifier")


@dataclass(frozen=True, slots=True)
class QueuePolicy:
    max_pending_per_owner: int = 16
    max_pending_total: int = 128
    max_running_total: int = 2
    max_attempts: int = 3
    lease_seconds: float = 30.0
    max_wall_seconds: float = 300.0
    max_artifact_bytes: int = 134_217_728
    max_store_bytes: int = 1_073_741_824

    def __post_init__(self) -> None:
        for name in (
            "max_pending_per_owner",
            "max_pending_total",
            "max_running_total",
            "max_attempts",
            "max_artifact_bytes",
            "max_store_bytes",
        ):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError("queue capacities must be positive integers")
        for value in (self.lease_seconds, self.max_wall_seconds):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0.3 <= value <= 86_400
            ):
                raise ValueError("lease/wall limits must be finite seconds in [.3,86400]")
        if self.max_running_total > self.max_pending_total:
            raise ValueError("running capacity cannot exceed total pending capacity")


@dataclass(frozen=True, slots=True)
class Job:
    job_id: str
    owner: str
    trace_id: str
    kind: str
    config_json: str
    recipe_sha256: str
    runtime_json: str
    estimate_json: str
    status: str
    created_ns: int
    updated_ns: int
    attempts: int
    cancel_requested: bool
    timeout_seconds: float
    artifact_sha256: str | None
    result_hash: str | None
    error_code: str | None
    diagnostic_id: str | None
    version: int

    @property
    def config(self) -> dict[str, Any]:
        result: dict[str, Any] = strict_json_loads(self.config_json)
        return result

    @property
    def runtime(self) -> dict[str, Any]:
        result: dict[str, Any] = strict_json_loads(self.runtime_json)
        return result


def _job(row: sqlite3.Row) -> Job:
    values = {name: row[name] for name in Job.__dataclass_fields__}
    values["cancel_requested"] = bool(values["cancel_requested"])
    return Job(**values)


@dataclass(frozen=True, slots=True)
class JobLease:
    job: Job
    token: str


class JobStore:
    def __init__(
        self,
        path: Path,
        *,
        policy: QueuePolicy | None = None,
        limits: ResourceLimits | None = None,
        clock: Callable[[], int] = time.time_ns,
    ) -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.policy, self.limits, self.clock = (
            policy or QueuePolicy(),
            limits or ResourceLimits(),
            clock,
        )
        with self._transaction() as connection:
            if connection.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
                raise JobError("local job store requires rollback journal mode")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise JobError("unsupported job database schema version")
            if version == 0:
                if connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchone():
                    raise JobError("refusing to initialize an unrelated database")
                statements = [
                    """CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)""",
                    """CREATE TABLE jobs (
                      job_id TEXT PRIMARY KEY, owner TEXT NOT NULL, trace_id TEXT NOT NULL,
                      kind TEXT NOT NULL, config_json TEXT NOT NULL, recipe_sha256 TEXT NOT NULL,
                      runtime_json TEXT NOT NULL, estimate_json TEXT NOT NULL,
                      status TEXT NOT NULL CHECK(status IN (
                        'queued','running','succeeded','failed','cancelled','timed_out')),
                      created_ns INTEGER NOT NULL, updated_ns INTEGER NOT NULL,
                      attempts INTEGER NOT NULL DEFAULT 0,
                      cancel_requested INTEGER NOT NULL DEFAULT 0, timeout_seconds REAL NOT NULL,
                      artifact_sha256 TEXT, result_hash TEXT, error_code TEXT, diagnostic_id TEXT,
                      version INTEGER NOT NULL DEFAULT 0, lease_token TEXT,
                      lease_expires_ns INTEGER,
                      worker_id TEXT, idempotency_key TEXT, request_sha256 TEXT NOT NULL,
                      UNIQUE(owner,idempotency_key))""",
                    """CREATE INDEX queue_order ON jobs(status,created_ns,job_id)""",
                    """CREATE TABLE events (seq INTEGER PRIMARY KEY AUTOINCREMENT,
                      job_id TEXT NOT NULL REFERENCES jobs(job_id), body_json TEXT NOT NULL,
                      previous_sha256 TEXT NOT NULL, event_sha256 TEXT NOT NULL)""",
                    "CREATE TRIGGER events_no_update BEFORE UPDATE ON events "
                    "BEGIN SELECT RAISE(ABORT,'audit events are append-only'); END",
                    "CREATE TRIGGER events_no_delete BEFORE DELETE ON events "
                    "BEGIN SELECT RAISE(ABORT,'audit events are append-only'); END",
                ]
                for statement in statements:
                    connection.execute(statement)
                connection.execute("PRAGMA user_version=1")
                connection.execute(
                    "INSERT INTO settings VALUES (?,?)", ("policy", self._policy_json())
                )
            stored = connection.execute(
                "SELECT value FROM settings WHERE key=?", ("policy",)
            ).fetchone()
            if stored is None or stored[0] != self._policy_json():
                raise JobError(
                    "job-store policy differs; an explicit migration/new store is required"
                )

        os.chmod(self.path, 0o600)

    def _policy_json(self) -> str:
        return json.dumps(
            {"queue": asdict(self.policy), "resources": asdict(self.limits)}, sort_keys=True
        )

    def check_ready(self) -> None:
        """Probe existing schema/policy and writer admission without creating or mutating state."""
        connection = None
        try:
            connection = sqlite3.connect(
                self.path.as_uri() + "?mode=rw", uri=True, timeout=0.25, isolation_level=None
            )
            connection.execute("BEGIN IMMEDIATE")
            stored = connection.execute(
                "SELECT value FROM settings WHERE key=?", ("policy",)
            ).fetchone()
            if (
                connection.execute("PRAGMA user_version").fetchone()[0] != 1
                or connection.execute("PRAGMA journal_mode").fetchone()[0] != "delete"
                or stored is None
                or stored[0] != self._policy_json()
            ):
                raise JobStorageError("job-store schema/policy is not ready")
            connection.execute("SELECT job_id FROM jobs LIMIT 1").fetchone()
            connection.execute("SELECT seq FROM events LIMIT 1").fetchone()
        except sqlite3.Error as exc:
            raise JobStorageError("job-store readiness probe failed") from exc
        finally:
            if connection is not None:
                connection.close()  # Roll back the probe's transaction, including on failure.

    def _connect(self) -> sqlite3.Connection:
        connection = None
        try:
            connection = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA synchronous=FULL")
            return connection
        except sqlite3.Error as exc:
            if connection is not None:
                connection.close()
            raise JobStorageError("job database is unavailable") from exc

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except sqlite3.Error as exc:
            connection.rollback()
            raise JobStorageError("job database transaction failed") from exc
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _now(self) -> int:
        now = self.clock()
        if type(now) is not int or not 0 <= now < 2**63:
            raise JobError("clock must return nonnegative int64 UTC nanoseconds")
        return now

    def _event(
        self,
        connection: sqlite3.Connection,
        job: Job,
        kind: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        last = connection.execute(
            "SELECT event_sha256 FROM events ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        previous = last[0] if last else "0" * 64
        body = {
            "job_id": job.job_id,
            "trace_id": job.trace_id,
            "owner": job.owner,
            "event": kind,
            "status": job.status,
            "version": job.version,
            "attempts": job.attempts,
            "cancel_requested": job.cancel_requested,
            "time_ns": job.updated_ns,
            "details": dict(details or {}),
        }
        digest = compute_result_hash({"previous_sha256": previous, "event": body})
        connection.execute(
            "INSERT INTO events(job_id,body_json,previous_sha256,event_sha256) VALUES (?,?,?,?)",
            (job.job_id, json.dumps(body, sort_keys=True), previous, digest),
        )

    def submit(
        self,
        kind: str,
        config: Mapping[str, Any],
        *,
        owner: str,
        idempotency_key: str | None = None,
        timeout_seconds: float | None = None,
    ) -> Job:
        _label(owner, "owner")
        if idempotency_key is not None:
            _label(idempotency_key, "idempotency key")
        timeout = self.policy.max_wall_seconds if timeout_seconds is None else timeout_seconds
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or not 0.05 <= timeout <= self.policy.max_wall_seconds
        ):
            raise JobError("timeout must be finite seconds within the configured wall budget")
        prepared = prepare_recipe(kind, config, limits=self.limits)
        request_hash = compute_result_hash(
            {"recipe_sha256": prepared.recipe_sha256, "timeout_seconds": float(timeout)}
        )
        runtime_json = json.dumps(runtime_provenance(), sort_keys=True)
        with self._transaction() as connection:
            if idempotency_key is not None:
                previous = connection.execute(
                    "SELECT * FROM jobs WHERE owner=? AND idempotency_key=?",
                    (owner, idempotency_key),
                ).fetchone()
                if previous is not None:
                    if previous["request_sha256"] != request_hash:
                        raise IdempotencyConflict(
                            "idempotency key already identifies a different request"
                        )
                    return _job(previous)
            counts = connection.execute(
                "SELECT COUNT(*),SUM(owner=?) FROM jobs WHERE status IN ('queued','running')",
                (owner,),
            ).fetchone()
            if (
                counts[0] >= self.policy.max_pending_total
                or (counts[1] or 0) >= self.policy.max_pending_per_owner
            ):
                raise QuotaExceeded("pending job capacity reached")
            now = self._now()
            identifier, trace = str(uuid.uuid4()), uuid.uuid4().hex
            connection.execute(
                """INSERT INTO jobs(job_id,owner,trace_id,kind,config_json,recipe_sha256,
                runtime_json,estimate_json,status,created_ns,updated_ns,timeout_seconds,idempotency_key,request_sha256)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    identifier,
                    owner,
                    trace,
                    kind,
                    prepared.canonical_json,
                    prepared.recipe_sha256,
                    runtime_json,
                    json.dumps(asdict(prepared.estimate), sort_keys=True),
                    "queued",
                    now,
                    now,
                    float(timeout),
                    idempotency_key,
                    request_hash,
                ),
            )
            job = self._get(connection, identifier)
            self._event(
                connection,
                job,
                "submitted",
                {
                    "recipe_sha256": job.recipe_sha256,
                    "runtime_sha256": compute_result_hash(job.runtime),
                    "request_sha256": request_hash,
                    "estimate_sha256": compute_result_hash(strict_json_loads(job.estimate_json)),
                },
            )
            return job

    def _get(
        self, connection: sqlite3.Connection, identifier: str, owner: str | None = None
    ) -> Job:
        if not isinstance(identifier, str) or len(identifier) != 36:
            raise JobNotFound("job not found")
        row = connection.execute(
            "SELECT * FROM jobs WHERE job_id=?" + (" AND owner=?" if owner is not None else ""),
            (identifier, owner) if owner is not None else (identifier,),
        ).fetchone()
        if row is None:
            raise JobNotFound("job not found")
        return _job(row)

    def get(self, identifier: str, *, owner: str) -> Job:
        _label(owner, "owner")
        connection = self._connect()
        try:
            return self._get(connection, identifier, owner)
        except sqlite3.Error as exc:
            raise JobStorageError("job database read failed") from exc
        finally:
            connection.close()

    def lease_activity(self, identifier: str, token: str) -> bool | None:
        """Worker-only staging cleanup check; None means an unknown job."""
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT status,lease_token,lease_expires_ns FROM jobs WHERE job_id=?", (identifier,)
            ).fetchone()
            if row is None:
                return None
            return bool(
                row["status"] == "running"
                and row["lease_token"] == token
                and row["lease_expires_ns"] > self._now()
            )
        except sqlite3.Error as exc:
            raise JobStorageError("job lease storage is unavailable") from exc
        finally:
            connection.close()

    def claim(self, worker_id: str) -> JobLease | None:
        _label(worker_id, "worker id")
        with self._transaction() as connection:
            if (
                connection.execute("SELECT COUNT(*) FROM jobs WHERE status='running'").fetchone()[0]
                >= self.policy.max_running_total
            ):
                return None
            row = connection.execute(
                "SELECT * FROM jobs WHERE status='queued' ORDER BY created_ns,job_id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            now, token = self._now(), uuid.uuid4().hex
            expires = now + int(self.policy.lease_seconds * 1e9)
            connection.execute(
                "UPDATE jobs SET status='running',attempts=attempts+1,version=version+1,"
                "updated_ns=?,lease_token=?,lease_expires_ns=?,worker_id=? "
                "WHERE job_id=? AND status='queued'",
                (now, token, expires, worker_id, row["job_id"]),
            )
            job = self._get(connection, row["job_id"])
            self._event(
                connection, job, "claimed", {"worker_id": worker_id, "attempt": job.attempts}
            )
            return JobLease(job, token)

    def _leased(self, connection: sqlite3.Connection, lease: JobLease) -> Job:
        row = connection.execute(
            "SELECT * FROM jobs WHERE job_id=?", (lease.job.job_id,)
        ).fetchone()
        if (
            row is None
            or row["status"] != "running"
            or row["lease_token"] != lease.token
            or row["lease_expires_ns"] <= self._now()
        ):
            raise LeaseLost("worker lease is no longer current")
        return _job(row)

    def heartbeat(self, lease: JobLease) -> Job:
        with self._transaction() as connection:
            job = self._leased(connection, lease)
            now = self._now()
            connection.execute(
                "UPDATE jobs SET lease_expires_ns=?,updated_ns=? WHERE job_id=?",
                (now + int(self.policy.lease_seconds * 1e9), now, job.job_id),
            )
            return self._get(connection, job.job_id)

    def cancel(self, identifier: str, *, owner: str) -> Job:
        _label(owner, "owner")
        with self._transaction() as connection:
            job = self._get(connection, identifier, owner)
            if job.status in TERMINAL or job.cancel_requested:
                return job
            status = "cancelled" if job.status == "queued" else "running"
            connection.execute(
                "UPDATE jobs SET status=?,cancel_requested=1,updated_ns=?,version=version+1 "
                "WHERE job_id=?",
                (status, self._now(), identifier),
            )
            job = self._get(connection, identifier)
            self._event(
                connection, job, "cancelled" if status == "cancelled" else "cancellation_requested"
            )
            return job

    def finish(
        self,
        lease: JobLease,
        status: str,
        *,
        artifact_sha256: str | None = None,
        result_hash: str | None = None,
        error_code: str | None = None,
    ) -> Job:
        if status not in TERMINAL:
            raise JobError("finish requires a terminal status")
        if (artifact_sha256 is None) != (result_hash is None) or any(
            v is not None and not is_sha256(v) for v in (artifact_sha256, result_hash)
        ):
            raise JobError("artifact/result fingerprints must be paired SHA-256 values")
        if status == "succeeded" and (artifact_sha256 is None or error_code is not None):
            raise JobError("successful jobs require an artifact and no error")
        if error_code is not None and error_code not in ERROR_CODES:
            raise JobError("unsupported structured error code")
        if status == "cancelled" and (artifact_sha256 is not None or error_code is not None):
            raise JobError("cancelled jobs cannot publish an artifact/error")
        if status in ("failed", "timed_out") and error_code not in ERROR_CODES:
            raise JobError("failed jobs require a supported structured error code")
        with self._transaction() as connection:
            job = self._leased(connection, lease)
            if job.cancel_requested and status != "cancelled":
                raise LeaseLost("cancellation request fences completion")
            if status == "cancelled" and not job.cancel_requested:
                raise JobError("cancelled completion requires a cancellation request")
            diagnostic = uuid.uuid4().hex if error_code is not None else None
            connection.execute(
                """UPDATE jobs SET status=?,artifact_sha256=?,result_hash=?,error_code=?,
                diagnostic_id=?,updated_ns=?,version=version+1,lease_token=NULL,
                lease_expires_ns=NULL,worker_id=NULL WHERE job_id=?""",
                (
                    status,
                    artifact_sha256,
                    result_hash,
                    error_code,
                    diagnostic,
                    self._now(),
                    job.job_id,
                ),
            )
            job = self._get(connection, job.job_id)
            self._event(
                connection,
                job,
                "finished",
                {
                    "artifact_sha256": artifact_sha256,
                    "result_hash": result_hash,
                    "error_code": error_code,
                    "diagnostic_id": diagnostic,
                },
            )
            return job

    def recover_expired(self) -> int:
        return self._recover_leases()

    def recover_after_restore(self, *, snapshot_sha256: str, expected_head: str) -> int:
        """Fence every copied lease in a private restored store before it is published."""
        if not is_sha256(snapshot_sha256) or not is_sha256(expected_head):
            raise JobError("restore requires snapshot and audit-head SHA-256 identities")
        return self._recover_leases(snapshot_sha256=snapshot_sha256, expected_head=expected_head)

    def _recover_leases(
        self, *, snapshot_sha256: str | None = None, expected_head: str | None = None
    ) -> int:
        with self._transaction() as connection:
            if expected_head is not None:
                last = connection.execute(
                    "SELECT event_sha256 FROM events ORDER BY seq DESC LIMIT 1"
                ).fetchone()
                if (last[0] if last else "0" * 64) != expected_head:
                    raise JobError("restore audit head changed before lease fencing")
            now = self._now()
            rows = connection.execute(
                "SELECT * FROM jobs WHERE status='running' "
                "AND (? IS NOT NULL OR lease_expires_ns<=?) "
                "ORDER BY created_ns,job_id",
                (snapshot_sha256, now),
            ).fetchall()
            for row in rows:
                status = (
                    "cancelled"
                    if row["cancel_requested"]
                    else "failed"
                    if row["attempts"] >= self.policy.max_attempts
                    else "queued"
                )
                error, diagnostic = (
                    (
                        "restore_interrupted" if snapshot_sha256 else "lease_expired",
                        uuid.uuid4().hex,
                    )
                    if status == "failed"
                    else (None, None)
                )
                connection.execute(
                    """UPDATE jobs SET status=?,updated_ns=?,version=version+1,
                    error_code=?,diagnostic_id=?,
                    lease_token=NULL,lease_expires_ns=NULL,worker_id=NULL WHERE job_id=?""",
                    (status, now, error, diagnostic, row["job_id"]),
                )
                recovered = self._get(connection, row["job_id"])
                self._event(
                    connection,
                    recovered,
                    "lease_recovered",
                    {
                        "artifact_sha256": recovered.artifact_sha256,
                        "result_hash": recovered.result_hash,
                        "error_code": recovered.error_code,
                        "diagnostic_id": recovered.diagnostic_id,
                        **({"snapshot_sha256": snapshot_sha256} if snapshot_sha256 else {}),
                    },
                )
            return len(rows)

    def list_jobs(
        self, *, owner: str, limit: int = 50, cursor: str | None = None
    ) -> tuple[tuple[Job, ...], str | None]:
        _label(owner, "owner")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise JobError("page limit must be in [1,100]")
        after_time, after_id = -1, ""
        if cursor is not None:
            try:
                if not isinstance(cursor, str):
                    raise ValueError("cursor must be text")
                if len(cursor) > 1024:
                    raise ValueError("oversized cursor")
                parsed = strict_json_loads(base64.urlsafe_b64decode(cursor.encode()).decode())
                if (
                    set(parsed) != {"owner", "time", "id"}
                    or parsed["owner"] != owner
                    or type(parsed["time"]) is not int
                    or not 0 <= parsed["time"] < 2**63
                    or not isinstance(parsed["id"], str)
                    or str(uuid.UUID(parsed["id"])) != parsed["id"]
                ):
                    raise ValueError("invalid cursor")
                after_time, after_id = parsed["time"], parsed["id"]
            except (ValueError, TypeError, UnicodeError) as exc:
                raise JobError("invalid or wrong-owner pagination cursor") from exc
        connection = self._connect()
        try:
            records = connection.execute(
                """SELECT * FROM jobs WHERE owner=? AND
                (created_ns>? OR (created_ns=? AND job_id>?))
                ORDER BY created_ns,job_id LIMIT ?""",
                (owner, after_time, after_time, after_id, limit + 1),
            ).fetchall()
        finally:
            connection.close()
        jobs = tuple(_job(row) for row in records[:limit])
        token = None
        if len(records) > limit:
            token = base64.urlsafe_b64encode(
                json.dumps(
                    {"owner": owner, "time": jobs[-1].created_ns, "id": jobs[-1].job_id}
                ).encode()
            ).decode()
        return jobs, token

    def verify_audit_chain(self, *, expected_head: str | None = None) -> str:
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            rows = connection.execute("SELECT * FROM events ORDER BY seq").fetchall()
            jobs = connection.execute("SELECT * FROM jobs").fetchall()
        except sqlite3.Error as exc:
            raise JobStorageError("job audit storage is unavailable") from exc
        finally:
            connection.close()
        previous = "0" * 64
        latest: dict[str, dict[str, Any]] = {}
        submitted: dict[str, dict[str, Any]] = {}
        for index, row in enumerate(rows, 1):
            body = strict_json_loads(row["body_json"])
            if (
                not isinstance(body, dict)
                or set(body)
                != {
                    "job_id",
                    "trace_id",
                    "owner",
                    "event",
                    "status",
                    "version",
                    "attempts",
                    "cancel_requested",
                    "time_ns",
                    "details",
                }
                or not isinstance(body["details"], dict)
            ):
                raise JobError("malformed audit event")
            actual = compute_result_hash({"previous_sha256": previous, "event": body})
            if (
                row["seq"] != index
                or row["previous_sha256"] != previous
                or row["event_sha256"] != actual
            ):
                raise JobError("audit chain consistency check failed")
            previous = actual
            latest[body["job_id"]] = body
            if body["event"] == "submitted":
                submitted[body["job_id"]] = body
        if set(latest) != {job["job_id"] for job in jobs} or set(submitted) != set(latest):
            raise JobError("job/audit projection differs")
        for job in jobs:
            last, first = latest[job["job_id"]], submitted[job["job_id"]]
            if any(
                last[key] != job[key]
                for key in (
                    "owner",
                    "trace_id",
                    "status",
                    "version",
                    "attempts",
                    "cancel_requested",
                )
            ):
                raise JobError("job state differs from its audit projection")
            recipe_hash = compute_result_hash(
                {"kind": job["kind"], "config": strict_json_loads(job["config_json"])}
            )
            if (
                recipe_hash != job["recipe_sha256"]
                or recipe_hash != first["details"]["recipe_sha256"]
            ):
                raise JobError("job recipe differs from its submitted fingerprint")
            request_hash = compute_result_hash(
                {"recipe_sha256": recipe_hash, "timeout_seconds": job["timeout_seconds"]}
            )
            if (
                request_hash != job["request_sha256"]
                or request_hash != first["details"]["request_sha256"]
            ):
                raise JobError("job request differs from its submitted fingerprint")
            if (
                compute_result_hash(strict_json_loads(job["estimate_json"]))
                != first["details"]["estimate_sha256"]
            ):
                raise JobError("job resource plan differs from its submitted fingerprint")
            if (
                compute_result_hash(strict_json_loads(job["runtime_json"]))
                != first["details"]["runtime_sha256"]
            ):
                raise JobError("job runtime differs from its submitted fingerprint")
            if last["event"] in ("finished", "lease_recovered") and any(
                last["details"].get(key) != job[key]
                for key in ("artifact_sha256", "result_hash", "error_code", "diagnostic_id")
            ):
                raise JobError("job outcome differs from its audited outcome")
        if expected_head is not None and (
            not is_sha256(expected_head) or previous != expected_head
        ):
            raise JobError("audit head differs from externally supplied checkpoint")
        return previous
