import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
import torch

from prometheus.evidence.export import export_evidence_bundle
from prometheus.jobs.artifacts import ArtifactError, ArtifactStore
from prometheus.jobs.store import JobStore
from prometheus.jobs.worker import Worker, _child_environment
from prometheus.orchestration.recipes import default_recipe
from prometheus.orchestration.replay import replay_evidence_bundle


def small_recipe():
    raw = default_recipe("benchmark")
    raw.update(
        n_steps=3,
        n_train_paths=16,
        n_train_epochs=3,
        batch_size=8,
        n_eval_paths=16,
        n_bootstrap_resamples=8,
        test_seeds=[100, 200],
    )
    return raw


def test_separate_processes_preserve_same_seed_results_and_parent_rng(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    artifacts = ArtifactStore(tmp_path / "objects")
    a = store.submit(
        "benchmark", small_recipe(), owner="alice", idempotency_key="a", timeout_seconds=20.0
    )
    b = store.submit(
        "benchmark", small_recipe(), owner="alice", idempotency_key="b", timeout_seconds=20.0
    )
    rng = torch.random.get_rng_state().clone()
    workers = [Worker(store, artifacts, worker_id=f"w-{n}") for n in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        done = list(pool.map(lambda w: w.run_once(), workers))
    assert {d.job_id for d in done} == {a.job_id, b.job_id}
    assert all(d.status == "succeeded" for d in done), [
        (d.error_code, d.diagnostic_id) for d in done
    ]
    assert done[0].result_hash == done[1].result_hash
    assert done[0].artifact_sha256 != done[1].artifact_sha256
    assert torch.equal(rng, torch.random.get_rng_state())
    body = artifacts.get(done[0].artifact_sha256)
    assert body["job_context"]["job_id"] == done[0].job_id
    assert replay_evidence_bundle(body, require_integrity=True).matches
    assert not list((tmp_path / "staging").iterdir())
    assert store.verify_audit_chain() != "0" * 64


def test_real_process_wall_timeout_is_terminal_and_publishes_no_success(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    artifacts = ArtifactStore(tmp_path / "objects")
    store.submit("benchmark", small_recipe(), owner="alice", timeout_seconds=0.05)
    start = time.monotonic()
    done = Worker(store, artifacts, worker_id="worker").run_once()
    assert done.status == "timed_out" and done.error_code == "wall_timeout"
    assert time.monotonic() - start < 5
    assert done.artifact_sha256 is None and not list((tmp_path / "staging").iterdir())


def test_running_cancellation_stops_child_and_fences_artifact_publication(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    artifacts = ArtifactStore(tmp_path / "objects")
    raw = small_recipe()
    raw.update(n_train_epochs=1000, n_steps=20)
    job = store.submit("benchmark", raw, owner="alice", timeout_seconds=20.0)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(Worker(store, artifacts, worker_id="worker").run_once)
        until = time.monotonic() + 5
        while store.get(job.job_id, owner="alice").status != "running":
            assert time.monotonic() < until
            time.sleep(0.01)
        store.cancel(job.job_id, owner="alice")
        done = future.result(timeout=5)
    assert done.status == "cancelled" and done.artifact_sha256 is None
    assert not list((tmp_path / "staging").iterdir())


def test_failed_simulation_keeps_invalid_evidence_without_success_status(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    artifacts = ArtifactStore(tmp_path / "objects")
    raw = default_recipe("economy")
    raw["max_price_evaluations"] = 3
    store.submit("economy", raw, owner="alice", timeout_seconds=20.0)
    done = Worker(store, artifacts, worker_id="worker").run_once()
    assert done.status == "failed" and done.error_code == "invalid_simulation"
    assert not artifacts.get(done.artifact_sha256)["economy"]["valid"]


def test_environment_change_fails_before_a_child_is_launched(tmp_path, monkeypatch):
    import prometheus.jobs.worker as module

    store = JobStore(tmp_path / "jobs.sqlite3")
    artifacts = ArtifactStore(tmp_path / "objects")
    store.submit("benchmark", small_recipe(), owner="alice")
    monkeypatch.setattr(module, "runtime_provenance", lambda: {"changed": True})

    def forbidden(*args, **kwargs):
        pytest.fail("mismatched environment must not launch a child")

    monkeypatch.setattr(module.subprocess, "Popen", forbidden)
    done = Worker(store, artifacts, worker_id="worker").run_once()
    assert done.status == "failed" and done.error_code == "environment_mismatch"


def test_worker_environment_excludes_service_credentials(monkeypatch):
    monkeypatch.setenv("PROMETHEUS_AUTH_TOKEN", "unit-test-secret")
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    env = _child_environment()
    assert "PROMETHEUS_AUTH_TOKEN" not in env and env["OMP_NUM_THREADS"] == "1"


def test_linux_parent_death_stops_orphan_and_record_is_recoverable(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    raw = small_recipe()
    raw.update(n_train_paths=10000, n_steps=100, n_train_epochs=1000)
    job = store.submit("benchmark", raw, owner="alice", timeout_seconds=30.0)
    # A dedicated subreaper supervisor reaps the deliberately orphaned child
    # so this failure-injection test cannot leave zombies in the test host.
    supervisor = r"""
import ctypes,json,os,subprocess,sys,time
libc=ctypes.CDLL(None);assert libc.prctl(36,1,0,0,0)==0
worker=subprocess.Popen([sys.executable,'-m','prometheus.jobs','--root',sys.argv[1],'work','--once'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
child=None
try:
 until=time.monotonic()+8
 while time.monotonic()<until:
  path=f'/proc/{worker.pid}/task/{worker.pid}/children'
  try: ids=open(path).read().split()
  except FileNotFoundError: ids=[]
  if ids: child=int(ids[0]);break
  if worker.poll() is not None:break
  time.sleep(.01)
 assert child is not None,'worker child never started'
 worker.kill();worker.wait(timeout=3)
 until=time.monotonic()+4;stopped=False
 while time.monotonic()<until:
  reaped,status=os.waitpid(child,os.WNOHANG)
  if reaped:stopped=True;break
  time.sleep(.01)
 if not stopped:
  os.kill(child,9);os.waitpid(child,0)
 assert stopped,'orphan child survived parent death'
 print(json.dumps({'stopped':True}))
finally:
 if worker.poll() is None:worker.kill();worker.wait()
"""
    result = subprocess.run(
        [sys.executable, "-c", supervisor, str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["stopped"]
    recovering = JobStore(tmp_path / "jobs.sqlite3", clock=lambda: time.time_ns() + 40_000_000_000)
    assert recovering.recover_expired() == 1
    assert recovering.get(job.job_id, owner="alice").status == "queued"
    recovering.cancel(job.job_id, owner="alice")
    assert recovering.verify_audit_chain() != "0" * 64


def test_staging_cleanup_only_removes_known_inactive_attempts(tmp_path):
    import uuid

    store = JobStore(tmp_path / "jobs.sqlite3")
    artifacts = ArtifactStore(tmp_path / "objects")
    job = store.submit("benchmark", small_recipe(), owner="alice")
    lease = store.claim("worker")
    worker = Worker(store, artifacts, worker_id="other")
    active = worker.staging / f"{job.job_id}-{lease.token}-active"
    inactive = worker.staging / f"{job.job_id}-{'a' * 32}-old"
    unknown = worker.staging / f"{uuid.uuid4()}-{'b' * 32}-unknown"
    for path in (active, inactive, unknown):
        path.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = worker.staging / f"{job.job_id}-{'c' * 32}-link"
    link.symlink_to(outside, target_is_directory=True)
    assert worker.clean_staging() == 1
    assert active.exists() and unknown.exists() and link.is_symlink() and outside.exists()
    store.cancel(job.job_id, owner="alice")
    store.finish(lease, "cancelled")
    assert worker.clean_staging() == 1 and not active.exists()


def test_wrong_job_context_cannot_be_published_as_a_job_result(tmp_path):
    from prometheus.orchestration.recipes import execute_recipe

    store = JobStore(tmp_path / "jobs.sqlite3")
    artifacts = ArtifactStore(tmp_path / "objects")
    raw = default_recipe("economy")
    raw.update(n_steps=2, productivity_shock_step=2)
    job = store.submit("economy", raw, owner="alice")
    lease = store.claim("worker")
    body = execute_recipe("economy", raw).evidence_bundle
    body["job_context"] = {"job_id": "a different job"}
    output = tmp_path / "wrong.json"
    export_evidence_bundle(body, output)
    with pytest.raises(ArtifactError, match="bound"):
        Worker(store, artifacts, worker_id="worker")._accept_output(lease, output)
    assert store.get(job.job_id, owner="alice").artifact_sha256 is None


def test_child_deadline_restores_an_alarm_ignored_by_its_parent(tmp_path):
    request = tmp_path / "request.json"
    output = tmp_path / "result.json"
    request.write_text("{}")
    # The parent deliberately ignores ALRM; the child must reset inherited
    # signal disposition before its own deadline, even before heavy imports.
    code = r"""
import os,signal,subprocess,sys
signal.signal(signal.SIGALRM,signal.SIG_IGN)
p=subprocess.Popen([sys.executable,'-m','prometheus.jobs.child','--input',sys.argv[1],'--output',sys.argv[2],'--timeout','0.01','--max-file-bytes','1000000','--parent-pid',str(os.getpid())],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
try: result=p.wait(timeout=5)
finally:
 if p.poll() is None:p.kill();p.wait()
assert result==-signal.SIGALRM,result
"""
    ran = subprocess.run(
        [sys.executable, "-c", code, str(request), str(output)],
        capture_output=True,
        text=True,
        timeout=8,
    )
    assert ran.returncode == 0, ran.stderr
