import base64
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace

import pytest

from prometheus.jobs.store import (
    IdempotencyConflict,
    JobError,
    JobNotFound,
    JobStore,
    LeaseLost,
    QueuePolicy,
    QuotaExceeded,
)
from prometheus.orchestration.recipes import default_recipe


class Clock:
    def __init__(self):
        self.value = 1_000_000_000_000

    def __call__(self):
        self.value += 1
        return self.value

    def advance(self, seconds):
        self.value += int(seconds * 1e9)


@pytest.fixture
def config():
    return default_recipe("economy")


def test_persistence_idempotency_conflicts_and_owner_visibility(tmp_path, config):
    path = tmp_path / "jobs.sqlite3"
    store = JobStore(path)
    first = store.submit("economy", config, owner="alice", idempotency_key="key")
    assert (
        store.submit("economy", config, owner="alice", idempotency_key="key").job_id == first.job_id
    )
    other = store.submit("economy", config, owner="bob", idempotency_key="key")
    assert other.job_id != first.job_id
    changed = dict(config, seed=5)
    with pytest.raises(IdempotencyConflict):
        store.submit("economy", changed, owner="alice", idempotency_key="key")
    with pytest.raises(JobNotFound):
        store.get(first.job_id, owner="bob")
    with pytest.raises(JobNotFound):
        store.cancel(first.job_id, owner="bob")
    reopened = JobStore(path)
    assert reopened.get(first.job_id, owner="alice") == first
    assert reopened.verify_audit_chain() == store.verify_audit_chain()


def test_concurrent_identical_submission_is_one_transactional_job(tmp_path, config):
    store = JobStore(tmp_path / "jobs.sqlite3")

    def submit(_):
        return store.submit("economy", config, owner="alice", idempotency_key="same").job_id

    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(submit, range(16)))
    assert len(set(ids)) == 1
    assert len(store.list_jobs(owner="alice")[0]) == 1
    assert store.verify_audit_chain() != "0" * 64


def test_capacity_is_atomic_and_idempotent_retries_do_not_consume_quota(tmp_path, config):
    policy = QueuePolicy(max_pending_per_owner=1, max_pending_total=2, max_running_total=1)
    store = JobStore(tmp_path / "jobs.sqlite3", policy=policy)
    first = store.submit("economy", config, owner="alice", idempotency_key="one")
    assert store.submit("economy", config, owner="alice", idempotency_key="one") == first
    with pytest.raises(QuotaExceeded):
        store.submit("economy", config, owner="alice")
    store.submit("economy", config, owner="bob")
    with pytest.raises(QuotaExceeded):
        store.submit("economy", config, owner="charlie")
    lease = store.claim("worker")
    assert lease is not None and store.claim("other") is None
    done = store.finish(lease, "succeeded", artifact_sha256="0" * 64, result_hash="1" * 64)
    assert done.status == "succeeded" and "token" not in asdict(done)
    assert store.submit("economy", config, owner=done.owner).status == "queued"


def test_claims_are_unique_and_completed_jobs_cannot_be_completed_again(tmp_path, config):
    store = JobStore(tmp_path / "jobs.sqlite3")
    store.submit("economy", config, owner="alice")

    def claim(n):
        return store.claim(f"worker-{n}")

    with ThreadPoolExecutor(max_workers=6) as pool:
        leases = list(pool.map(claim, range(6)))
    actual = [lease for lease in leases if lease is not None]
    assert len(actual) == 1
    store.finish(actual[0], "succeeded", artifact_sha256="a" * 64, result_hash="b" * 64)
    with pytest.raises(LeaseLost):
        store.finish(actual[0], "succeeded", artifact_sha256="a" * 64, result_hash="b" * 64)


def test_expired_worker_is_fenced_after_recovery_and_reclaim(tmp_path, config):
    clock = Clock()
    policy = QueuePolicy(lease_seconds=1.0)
    store = JobStore(tmp_path / "jobs.sqlite3", policy=policy, clock=clock)
    submitted = store.submit("economy", config, owner="alice")
    old = store.claim("old")
    clock.advance(2)
    assert store.recover_expired() == 1
    new = store.claim("new")
    assert old.token != new.token and new.job.attempts == 2
    with pytest.raises(LeaseLost):
        store.heartbeat(old)
    with pytest.raises(LeaseLost):
        store.finish(old, "succeeded", artifact_sha256="a" * 64, result_hash="b" * 64)
    assert (
        store.finish(new, "succeeded", artifact_sha256="c" * 64, result_hash="d" * 64).job_id
        == submitted.job_id
    )


def test_cancellation_fences_success_and_is_idempotent(tmp_path, config):
    store = JobStore(tmp_path / "jobs.sqlite3")
    queued = store.submit("economy", config, owner="alice")
    cancelled = store.cancel(queued.job_id, owner="alice")
    assert cancelled.status == "cancelled"
    assert store.cancel(queued.job_id, owner="alice") == cancelled
    running = store.submit("economy", config, owner="alice")
    lease = store.claim("worker")
    asked = store.cancel(running.job_id, owner="alice")
    assert asked.status == "running" and asked.cancel_requested
    with pytest.raises(LeaseLost):
        store.finish(lease, "succeeded", artifact_sha256="a" * 64, result_hash="b" * 64)
    assert store.finish(lease, "cancelled").status == "cancelled"


def test_recovery_terminalizes_cancelled_and_exhausted_jobs(tmp_path, config):
    clock = Clock()
    store = JobStore(
        tmp_path / "jobs.sqlite3",
        policy=QueuePolicy(max_attempts=1, lease_seconds=1.0),
        clock=clock,
    )
    a = store.submit("economy", config, owner="alice")
    store.claim("one")
    clock.advance(2)
    store.recover_expired()
    assert store.get(a.job_id, owner="alice").error_code == "lease_expired"
    b = store.submit("economy", config, owner="alice")
    store.claim("two")
    store.cancel(b.job_id, owner="alice")
    clock.advance(2)
    store.recover_expired()
    assert store.get(b.job_id, owner="alice").status == "cancelled"


def test_pagination_is_stable_scoped_and_cursor_values_are_bounded(tmp_path, config):
    store = JobStore(tmp_path / "jobs.sqlite3")
    for _ in range(5):
        store.submit("economy", config, owner="alice")
    store.submit("economy", config, owner="bob")
    seen = []
    cursor = None
    while True:
        jobs, cursor = store.list_jobs(owner="alice", limit=2, cursor=cursor)
        seen.extend(job.job_id for job in jobs)
        if cursor is None:
            break
    assert len(seen) == len(set(seen)) == 5
    _, token = store.list_jobs(owner="alice", limit=1)
    with pytest.raises(JobError):
        store.list_jobs(owner="bob", cursor=token)
    forged = base64.urlsafe_b64encode(
        json.dumps({"owner": "alice", "time": 10**100, "id": seen[0]}).encode()
    ).decode()
    with pytest.raises(JobError):
        store.list_jobs(owner="alice", cursor=forged)


def test_policy_migrations_and_unrelated_databases_fail_explicitly(tmp_path, config):
    path = tmp_path / "jobs.sqlite3"
    JobStore(path)
    with pytest.raises(JobError, match="policy differs"):
        JobStore(path, policy=replace(QueuePolicy(), max_attempts=4))
    other = tmp_path / "other.sqlite3"
    con = sqlite3.connect(other)
    con.execute("CREATE TABLE unrelated(value TEXT)")
    con.commit()
    con.close()
    with pytest.raises(JobError, match="unrelated"):
        JobStore(other)
    con = sqlite3.connect(path)
    con.execute("PRAGMA user_version=99")
    con.close()
    with pytest.raises(JobError, match="schema"):
        JobStore(path)


def test_audit_events_reject_application_mutations_and_detect_corruption(tmp_path, config):
    path = tmp_path / "jobs.sqlite3"
    store = JobStore(path)
    store.submit("economy", config, owner="alice")
    con = sqlite3.connect(path)
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("UPDATE events SET event_sha256='bad'")
    con.rollback()
    con.execute("DROP TRIGGER events_no_update")
    con.execute("UPDATE events SET event_sha256='bad'")
    con.commit()
    con.close()
    with pytest.raises(JobError, match="consistency"):
        store.verify_audit_chain()


def test_audit_projection_detects_job_row_tampering_without_an_event_change(tmp_path, config):
    path = tmp_path / "jobs.sqlite3"
    store = JobStore(path)
    job = store.submit("economy", config, owner="alice")
    head = store.verify_audit_chain()
    assert store.verify_audit_chain(expected_head=head) == head
    con = sqlite3.connect(path)
    con.execute(
        "UPDATE jobs SET config_json=? WHERE job_id=?",
        (json.dumps(dict(config, seed=99)), job.job_id),
    )
    con.commit()
    con.close()
    with pytest.raises(JobError, match="recipe"):
        store.verify_audit_chain()


def test_database_errors_have_a_structured_application_error(tmp_path):
    from prometheus.jobs.store import JobStorageError

    path = tmp_path / "bad.sqlite3"
    path.write_text("not a database")
    with pytest.raises(JobStorageError):
        JobStore(path)
