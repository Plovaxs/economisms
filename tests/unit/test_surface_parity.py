"""One recipe, three ways in: the same scientific result.

The architecture rule is "one canonical engine and experiment schema: the direct runner, the jobs
engine behind the web API, and the desktop window's session must produce the same result when
configured identically". Each path below runs the identical recipe through its own machinery (the
direct call in-process; the job store, a worker and an isolated child process; the desktop's local
session) and compares the sealed result hash, which covers the whole scientific payload, and the
recipe hash. A second recipe with a different seed must differ, so equality is not vacuous.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from prometheus.desktop.session import LocalSession
from prometheus.jobs.artifacts import ArtifactStore
from prometheus.jobs.store import JobStore
from prometheus.jobs.worker import Worker
from prometheus.orchestration.recipes import default_recipe, execute_recipe, prepare_recipe


def _economy(seed: int = 0) -> dict[str, Any]:
    recipe = default_recipe("economy")
    recipe.update(n_steps=2, productivity_shock_step=2)
    if "seed" in recipe:
        recipe["seed"] = seed
    return recipe


def _hedge(seed: int = 0) -> dict[str, Any]:
    recipe = default_recipe("rl_hedge")
    recipe.update(seed=seed, n_epochs=3, n_paths=200)
    return recipe


def _three_ways(kind: str, recipe: dict[str, Any], root: Path) -> dict[str, str]:
    direct = execute_recipe(kind, recipe)

    store = JobStore(root / "jobs.sqlite3")
    artifacts = ArtifactStore(root / "objects")
    submitted = store.submit(
        kind, recipe, owner="alice", idempotency_key="k", timeout_seconds=120.0
    )
    via_jobs = Worker(store, artifacts, worker_id="parity").run_once()
    assert via_jobs is not None and via_jobs.job_id == submitted.job_id
    assert via_jobs.status == "succeeded", (via_jobs.error_code, via_jobs.diagnostic_id)

    session = LocalSession(root / "desktop")
    session.submit(kind, recipe, timeout_seconds=120.0)
    via_desktop = session.work_once()
    assert via_desktop is not None and via_desktop.status == "succeeded"

    prepared = prepare_recipe(kind, recipe)
    return {
        "direct": direct.manifest.result_hash,
        "jobs": str(via_jobs.result_hash),
        "desktop": str(via_desktop.result_hash),
        "recipe_direct": prepared.recipe_sha256,
        "recipe_jobs": str(via_jobs.recipe_sha256),
        "recipe_desktop": str(via_desktop.recipe_sha256),
    }


@pytest.mark.parametrize(("kind", "make"), [("economy", _economy), ("rl_hedge", _hedge)])
def test_the_direct_runner_the_job_engine_and_the_desktop_session_agree(
    tmp_path: Path, kind: str, make: Any
) -> None:
    got = _three_ways(kind, make(), tmp_path)
    assert got["direct"] == got["jobs"] == got["desktop"]
    assert got["recipe_direct"] == got["recipe_jobs"] == got["recipe_desktop"]


def test_a_different_seed_gives_a_different_result_so_agreement_is_not_vacuous(
    tmp_path: Path,
) -> None:
    first = _three_ways("rl_hedge", _hedge(0), tmp_path / "a")
    second = _three_ways("rl_hedge", _hedge(1), tmp_path / "b")
    assert first["direct"] != second["direct"]
    assert first["recipe_direct"] != second["recipe_direct"]
    assert second["direct"] == second["jobs"] == second["desktop"]
