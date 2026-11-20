"""PR-201: the pre-commit secret scan.

Real `git` in throwaway repositories: what is staged is scanned (the index, not the
working tree), a finding names the place and kind but never the text, a scanner that
cannot run fails closed, and the hook script really blocks a `git commit`.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from prometheus.evidence import secret_scan_cli as cli
from prometheus.evidence.secret_scan_cli import main, read_texts, staged_paths, tracked_paths

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = REPO_ROOT / ".githooks" / "pre-commit"
# Assembled at run time: the whole-repository sweep scans this file with no allowlist.
FAKE_TOKEN = "KGAT_" + "0123456789abcdef0123456789abcdef"

_ENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def git(
    repo: Path, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo, env=env or _ENV, capture_output=True, text=True, timeout=60
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    assert git(root, "init", "-q").returncode == 0
    return root


def stage(repo: Path, name: str, content: str | bytes) -> None:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content)
    assert git(repo, "add", name).returncode == 0


def run(repo: Path, *flags: str) -> int:
    return main([*flags, "--repo", str(repo)])


# ------------------------------------------------------------------ staged content


def test_a_clean_staged_file_passes(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    stage(repo, "a.py", "print('hello')\n")
    assert run(repo, "--staged") == 0
    assert "1 file(s) checked, nothing found" in capsys.readouterr().out


def test_a_staged_secret_is_refused_and_the_secret_is_never_printed(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stage(repo, "notes.md", f"line one\nvalue {FAKE_TOKEN}\n")
    assert run(repo, "--staged") == 1
    captured = capsys.readouterr()
    assert "notes.md:2: Kaggle API token" in captured.err
    assert FAKE_TOKEN not in captured.out + captured.err
    assert "0123456789abcdef" not in captured.out + captured.err


def test_the_index_is_scanned_not_the_working_tree(repo: Path) -> None:
    """What would be committed is what counts: a clean staged blob passes even if the file
    on disk was edited afterwards, and a staged secret fails even if it was then removed."""
    stage(repo, "f.txt", "clean\n")
    (repo / "f.txt").write_text(f"{FAKE_TOKEN}\n")  # edited, NOT staged
    assert run(repo, "--staged") == 0
    stage(repo, "g.txt", f"{FAKE_TOKEN}\n")
    (repo / "g.txt").write_text("clean again\n")  # the leak is still in the index
    assert run(repo, "--staged") == 1


def test_an_unstaged_untracked_secret_is_not_this_commits_problem(repo: Path) -> None:
    stage(repo, "ok.txt", "fine\n")
    (repo / "scratch.txt").write_text(f"{FAKE_TOKEN}\n")
    assert run(repo, "--staged") == 0


def test_a_staged_file_with_a_sensitive_name_is_refused_even_with_harmless_content(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stage(repo, ".env", "DEBUG=1\n")
    assert run(repo, "--staged") == 1
    assert ".env: sensitive file name (environment file)" in capsys.readouterr().err


def test_a_deletion_stages_nothing_to_scan(repo: Path) -> None:
    stage(repo, "old.txt", "x\n")
    assert git(repo, "commit", "-q", "-m", "seed").returncode == 0
    assert git(repo, "rm", "-q", "old.txt").returncode == 0
    assert staged_paths(repo) == []
    assert run(repo, "--staged") == 0


def test_binary_and_oversized_files_are_skipped_not_crashed_on(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stage(repo, "blob.bin", b"\xff\xfe\x00\x01")
    stage(repo, "big.txt", "x" * 50)
    monkeypatch.setattr(cli, "MAX_SCANNED_BYTES", 10)
    texts, skipped = read_texts(repo, ["blob.bin", "big.txt"], from_index=True)
    assert texts == {} and sorted(skipped) == ["big.txt", "blob.bin"]
    assert run(repo, "--staged") == 0


def test_a_rename_is_scanned_under_its_new_name(repo: Path) -> None:
    stage(repo, "a.txt", "innocent\n")
    assert git(repo, "commit", "-q", "-m", "seed").returncode == 0
    assert git(repo, "mv", "a.txt", ".env").returncode == 0
    assert staged_paths(repo) == [".env"]
    assert run(repo, "--staged") == 1


# ------------------------------------------------------------------ --all and failure modes


def test_all_mode_scans_every_tracked_file(repo: Path) -> None:
    stage(repo, "clean.txt", "fine\n")
    stage(repo, "dirty.txt", f"{FAKE_TOKEN}\n")
    assert git(repo, "commit", "-q", "-m", "seed").returncode == 0
    assert sorted(tracked_paths(repo)) == ["clean.txt", "dirty.txt"]
    assert run(repo, "--all") == 1


def test_a_scan_that_cannot_run_fails_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    not_a_repo = tmp_path / "plain"
    not_a_repo.mkdir()
    assert run(not_a_repo, "--staged") == 2
    assert "could not run" in capsys.readouterr().err


def test_one_mode_is_required() -> None:
    with pytest.raises(SystemExit):
        main([])


# ------------------------------------------------------------------ the hook itself


def _hook_env() -> dict[str, str]:
    return {
        **_ENV,
        "PYTHON": sys.executable,
        "PYTHONPATH": str(REPO_ROOT / "src"),
    }


def _install_hook(repo: Path) -> None:
    hooks = repo / ".githooks"
    hooks.mkdir()
    target = hooks / "pre-commit"
    target.write_text(HOOK.read_text())
    target.chmod(0o755)
    assert git(repo, "config", "core.hooksPath", ".githooks").returncode == 0


def test_the_hook_blocks_a_real_commit_with_a_secret_and_allows_a_clean_one(repo: Path) -> None:
    _install_hook(repo)
    env = _hook_env()
    stage(repo, "notes.md", f"value {FAKE_TOKEN}\n")
    blocked = git(repo, "commit", "-m", "leak", env=env)
    assert blocked.returncode != 0
    assert FAKE_TOKEN not in blocked.stdout + blocked.stderr
    assert "Kaggle API token" in blocked.stderr
    assert git(repo, "rev-parse", "--verify", "HEAD", env=env).returncode != 0, "nothing committed"

    assert git(repo, "rm", "-q", "--cached", "notes.md", env=env).returncode == 0
    stage(repo, "ok.md", "nothing secret here\n")
    assert git(repo, "commit", "-m", "fine", env=env).returncode == 0


def test_the_hook_can_be_bypassed_deliberately_and_says_so(repo: Path) -> None:
    """`--no-verify` is Git's own escape hatch: the hook is an accident-catcher."""
    _install_hook(repo)
    stage(repo, "notes.md", f"value {FAKE_TOKEN}\n")
    assert git(repo, "commit", "--no-verify", "-m", "x", env=_hook_env()).returncode == 0
    assert "--no-verify" in HOOK.read_text()


def test_the_committed_hook_is_executable_and_runs_the_staged_scan() -> None:
    assert HOOK.is_file() and os.access(HOOK, os.X_OK)
    text = HOOK.read_text()
    assert text.startswith("#!/bin/sh\n") and "set -eu" in text
    assert "prometheus.evidence.secret_scan_cli --staged" in text
    assert "git config core.hooksPath .githooks" in text


def test_this_repositorys_own_tracked_files_pass_the_scan() -> None:
    if not (REPO_ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    assert run(REPO_ROOT, "--all") == 0
