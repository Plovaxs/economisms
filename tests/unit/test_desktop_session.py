"""PR-205: the desktop job engine, against the real isolated worker.

Nothing here fakes the worker: a job is submitted to the real queue, claimed by the real `Worker`,
run in a real child process, published to the real content-addressed store and read back through
its hash verification. Only the *sizes* are small (a few epochs) so a run takes seconds.
"""

from __future__ import annotations

import importlib
import json
import os
import sqlite3
import stat
import time
import types
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from prometheus.desktop import catalog
from prometheus.desktop import session as session_module
from prometheus.desktop.catalog import KIND_CATALOG, describe_error, info
from prometheus.desktop.paths import StateDirectoryError
from prometheus.desktop.runner import WorkerLoop
from prometheus.desktop.session import (
    DESKTOP_POLICY,
    THREAD_VARIABLES,
    JobsUnavailableError,
    LocalSession,
    ResultUnavailableError,
    configure_worker_environment,
    summarize,
)
from prometheus.jobs.store import ERROR_CODES, JobError, QueuePolicy
from prometheus.orchestration.recipes import RUNNERS, default_recipe


def small_inflationcast() -> dict[str, Any]:
    recipe = default_recipe("inflationcast")
    recipe.update(max_epochs=3, bootstrap_resamples=20)
    return recipe


def slow_rl_hedge() -> dict[str, Any]:
    """Admitted by the limits, but far longer than any test waits for."""
    recipe = default_recipe("rl_hedge")
    recipe.update(n_epochs=400, n_paths=800, n_steps=60)
    return recipe


def wait_for(predicate: Callable[[], bool], *, timeout: float = 90.0, what: str = "") -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError(f"timed out after {timeout}s waiting for {what or predicate}")


def child_pids() -> list[int]:
    """Worker child processes of THIS process, from /proc (no extra dependency)."""
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        parsed = _parent_and_command(entry)
        if parsed and parsed[0] == os.getpid() and b"prometheus.jobs.child" in parsed[1]:
            found.append(int(entry.name))
    return found


def _parent_and_command(entry: Path) -> tuple[int, bytes] | None:
    try:
        parent = int((entry / "stat").read_text().rsplit(")", 1)[1].split()[1])
        return parent, (entry / "cmdline").read_bytes()
    except (OSError, ValueError, IndexError):
        return None


@pytest.fixture
def session(tmp_path: Path) -> LocalSession:
    return LocalSession(tmp_path / "state")


# ------------------------------------------------------------------ the catalog


def test_the_catalog_has_exactly_one_entry_per_runner() -> None:
    kinds = [entry.kind for entry in KIND_CATALOG]
    assert sorted(kinds) == sorted(RUNNERS) and len(kinds) == len(set(kinds))
    assert len({entry.title for entry in KIND_CATALOG}) == len(KIND_CATALOG)
    assert {entry.group for entry in KIND_CATALOG} == set(catalog.GROUPS)
    assert all(entry.summary.endswith((".", "?")) for entry in KIND_CATALOG)


def test_every_error_code_the_queue_can_record_has_a_plain_message() -> None:
    assert set(catalog.ERROR_MESSAGES) == set(ERROR_CODES)
    assert describe_error(None) == ""
    assert "time limit" in describe_error("wall_timeout")
    assert "unknown_code" in describe_error("unknown_code")


def test_a_runner_is_marked_as_using_the_network_exactly_when_its_code_does() -> None:
    for kind, spec in RUNNERS.items():
        module = importlib.import_module(f"prometheus.orchestration.{spec.module}")
        source = Path(module.__file__ or "").read_text(encoding="utf-8")
        reaches_out = "default_ingestion_transport" in source
        assert info(kind).network is reaches_out, kind


# ------------------------------------------------------------------ the state directory


def test_the_session_keeps_its_state_in_a_private_directory(tmp_path: Path) -> None:
    root = tmp_path / "state"
    LocalSession(root)
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE((root / "jobs.sqlite3").stat().st_mode) == 0o600
    assert (root / "artifacts").is_dir()


def test_a_state_directory_open_to_others_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "loose"
    root.mkdir()
    root.chmod(0o755)
    with pytest.raises(StateDirectoryError, match="chmod 700"):
        LocalSession(root)


def test_a_store_cannot_be_reopened_under_different_limits(tmp_path: Path) -> None:
    LocalSession(tmp_path / "state")
    with pytest.raises(JobError, match="policy differs"):
        LocalSession(tmp_path / "state", policy=QueuePolicy(max_wall_seconds=60.0))


def test_the_desktop_policy_runs_one_job_at_a_time() -> None:
    assert DESKTOP_POLICY.max_running_total == 1
    assert DESKTOP_POLICY.max_wall_seconds == 1800.0


# ------------------------------------------------------------------ judging a recipe


def test_a_valid_recipe_is_admitted_with_its_resource_estimate(session: LocalSession) -> None:
    prepared = session.validate("inflationcast", small_inflationcast())
    assert prepared.kind == "inflationcast" and len(prepared.recipe_sha256) == 64
    assert prepared.estimate.epochs == 3


def test_an_unknown_field_is_rejected_with_a_message(session: LocalSession) -> None:
    config = small_inflationcast()
    config["bogus"] = 1
    with pytest.raises(ValueError, match="inflationcast"):
        session.validate("inflationcast", config)


def test_a_recipe_beyond_the_resource_limits_is_rejected_before_it_is_queued(
    session: LocalSession,
) -> None:
    config = small_inflationcast()
    config["max_epochs"] = 10_000_000
    with pytest.raises(ValueError, match="max_epochs"):
        session.submit("inflationcast", config)
    assert session.jobs() == ()


# ------------------------------------------------------------------ a whole job, for real


def test_a_job_runs_in_a_child_process_and_its_verified_result_is_readable(
    session: LocalSession,
) -> None:
    job = session.submit("inflationcast", small_inflationcast())
    assert job.status == "queued" and session.counts() == {"queued": 1}

    finished = session.work_once()
    assert finished is not None and finished.status == "succeeded"
    assert finished.job_id == job.job_id and finished.error_code is None

    result = session.result(job.job_id)
    assert result.kind == "inflationcast" and result.title == "INFLATIONCAST"
    assert result.verdict in {"gru_better", "classical_better", "inconclusive"}
    assert result.comparisons and {"mae", "rmse"} <= set(result.comparisons[0].columns)
    assert result.disclaimer.startswith("SIMULATED DATA -- RESEARCH ONLY")
    facts = dict(result.provenance)
    assert facts["Job"] == job.job_id and facts["Artifact SHA-256"] == finished.artifact_sha256

    [summary] = session.summaries()
    assert summary.status == "succeeded" and summary.has_result and summary.error == ""
    assert summary.title == "INFLATIONCAST" and summary.finished
    assert len(session.audit_head()) == 64
    assert session.storage_bytes() > 0
    assert child_pids() == [], "the child process is gone when the job is"


def test_a_finished_job_survives_closing_and_reopening_the_session(tmp_path: Path) -> None:
    first = LocalSession(tmp_path / "state")
    job = first.submit("inflationcast", small_inflationcast())
    first.work_once()
    second = LocalSession(tmp_path / "state")
    assert [j.job_id for j in second.jobs()] == [job.job_id]
    assert second.result(job.job_id).verdict is not None
    assert second.audit_head() == first.audit_head()


def test_an_empty_queue_returns_nothing_to_do(session: LocalSession) -> None:
    assert session.work_once() is None


def test_jobs_are_listed_newest_first_and_bounded(session: LocalSession) -> None:
    ids = [session.submit("inflationcast", small_inflationcast()).job_id for _ in range(3)]
    listed = [job.job_id for job in session.jobs()]
    assert listed == ids[::-1]
    assert [job.job_id for job in session.jobs(limit=2)] == ids[::-1][:2]


def test_cancelling_a_queued_job_is_immediate_and_it_never_runs(session: LocalSession) -> None:
    job = session.submit("inflationcast", small_inflationcast())
    assert session.cancel(job.job_id).status == "cancelled"
    assert session.work_once() is None
    with pytest.raises(ResultUnavailableError, match="no result"):
        session.result(job.job_id)
    assert session.cancel(job.job_id).status == "cancelled", "cancelling twice is harmless"


def test_a_job_that_runs_out_of_time_is_recorded_as_timed_out(session: LocalSession) -> None:
    job = session.submit("rl_hedge", slow_rl_hedge(), timeout_seconds=1.0)
    finished = session.work_once()
    assert finished is not None and finished.job_id == job.job_id
    assert finished.status == "timed_out"
    assert finished.error_code in {"wall_timeout", "cpu_timeout"}
    [summary] = session.summaries()
    assert "limit" in summary.error and not summary.has_result
    with pytest.raises(ResultUnavailableError, match="timed_out"):
        session.result(job.job_id)
    assert child_pids() == []


def test_an_unknown_job_id_is_reported(session: LocalSession) -> None:
    with pytest.raises(ValueError, match="not found"):
        session.get("0" * 36)
    with pytest.raises(ValueError, match="not found"):
        session.result("nonsense")


# ------------------------------------------------------------------ results are verified on read


def test_a_result_edited_after_the_fact_is_refused_not_displayed(session: LocalSession) -> None:
    job = session.submit("inflationcast", small_inflationcast())
    finished = session.work_once()
    assert finished is not None and finished.artifact_sha256 is not None
    digest = finished.artifact_sha256
    path = session.artifacts.root / digest[:2] / f"{digest}.json"
    body = json.loads(path.read_text())
    body["inflationcast"]["best_point_challenger"] = "tampered"
    path.chmod(0o600)
    path.write_text(json.dumps(body, sort_keys=True, indent=2))
    with pytest.raises(ResultUnavailableError, match="failed verification"):
        session.result(job.job_id)


def test_a_missing_result_file_is_reported_not_raised_raw(session: LocalSession) -> None:
    job = session.submit("inflationcast", small_inflationcast())
    finished = session.work_once()
    assert finished is not None and finished.artifact_sha256 is not None
    digest = finished.artifact_sha256
    path = session.artifacts.root / digest[:2] / f"{digest}.json"
    path.unlink()
    with pytest.raises(ResultUnavailableError, match="failed verification"):
        session.result(job.job_id)


def test_a_result_belonging_to_another_job_is_not_shown_as_this_ones(
    session: LocalSession,
) -> None:
    first = session.submit("inflationcast", small_inflationcast())
    done_first = session.work_once()
    other = {**small_inflationcast(), "seed": 7}
    second = session.submit("inflationcast", other)
    session.work_once()
    assert done_first is not None and done_first.artifact_sha256 is not None
    # someone with write access to the database points the second job at the first's (valid) result
    connection = sqlite3.connect(session.store.path)
    connection.execute(
        "UPDATE jobs SET artifact_sha256=?, result_hash=? WHERE job_id=?",
        (done_first.artifact_sha256, done_first.result_hash, second.job_id),
    )
    connection.commit()
    connection.close()
    assert session.result(first.job_id).verdict is not None
    with pytest.raises(ResultUnavailableError, match="does not belong to this job"):
        session.result(second.job_id)


def test_exporting_a_result_writes_a_verified_copy_and_never_overwrites(
    session: LocalSession, tmp_path: Path
) -> None:
    job = session.submit("inflationcast", small_inflationcast())
    session.work_once()
    target = tmp_path / "out" / "result.json"
    assert session.export_result(job.job_id, target) == target
    exported = json.loads(target.read_text())
    assert exported["job_context"]["job_id"] == job.job_id
    assert "inflationcast" in exported and "artifact_integrity" in exported
    with pytest.raises(FileExistsError):
        session.export_result(job.job_id, target)
    planted = tmp_path / "planted.json"
    planted.symlink_to(tmp_path / "elsewhere.json")
    with pytest.raises(FileExistsError):
        session.export_result(job.job_id, planted)


# ------------------------------------------------------------------ presenting a job


def test_a_summary_stops_the_clock_for_a_finished_job_and_runs_it_for_a_live_one(
    session: LocalSession,
) -> None:
    job = session.submit("inflationcast", small_inflationcast())
    queued_for_a_moment = summarize(job, now_ns=job.created_ns + 5_000_000_000)
    assert queued_for_a_moment.elapsed_seconds == pytest.approx(5.0)
    assert queued_for_a_moment.short_id == job.job_id[:8] and not queued_for_a_moment.finished
    done = session.work_once()
    assert done is not None
    long_after = summarize(done, now_ns=done.updated_ns + 9_000_000_000)
    assert long_after.elapsed_seconds == pytest.approx((done.updated_ns - done.created_ns) / 1e9)


def test_an_unknown_kind_still_has_a_title(session: LocalSession) -> None:
    job = session.submit("inflationcast", small_inflationcast())
    assert summarize(replace(job, kind="from_the_future")).title == "from_the_future"


# ------------------------------------------------------------------ platform and environment


def test_a_platform_without_the_isolated_worker_says_so_instead_of_pretending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(session_module, "sys", types.SimpleNamespace(platform="darwin"))
    elsewhere = LocalSession(tmp_path / "state")
    assert not elsewhere.can_run_jobs
    with pytest.raises(JobsUnavailableError, match="Linux"):
        elsewhere.work_once()


def test_thread_pools_default_to_one_but_never_override_the_user() -> None:
    environ: dict[str, str] = {"OMP_NUM_THREADS": "6"}
    configure_worker_environment(environ=environ)
    assert environ["OMP_NUM_THREADS"] == "6"
    untouched = [name for name in THREAD_VARIABLES if name != "OMP_NUM_THREADS"]
    assert [environ[name] for name in untouched] == ["1"] * len(untouched)
    other: dict[str, str] = {}
    configure_worker_environment(4, environ=other)
    assert set(other.values()) == {"4"}


# ------------------------------------------------------------------ the worker thread


def test_the_loop_works_through_the_queue_while_the_caller_is_free(session: LocalSession) -> None:
    loop = WorkerLoop(session)
    loop.start()
    loop.start()  # harmless
    try:
        job = session.submit("inflationcast", small_inflationcast())
        wait_for(lambda: session.get(job.job_id).status == "succeeded", what="the job to finish")
        assert loop.processed == 1 and loop.alive and loop.last_error is None
    finally:
        assert loop.stop()
    assert not loop.alive


def test_stopping_a_loop_that_never_started_is_fine(session: LocalSession) -> None:
    assert WorkerLoop(session).stop()


def test_one_failure_does_not_kill_the_loop(
    session: LocalSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"n": 0}

    def flaky() -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("disk hiccup")

    monkeypatch.setattr(session, "work_once", flaky)
    loop = WorkerLoop(session, idle_seconds=0.01)
    loop.start()
    try:
        wait_for(lambda: calls["n"] >= 3, timeout=10, what="the loop to keep polling")
        assert loop.alive and loop.last_error == "RuntimeError: disk hiccup"
    finally:
        assert loop.stop()


def test_a_platform_that_can_never_work_ends_the_loop_with_the_reason(
    session: LocalSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    def never() -> None:
        raise JobsUnavailableError("needs Linux")

    monkeypatch.setattr(session, "work_once", never)
    loop = WorkerLoop(session, idle_seconds=0.01)
    loop.start()
    wait_for(lambda: not loop.alive, timeout=10, what="the loop to give up")
    assert loop.last_error == "needs Linux"


def test_stopping_cancels_the_running_job_and_leaves_no_process_behind(
    session: LocalSession,
) -> None:
    loop = WorkerLoop(session, idle_seconds=0.01)
    loop.start()
    job = session.submit("rl_hedge", slow_rl_hedge())
    wait_for(lambda: session.get(job.job_id).status == "running", what="the job to start")
    wait_for(lambda: len(child_pids()) == 1, what="the child process to exist")
    started = time.monotonic()
    assert loop.stop(timeout=30)
    assert time.monotonic() - started < 20, "closing must not wait out a long job"
    assert session.get(job.job_id).status == "cancelled"
    wait_for(lambda: child_pids() == [], timeout=10, what="the child process to be gone")
