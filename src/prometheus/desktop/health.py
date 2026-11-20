"""What the "System" page shows: is this installation the one the results came from, and what is
the standing of the project.

Nothing here is new machinery. The preflight checks are `doctor`'s (Python version, installed
dependency versions against `uv.lock`, the data manifest, a writable state directory); the data
table is the manifest `snapshot_integrity` verifies; the gate is `current_repository_gate_report`
-- the same code-generated NO-GO the dashboard and every artifact carry. This module only gathers
them into one object the window can draw, and does so without importing Qt, numpy or torch.
"""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

from prometheus.data_ingestion.snapshot_integrity import (
    COMMITTED_DATA_DIR,
    DataFileError,
    load_manifest,
    verify_directory,
)
from prometheus.doctor import LOCK_PATH, Check, run_checks
from prometheus.evidence.constants import SIMULATION_DISCLAIMER
from prometheus.evidence.repository_status import current_repository_gate_report

SHOWN_DISTRIBUTIONS = ("numpy", "scipy", "torch", "PySide6-Essentials", "pennylane", "cryptography")


@dataclass(frozen=True, slots=True)
class GateSummary:
    gate: str
    decision: str
    decided_at: str
    scope_prohibited: tuple[str, ...]
    open_findings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DataFile:
    name: str
    size: int
    sha256: str
    status: str
    """`ok`, `modified`, `missing` (listed, not on disk) or `unlisted` (on disk, not listed)."""


@dataclass(frozen=True, slots=True)
class HealthReport:
    app_version: str
    disclaimer: str
    gate: GateSummary
    checks: tuple[Check, ...]
    data_files: tuple[DataFile, ...]
    environment: tuple[tuple[str, str], ...]

    @property
    def failures(self) -> int:
        return sum(1 for check in self.checks if check.status == "fail")

    @property
    def warnings(self) -> int:
        return sum(1 for check in self.checks if check.status == "warn")

    @property
    def ok(self) -> bool:
        return self.failures == 0


def app_version() -> str:
    try:
        return metadata.version("prometheus-econ")
    except metadata.PackageNotFoundError:
        return "unknown"


def gate_summary() -> GateSummary:
    form = current_repository_gate_report()
    return GateSummary(
        gate=form.gate,
        decision=str(form.decision),
        decided_at=form.decided_at.isoformat(),
        scope_prohibited=form.scope_prohibited,
        open_findings=form.open_findings,
    )


def data_files(data_dir: Path = COMMITTED_DATA_DIR) -> tuple[DataFile, ...]:
    """Every file the manifest lists, with whether it still matches; plus any unlisted extra.

    An unreadable or malformed manifest yields no rows (the `data_integrity` check says why).
    """
    try:
        listed = load_manifest(data_dir)
        problems = {problem.name: problem.kind for problem in verify_directory(data_dir)}
    except (DataFileError, OSError):
        return ()
    rows = [
        DataFile(name, entry.size, entry.sha256, problems.get(name, "ok"))
        for name, entry in listed.items()
    ]
    rows.extend(
        DataFile(name, 0, "", kind) for name, kind in problems.items() if kind == "unlisted"
    )
    return tuple(sorted(rows, key=lambda row: row.name))


def environment() -> tuple[tuple[str, str], ...]:
    rows = [
        ("Application", app_version()),
        ("Python", platform.python_version()),
        ("Platform", platform.platform()),
        ("Interpreter", sys.executable),
    ]
    for name in SHOWN_DISTRIBUTIONS:
        try:
            rows.append((name, metadata.version(name)))
        except metadata.PackageNotFoundError:
            rows.append((name, "not installed"))
    return tuple(rows)


def collect_health(
    *,
    state_dir: Path | None = None,
    data_dir: Path = COMMITTED_DATA_DIR,
    lock_path: Path = LOCK_PATH,
) -> HealthReport:
    return HealthReport(
        app_version=app_version(),
        disclaimer=SIMULATION_DISCLAIMER,
        gate=gate_summary(),
        checks=tuple(run_checks(state_dir=state_dir, lock_path=lock_path)),
        data_files=data_files(data_dir),
        environment=environment(),
    )
