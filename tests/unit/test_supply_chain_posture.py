"""Mechanical checks on the supply-chain posture of the repository itself:
the CI workflows, the dependency-update config, the lockfile and the linter
configuration. They exist so the posture cannot erode silently -- an unpinned
action, a workflow with write permissions or no timeout, or a weakened ruff
configuration fails here, in the same run that would have shipped it.

The workflows are scanned line by line rather than parsed: PyYAML is not a
dependency of this project, and the invariants below are about the shape of a
few well-known lines, not about YAML semantics."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
WORKFLOWS = sorted(WORKFLOW_DIR.glob("*.yml"))
EXPECTED = {
    "ci.yml",
    "docker-build.yml",
    "frontend-ci.yml",
    "security.yml",
    "codeql.yml",
    "release.yml",
}


def _jobs(text: str) -> dict[str, list[str]]:
    blocks: dict[str, list[str]] = {}
    in_jobs, current = False, None
    for line in text.splitlines():
        if re.match(r"^jobs:\s*$", line):
            in_jobs = True
            continue
        if not in_jobs:
            continue
        if re.match(r"^\S", line):
            break
        header = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if header:
            current = header.group(1)
            blocks[current] = []
        elif current is not None:
            blocks[current].append(line)
    return blocks


def test_every_expected_workflow_exists() -> None:
    assert EXPECTED <= {path.name for path in WORKFLOWS}


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_every_action_is_pinned_to_a_full_commit_sha_with_a_version_comment(path) -> None:
    uses = 0
    for number, line in enumerate(path.read_text().splitlines(), 1):
        match = re.match(r"^\s*-?\s*uses:\s*(\S+)(.*)$", line)
        if match is None:
            continue
        uses += 1
        reference, rest = match.groups()
        if reference.startswith("./"):
            continue
        assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", reference), (
            f"{path.name}:{number} must pin {reference!r} to a 40-hex commit SHA, not a tag "
            "(a tag can be moved to different code after it was reviewed)"
        )
        assert re.search(r"#\s*v\d+\.\d+\.\d+", rest), (
            f"{path.name}:{number} needs a trailing '# vX.Y.Z' comment naming the pinned release"
        )
    assert uses > 0, f"{path.name} uses no actions at all -- is the scan broken?"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_every_workflow_declares_read_only_permissions_at_the_top(path) -> None:
    text = path.read_text()
    assert re.search(r"^permissions:\n  contents: read\n(?!  \S)", text, re.M), (
        f"{path.name} must declare a top-level `permissions: contents: read` and nothing broader"
    )
    assert "write-all" not in text


def test_only_codeql_and_the_release_publish_job_may_write_anything() -> None:
    for path in WORKFLOWS:
        writes = re.findall(r"^\s+([\w-]+):\s*write\s*$", path.read_text(), re.M)
        if path.name == "codeql.yml":
            assert writes == ["security-events"], writes
        elif path.name == "release.yml":
            # one write, `contents`, in the one job that publishes, which runs for a tag only
            assert writes == ["contents"], writes
            jobs = _jobs(path.read_text())
            owners = [
                n for n, b in jobs.items() if any(re.search(r"contents:\s*write", x) for x in b)
            ]
            assert owners == ["publish"], owners
            assert any("github.ref_type == 'tag'" in x for x in jobs["publish"]), "only for a tag"
        else:
            assert writes == [], (path.name, writes)


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_every_job_has_a_timeout(path) -> None:
    jobs = _jobs(path.read_text())
    assert jobs, f"{path.name} has no jobs -- is the scan broken?"
    for name, block in jobs.items():
        assert any(re.match(r"^    timeout-minutes:\s*\d+\s*$", line) for line in block), (
            f"{path.name}: job {name!r} has no timeout-minutes (the default is six hours)"
        )


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_checkout_never_persists_the_token_into_the_workspace(path) -> None:
    lines = path.read_text().splitlines()
    for index, line in enumerate(lines):
        if re.match(r"^\s*-?\s*uses:\s*actions/checkout@", line):
            window = "\n".join(lines[index + 1 : index + 4])
            assert "persist-credentials: false" in window, f"{path.name}:{index + 1}"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_no_dangerous_trigger_and_no_untrusted_context_reaches_a_script(path) -> None:
    text = path.read_text()
    assert "pull_request_target" not in text
    assert "workflow_run" not in text
    untrusted = re.findall(
        r"\$\{\{\s*github\.(?:event\.(?:issue|pull_request|comment|review|head_commit|pages)"
        r"|head_ref)[^}]*\}\}",
        text,
    )
    assert untrusted == [], f"attacker-controlled text interpolated in {path.name}: {untrusted}"


def test_the_ci_matrix_still_runs_the_tests_the_security_workflow_does_not_replace() -> None:
    ci = (WORKFLOW_DIR / "ci.yml").read_text()
    assert "pytest" in ci and "mypy --strict" in ci and "ruff check" in ci


def test_dependabot_watches_every_ecosystem_in_use() -> None:
    config = (ROOT / ".github" / "dependabot.yml").read_text()
    for ecosystem in ("github-actions", "npm", "uv", "docker"):
        assert f'package-ecosystem: "{ecosystem}"' in config
    assert 'directory: "/frontend"' in config
    # The numerics stack is deliberately excluded from automated bumps: a new
    # torch/numpy/scipy changes floating-point results the reference bundles pin.
    for name in ("torch", "numpy", "scipy"):
        assert f'dependency-name: "{name}"' in config


def test_the_audit_tool_is_hash_locked_like_every_other_dependency() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert pyproject["dependency-groups"]["security"] == ["pip-audit==2.10.1"]
    lock = (ROOT / "uv.lock").read_text()
    block = re.search(
        r'\[\[package\]\]\nname = "pip-audit"\n(.*?)(?=\n\[\[package\]\]|\Z)', lock, re.S
    )
    assert block is not None, "pip-audit is not in uv.lock"
    assert 'version = "2.10.1"' in block.group(1)
    assert block.group(1).count("sha256:") >= 2, "pip-audit's artifacts must carry hashes"


def test_the_security_workflow_audits_the_lock_and_installs_only_the_audit_group() -> None:
    text = (WORKFLOW_DIR / "security.yml").read_text()
    assert "--only-group security" in text
    assert "uv export --locked --all-extras --all-groups" in text
    assert "pip-audit" in text and "--no-deps --disable-pip" in text
    assert "npm audit" in text and "npm audit signatures" in text
    assert "trivy-action" in text and "ignore-unfixed: true" in text
    assert "schedule:" in text, "a weekly run is what notices a NEW advisory"


def test_ruff_security_rules_are_on_and_src_has_no_blanket_ignore() -> None:
    ruff = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["ruff"]["lint"]
    assert "S" in ruff["select"]
    ignores = ruff.get("per-file-ignores", {})
    assert set(ignores) <= {"tests/**"}, (
        "src/ and tools/ must carry per-line, justified `# noqa: Sxxx` -- not a blanket ignore"
    )
    assert "S101" in ignores["tests/**"]


def test_every_security_noqa_in_src_names_its_rule_and_never_blankets() -> None:
    for path in (ROOT / "src").rglob("*.py"):
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if "noqa" in line:
                assert "# noqa:" in line or "# noqa :" in line, (
                    f"{path.relative_to(ROOT)}:{number}: a bare `# noqa` silences every rule"
                )
