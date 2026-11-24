"""The mutation catalogue cannot go stale, and the tool that runs it cannot damage the tree.

The mutations themselves take minutes and run in `.github/workflows/mutation-check.yml`; what runs
on every test pass is the cheap part: each mutation's snippet still occurs exactly once (so a
refactor that moves a line fails here, not silently), and the harness restores a file whether the
mutation was caught or missed.
"""

from __future__ import annotations

import runpy
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "mutation_check.py"


@pytest.fixture(scope="module")
def tool() -> dict[str, Any]:
    return runpy.run_path(str(TOOL))


def test_every_snippet_occurs_exactly_once_and_names_a_real_test(tool: dict[str, Any]) -> None:
    stale = [m.name for m in tool["MUTATIONS"] if tool["occurrences"](m) != 1]
    assert stale == [], f"the catalogue no longer matches the code: {stale}"
    for mutation in tool["MUTATIONS"]:
        assert mutation.old != mutation.new, mutation.name
        assert mutation.tests and all((ROOT / t).exists() for t in mutation.tests), mutation.name


def test_names_are_unique_and_the_critical_modules_are_all_covered(tool: dict[str, Any]) -> None:
    names = [m.name for m in tool["MUTATIONS"]]
    assert len(names) == len(set(names))
    covered = {m.file for m in tool["MUTATIONS"]}
    assert covered >= {
        "core/ledger.py",
        "volterra/black_scholes.py",
        "titan/risk_metrics.py",
        "hedging/simulate.py",
        "experiments/block_bootstrap.py",
    }


def _scratch_tree(tmp_path: Path, test_body: str) -> Path:
    src = tmp_path / "src" / "prometheus"
    src.mkdir(parents=True)
    (src / "m.py").write_text("VALUE = 1\nOTHER = 2\n")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_m.py").write_text(test_body)
    return src


_CHECKS_VALUE = (
    "from pathlib import Path\n\n"
    "def test_value() -> None:\n"
    "    assert 'VALUE = 1' in (Path(__file__).parents[1] / 'src/prometheus/m.py').read_text()\n"
)
_CHECKS_NOTHING = "def test_nothing() -> None:\n    assert True\n"


@pytest.mark.parametrize(
    ("body", "caught"), [(_CHECKS_VALUE, True), (_CHECKS_NOTHING, False)], ids=["caught", "missed"]
)
def test_the_harness_reports_the_outcome_and_always_restores_the_file(
    tool: dict[str, Any], tmp_path: Path, body: str, caught: bool
) -> None:
    src = _scratch_tree(tmp_path, body)
    scratch = dict(tool)
    scratch["ROOT"], scratch["SRC"] = tmp_path, src
    run_one = tool["run_one"]
    # run_one reads the module globals at call time, so point them at the scratch tree
    run_one.__globals__.update(ROOT=tmp_path, SRC=src)
    try:
        mutation = tool["Mutation"](
            "scratch", "m.py", "VALUE = 1", "VALUE = 99", ("tests/test_m.py",)
        )
        outcome = run_one(mutation)
    finally:
        run_one.__globals__.update(ROOT=ROOT, SRC=ROOT / "src" / "prometheus")
    assert outcome["caught"] is caught
    assert (src / "m.py").read_text() == "VALUE = 1\nOTHER = 2\n"
    assert list(src.glob("*.mutation-backup")) == []
