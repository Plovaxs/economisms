"""`econosim doctor`: a preflight check that this environment is the one the results came from.

Every number in this repository was produced under the exact dependency versions pinned in
`uv.lock` (CI found, more than once, that a different numpy changes a result), on data that
matches `data_cache/MANIFEST.sha256.json`. Before starting a service or trusting a run, `doctor`
answers six questions and exits non-zero if any answer is "fail":

- the Python version is supported;
- the installed versions of the locked dependencies match `uv.lock` (a mismatch in the numerical
  stack is a failure, any other a warning; a locked package that is not installed -- an extra you
  did not ask for, a wheel for another platform -- is skipped, not guessed at);
- every committed data snapshot still matches its manifest;
- the credentials file, if one is named, is a regular file that only its owner can read;
- the state directory, if one is named, is writable;
- the frontend build exists (a warning only: the research API works without it).

It makes no network call and changes nothing on disk except a short-lived probe file in the state
directory. It is a diagnostic, not a security control: it tells an operator what is wrong, it
does not stop anything from starting.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import tempfile
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from importlib import metadata
from pathlib import Path

from prometheus.data_ingestion.snapshot_integrity import (
    COMMITTED_DATA_DIR,
    DataFileError,
    verify_directory,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = REPO_ROOT / "uv.lock"
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"
MIN_PYTHON = (3, 11)
NUMERICAL_STACK = frozenset({"numpy", "scipy", "torch", "pennylane", "pennylane-lightning"})
"""Packages whose version changes numerical results, so a drift here is a failure."""


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    status: str
    """`ok`, `warn`, `fail` or `skip`."""
    detail: str


def check_python(version_info: tuple[int, ...] | None = None) -> Check:
    found = tuple(sys.version_info[:3]) if version_info is None else version_info
    label = ".".join(str(part) for part in found[:3])
    if found[:2] >= MIN_PYTHON:
        return Check("python", "ok", f"{label} (needs {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+)")
    return Check("python", "fail", f"{label} is older than {MIN_PYTHON[0]}.{MIN_PYTHON[1]}")


def _public(version: str) -> str:
    return version.split("+", 1)[0]


def check_locked_dependencies(
    lock_path: Path = LOCK_PATH, *, installed: Callable[[str], str] = metadata.version
) -> Check:
    if not lock_path.is_file():
        return Check("locked_dependencies", "skip", "no uv.lock next to the installed package")
    try:
        lock = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        return Check("locked_dependencies", "fail", f"cannot read uv.lock ({type(exc).__name__})")
    locked: dict[str, set[str]] = {}
    for package in lock.get("package", []):
        source = package.get("source", {})
        if "editable" in source or "virtual" in source:
            continue  # the project itself
        locked.setdefault(package["name"], set()).add(package["version"])
    mismatched: list[tuple[str, str, list[str]]] = []
    not_installed = 0
    for name, versions in sorted(locked.items()):
        try:
            found = installed(name)
        except metadata.PackageNotFoundError:
            not_installed += 1
            continue
        # a lock can hold several versions per name (one per Python/platform fork); a local
        # tag such as `+cpu` is a build detail, not a different release
        if found not in versions and _public(found) not in {_public(v) for v in versions}:
            mismatched.append((name, found, sorted(versions)))
    checked = len(locked) - not_installed
    summary = f"{checked} installed packages checked, {not_installed} locked but not installed"
    if not mismatched:
        return Check("locked_dependencies", "ok", f"{summary}; all match uv.lock")
    text = ", ".join(f"{n} {found} (locked {'/'.join(v)})" for n, found, v in mismatched[:6])
    critical = [m for m in mismatched if m[0] in NUMERICAL_STACK]
    status = "fail" if critical else "warn"
    return Check(
        "locked_dependencies", status, f"{summary}; {len(mismatched)} differ from uv.lock: {text}"
    )


def check_data_integrity(data_dir: Path | None = None) -> Check:
    root = COMMITTED_DATA_DIR if data_dir is None else data_dir
    if not root.is_dir():
        return Check("data_integrity", "skip", f"no {root.name}/ directory next to the package")
    try:
        problems = verify_directory(root)
    except DataFileError as exc:
        return Check("data_integrity", "fail", str(exc))
    if problems:
        names = ", ".join(f"{p.kind} {p.name}" for p in problems[:5])
        return Check("data_integrity", "fail", f"{len(problems)} problem(s): {names}")
    return Check("data_integrity", "ok", f"every file in {root.name}/ matches its manifest entry")


def check_credentials_file(path: Path | None) -> Check:
    if path is None:
        return Check("credentials_file", "skip", "no --credentials given")
    try:
        info = os.lstat(path)
    except OSError as exc:
        return Check("credentials_file", "fail", f"cannot stat {path.name}: {type(exc).__name__}")
    if stat.S_ISLNK(info.st_mode):
        return Check("credentials_file", "fail", f"{path.name} is a symlink")
    if not stat.S_ISREG(info.st_mode):
        return Check("credentials_file", "fail", f"{path.name} is not a regular file")
    if info.st_mode & 0o077:
        mode = stat.S_IMODE(info.st_mode)
        return Check(
            "credentials_file",
            "fail",
            f"{path.name} has mode {mode:04o}: readable by group or others (expected 0600)",
        )
    return Check(
        "credentials_file", "ok", f"{path.name} is a regular file readable only by its owner"
    )


def check_state_directory(path: Path | None) -> Check:
    if path is None:
        return Check("state_directory", "skip", "no --state-dir given")
    if not path.is_dir():
        return Check("state_directory", "fail", f"{path.name} is not a directory")
    try:
        with tempfile.NamedTemporaryFile(dir=path, prefix=".doctor-"):
            pass
    except OSError as exc:
        return Check(
            "state_directory", "fail", f"{path.name} is not writable ({type(exc).__name__})"
        )
    return Check("state_directory", "ok", f"{path.name} is writable")


def check_frontend_build(dist: Path = FRONTEND_DIST) -> Check:
    if (dist / "index.html").is_file():
        return Check("frontend_build", "ok", "frontend/dist/index.html exists")
    return Check(
        "frontend_build",
        "warn",
        "frontend/dist is missing (`npm run build` in frontend/); the API works without it",
    )


def run_checks(
    *,
    credentials: Path | None = None,
    state_dir: Path | None = None,
    lock_path: Path = LOCK_PATH,
) -> list[Check]:
    return [
        check_python(),
        check_locked_dependencies(lock_path),
        check_data_integrity(),
        check_credentials_file(credentials),
        check_state_directory(state_dir),
        check_frontend_build(),
    ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="econosim doctor", description="Preflight check of this environment."
    )
    parser.add_argument("--credentials", type=Path, help="a service credentials file to inspect")
    parser.add_argument(
        "--state-dir", type=Path, help="a job-store directory that must be writable"
    )
    parser.add_argument(
        "--lock", type=Path, default=LOCK_PATH, help="the uv.lock to compare against"
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)
    checks = run_checks(credentials=args.credentials, state_dir=args.state_dir, lock_path=args.lock)
    failed = [c for c in checks if c.status == "fail"]
    if args.json:
        print(json.dumps({"ok": not failed, "checks": [asdict(c) for c in checks]}, indent=2))
    else:
        for check in checks:
            print(f"[{check.status:4}] {check.name}: {check.detail}")
        print("doctor: all clear" if not failed else f"doctor: {len(failed)} check(s) failed")
    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
