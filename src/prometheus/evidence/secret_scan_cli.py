"""Command-line front end for `security_scan`: refuse a commit that stages a secret.

    python -m prometheus.evidence.secret_scan_cli --staged   # what the pre-commit hook runs
    python -m prometheus.evidence.secret_scan_cli --all      # every tracked file (working tree)

The test suite already fails the build when a tracked file holds a secret
(`test_security_scan.py::test_no_tracked_file_contains_a_secret_or_has_a_sensitive_name`),
but CI runs AFTER a push, by which time the secret is on a remote. `--staged` runs
BEFORE the commit exists, over the INDEX content (what would be committed, not what
happens to be on disk), so the secret never enters history. `.githooks/pre-commit`
calls it; enable it once with `git config core.hooksPath .githooks`. `git commit
--no-verify` bypasses any hook -- this is a safety net against accidents (a token pasted
into a file, an `.env` added by `git add -A`), not a control against a person who means it.

A finding is reported as `path:line: description` ONLY. The matched text is never printed
or logged: a scanner that echoes the secret it found would put it in a terminal scrollback
and a CI log.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from prometheus.evidence.security_scan import ScanFinding, path_scan, secret_scan

MAX_SCANNED_BYTES = 2 * 1024 * 1024
"""Files above this size are not content-scanned (the repository's 7-16 MB numeric replay
dumps); their NAMES are still checked."""
_GIT_TIMEOUT_SECONDS = 60


def _git(repo: Path, *args: str) -> bytes:
    # Fixed argv, no shell, a bounded runtime: nothing here is built from untrusted text.
    return subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=repo,
        capture_output=True,
        check=True,
        timeout=_GIT_TIMEOUT_SECONDS,
    ).stdout


def _split(raw: bytes) -> list[str]:
    return [name for name in raw.decode("utf-8", errors="surrogateescape").split("\0") if name]


def staged_paths(repo: Path) -> list[str]:
    """Paths added, copied, modified or renamed in the index (a deletion stages nothing to leak)."""
    return _split(_git(repo, "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"))


def tracked_paths(repo: Path) -> list[str]:
    return _split(_git(repo, "ls-files", "-z"))


def _decode(data: bytes) -> str | None:
    if len(data) > MAX_SCANNED_BYTES:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def read_texts(
    repo: Path, paths: Sequence[str], *, from_index: bool
) -> tuple[dict[str, str], list[str]]:
    """(text per readable path, paths whose CONTENT was not scanned). `from_index` reads the
    staged blob (`git show :path`); otherwise the working-tree file."""
    texts: dict[str, str] = {}
    skipped: list[str] = []
    for name in paths:
        try:
            data = _git(repo, "show", f":{name}") if from_index else (repo / name).read_bytes()
        except (OSError, subprocess.CalledProcessError):
            skipped.append(name)  # a submodule, a deleted path, a directory
            continue
        text = _decode(data)
        if text is None:
            skipped.append(name)
        else:
            texts[name] = text
    return texts, skipped


def scan_paths(repo: Path, paths: Sequence[str], *, from_index: bool) -> list[ScanFinding]:
    texts, _ = read_texts(repo, paths, from_index=from_index)
    return [*path_scan(paths), *secret_scan(texts)]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="secret_scan_cli", description="Scan staged or tracked files for secrets."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--staged", action="store_true", help="scan the index (pre-commit)")
    mode.add_argument("--all", action="store_true", help="scan every tracked file")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    repo: Path = args.repo
    try:
        paths = staged_paths(repo) if args.staged else tracked_paths(repo)
        findings = scan_paths(repo, paths, from_index=bool(args.staged))
    except (OSError, subprocess.SubprocessError) as exc:
        # Fail closed: a hook that cannot run must not wave a commit through.
        print(f"secret scan could not run: {type(exc).__name__}", file=sys.stderr)
        return 2
    if not findings:
        print(f"secret scan: {len(paths)} file(s) checked, nothing found")
        return 0
    for finding in findings:
        print(f"{finding.location}: {finding.description}", file=sys.stderr)
    print(
        f"secret scan: {len(findings)} finding(s). The matched text is not printed. Remove it "
        "(and rotate it if it was ever real) before committing; `git commit --no-verify` "
        "bypasses this check.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
