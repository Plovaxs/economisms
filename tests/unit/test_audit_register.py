"""The audit response register: valid, rendered, complete, honest about scores, and in step.

The audit's weighted score is recomputed rather than trusted, the baseline scores are PINNED so that
raising one is a deliberate edit of this file (the audit's rule is that a score moves only with
independent evidence, and nothing in the repository is independent), and the validator is exercised
on registers that break each rule.
"""

from __future__ import annotations

import copy
import hashlib
import re
import subprocess
from pathlib import Path

import pytest

from prometheus.evidence import audit_register as register

ROOT = Path(__file__).resolve().parents[2]
BASELINE_SCORES = [
    9.3, 8.8, 7.0, 8.0, 7.5, 7.5, 7.5, 8.5, 8.0, 6.8,
    9.0, 9.2, 9.3, 9.0, 8.5, 9.4, 8.0, 8.0, 8.0, 5.5,
]  # fmt: skip
BASELINE_WEIGHTS = [7, 6, 7, 7, 6, 5, 5, 5, 5, 5, 5, 4, 5, 5, 4, 4, 4, 3, 3, 5]
REQUIRED_IDS = (
    [f"SCI-{n:02d}" for n in range(1, 9)]
    + [f"M-{n:02d}" for n in range(1, 9)]
    + [f"D-{n:02d}" for n in range(1, 9)]
    + [f"L-{n:02d}" for n in range(1, 10)]
    + [f"Q-{n}" for n in range(1, 9)]
    + [f"RM-{n}" for n in range(0, 7)]
    + [f"R-{n}" for n in range(1, 11)]
)
COMMIT = "05905835dbb6729bb9f79c629027b8ba47176e44"


def _doc() -> dict:
    return register.load()


def test_the_committed_register_is_valid_and_its_rendering_is_current() -> None:
    assert register.problems(_doc()) == []
    assert register.RENDERED_PATH.read_text(encoding="utf-8") == register.render(_doc())
    assert register.main(["check"]) == 0


def test_every_item_the_audit_names_is_in_the_register_exactly_once() -> None:
    ids = [item["id"] for item in _doc()["items"]]
    assert sorted(ids) == sorted(REQUIRED_IDS)


def test_the_weighted_score_is_recomputed_and_equals_the_audits_figure() -> None:
    document = _doc()
    assert register.weighted_score(document) == pytest.approx(8.118, abs=5e-4)
    assert sum(c["weight"] for c in document["scorecard"]["criteria"]) == 100


def test_the_baseline_scores_and_weights_are_the_reviewers_and_unchanged() -> None:
    """To change a score, edit this test and say what E3 or E4 evidence justifies it."""
    criteria = _doc()["scorecard"]["criteria"]
    assert [c["score"] for c in criteria] == BASELINE_SCORES
    assert [c["weight"] for c in criteria] == BASELINE_WEIGHTS
    assert all(item["evidence_level"] in {"E0", "E1", "E2"} for item in _doc()["items"])


def test_the_validator_rejects_each_kind_of_overclaim_or_slip() -> None:
    good = _doc()

    def broken(mutate) -> list[str]:  # type: ignore[no-untyped-def]
        document = copy.deepcopy(good)
        mutate(document)
        return register.problems(document)

    first = lambda d: d["items"][0]  # noqa: E731
    assert any(
        "sum to 100" in p for p in broken(lambda d: d["scorecard"]["criteria"][0].update(weight=8))
    )
    assert any("unknown status" in p for p in broken(lambda d: first(d).update(status="finished")))
    assert any(
        "unknown evidence level" in p
        for p in broken(lambda d: first(d).update(evidence_level="E9"))
    )
    assert any(
        "no evidence" in p for p in broken(lambda d: first(d).update(status="done", evidence=[]))
    )
    assert any(
        "E0/E1" in p for p in broken(lambda d: first(d).update(status="done", evidence_level="E1"))
    )
    assert any(
        "does not exist" in p for p in broken(lambda d: first(d)["evidence"].append("no/such/file"))
    )
    assert any(
        "nothing here is independent" in p
        for p in broken(lambda d: first(d).update(evidence_level="E3"))
    )
    assert any(
        "duplicate" in p for p in broken(lambda d: d["items"].append(copy.deepcopy(first(d))))
    )


def test_the_roadmap_table_agrees_with_the_register_on_every_milestone() -> None:
    roadmap = (ROOT / "docs" / "ROADMAP.md").read_text(encoding="utf-8")
    by_id = {item["id"]: item for item in _doc()["items"]}
    for n in range(0, 7):
        row = next(line for line in roadmap.splitlines() if line.startswith(f"| **M{n} "))
        status = by_id[f"RM-{n}"]["status"]
        assert ("**Done**" in row) == (status == "done"), (n, status)
        assert ("Partial" in row) == (status == "partial"), (n, status)


def _manifest() -> tuple[list[str], list[tuple[str, int, str]]]:
    lines = (
        (ROOT / "docs" / "audit" / "source_manifest_05905835.txt")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    header = [line for line in lines if line.startswith("#")]
    entries = []
    for line in lines:
        if line.startswith("#"):
            continue
        match = re.fullmatch(r"([0-9a-f]{64})  (\d+)  (.+)", line)
        assert match, line
        entries.append((match.group(1), int(match.group(2)), match.group(3)))
    return header, entries


def test_the_source_manifest_is_well_formed_and_the_baseline_document_agrees_with_it() -> None:
    header, entries = _manifest()
    assert f"# commit {COMMIT}" in header
    assert f"# files  {len(entries)}" in header
    assert [p for _, _, p in entries] == sorted(p for _, _, p in entries)
    baseline = (ROOT / "docs" / "audit" / "BASELINE.md").read_text(encoding="utf-8")
    assert COMMIT in baseline and f"{len(entries)} files" in baseline


def _commit_available() -> bool:
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{COMMIT}^{{commit}}"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


@pytest.mark.skipif(not _commit_available(), reason="the audited commit is not in this clone")
def test_every_manifest_entry_matches_the_content_at_that_commit() -> None:
    _, entries = _manifest()
    for digest, size, path in entries:
        blob = subprocess.run(
            ["git", "show", f"{COMMIT}:{path}"], cwd=ROOT, capture_output=True, check=True
        ).stdout
        assert (hashlib.sha256(blob).hexdigest(), len(blob)) == (digest, size), path
