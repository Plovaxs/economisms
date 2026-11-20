"""`econosim desktop --check`: does every part of the application work on this machine, no window?

It exercises the real thing end to end in a throwaway state directory (the user's own results are
never touched): every runner's form against its default recipe, the state-directory rules, the
seven explorers in their child processes, one small real job through the isolated worker with its
result read back through hash verification, the findings document, the health report, and whether
Qt is installed. It exists for three readers: a person who wants to know "is this install
healthy?", CI (a smoke test of everything that does not need a display), and `doctor`'s habit of
saying what is wrong rather than failing mysteriously later.

Every step reports `ok`, `fail` or `skip`; only `fail` makes the exit status non-zero. A missing Qt
is a `skip`, because the research engine is useful without the window.
"""

from __future__ import annotations

import importlib.util
import stat
import tempfile
import time
from collections.abc import Callable
from importlib import metadata
from pathlib import Path

from prometheus.desktop import displaycheck, explorers, findings, forms, health, launcher
from prometheus.desktop.explorer_runner import run_explorer
from prometheus.desktop.session import LocalSession
from prometheus.doctor import Check
from prometheus.orchestration.recipes import RUNNERS, default_recipe, prepare_recipe

SMOKE_KIND = "inflationcast"


def _small_recipe() -> dict[str, object]:
    recipe = default_recipe(SMOKE_KIND)
    recipe.update(max_epochs=3, bootstrap_resamples=20)
    return recipe


def check_forms() -> Check:
    problems: list[str] = []
    for kind in RUNNERS:
        specs = forms.build_form(kind)
        config, errors = forms.assemble(specs, forms.initial_values(specs))
        if errors:
            problems.append(f"{kind}: {sorted(errors)}")
        elif (
            prepare_recipe(kind, config).recipe_sha256
            != prepare_recipe(kind, default_recipe(kind)).recipe_sha256
        ):
            problems.append(f"{kind}: the form does not reproduce the default recipe")
    if problems:
        return Check("forms", "fail", "; ".join(problems))
    return Check("forms", "ok", f"all {len(RUNNERS)} runners' forms reproduce their default recipe")


def check_explorers() -> Check:
    failures: list[str] = []
    for explorer in explorers.EXPLORERS:
        params, errors = explorers.validate(explorer.name, explorers.defaults(explorer.name))
        if errors:
            failures.append(f"{explorer.name}: {errors}")
            continue
        try:
            run_explorer(explorer.name, params, timeout=60.0)
        except Exception as exc:  # report every explorer, not just the first to fail
            failures.append(f"{explorer.name}: {exc}")
    if failures:
        return Check("explorers", "fail", "; ".join(failures))
    return Check("explorers", "ok", f"all {len(explorers.EXPLORERS)} ran in child processes")


def check_job(root: Path) -> Check:
    session = LocalSession(root / "state")
    if not session.can_run_jobs:
        return Check(
            "job", "skip", "the isolated worker needs Linux; this platform cannot run jobs"
        )
    mode = stat.S_IMODE(session.root.stat().st_mode)
    if mode != 0o700:
        return Check("job", "fail", f"the state directory is mode {mode:04o}, not 0700")
    started = time.monotonic()
    job = session.submit(SMOKE_KIND, _small_recipe())
    finished = session.work_once()
    if finished is None or finished.job_id != job.job_id or finished.status != "succeeded":
        status = "nothing was claimed" if finished is None else finished.status
        reason = "" if finished is None else f" ({finished.error_code})"
        return Check("job", "fail", f"the {SMOKE_KIND} job did not succeed: {status}{reason}")
    result = session.result(job.job_id)
    session.audit_head()
    seconds = time.monotonic() - started
    return Check(
        "job",
        "ok",
        f"a real {SMOKE_KIND} job ran in an isolated process in {seconds:.1f}s; its result was "
        f"verified on read (verdict: {result.verdict}) and the audit chain recomputed",
    )


def check_findings() -> Check:
    document = findings.load()
    if not document.available:
        return Check(
            "findings", "skip", "docs/RESULTS_AND_LIMITATIONS.md is not next to the package"
        )
    numbers = [finding.number for finding in document.findings]
    if numbers != list(range(1, len(numbers) + 1)):
        return Check("findings", "fail", f"the findings are not numbered 1..N: {numbers}")
    return Check(
        "findings",
        "ok",
        f"{len(numbers)} findings; the document's gate decision is "
        f"{document.gate_decision or 'absent'}",
    )


def check_health() -> Check:
    report = health.collect_health()
    if report.gate.decision != "NO-GO":
        return Check("gate", "fail", f"the gate decision is {report.gate.decision}, not NO-GO")
    if not report.ok:
        failing = ", ".join(c.name for c in report.checks if c.status == "fail")
        return Check("health", "fail", f"preflight checks failed: {failing}")
    return Check(
        "health",
        "ok",
        f"gate {report.gate.gate} decision {report.gate.decision}; {len(report.data_files)} data "
        f"files verified; {report.warnings} warning(s)",
    )


def check_qt() -> Check:
    if importlib.util.find_spec("PySide6") is None:
        return Check("qt", "skip", "PySide6 is not installed (`uv sync --extra desktop`)")
    try:
        version = metadata.version("PySide6-Essentials")
    except metadata.PackageNotFoundError:
        version = "unknown version"
    return Check("qt", "ok", f"PySide6 {version} is installed")


def check_display() -> Check:
    kind = displaycheck.effective_platform()
    if kind in ("none", "offscreen"):
        return Check("display", "skip", f"no graphical session to open a window on ({kind})")
    problems = displaycheck.check_display()
    if problems:
        return Check("display", "fail", displaycheck.report(problems).replace("\n  ", " -- "))
    return Check(
        "display", "ok", f"a {kind} session, and the libraries Qt needs for it are present"
    )


def check_launcher() -> Check:
    entry = launcher.desktop_entry()
    if "Exec=" not in entry or launcher.MARKER not in entry:
        return Check("launcher", "fail", "the desktop entry is malformed")
    return Check("launcher", "ok", "the application-menu entry can be generated")


def run_checks() -> list[Check]:
    """Run every step; a step that raises is reported as a failure, not a crash."""
    with tempfile.TemporaryDirectory(prefix="econosim-check-") as directory:
        root = Path(directory)
        steps: list[tuple[str, Callable[[], Check]]] = [
            ("forms", check_forms),
            ("explorers", check_explorers),
            ("job", lambda: check_job(root)),
            ("findings", check_findings),
            ("health", check_health),
            ("qt", check_qt),
            ("display", check_display),
            ("launcher", check_launcher),
        ]
        results: list[Check] = []
        for name, step in steps:
            try:
                results.append(step())
            except Exception as exc:  # a broken step must not hide the others
                results.append(Check(name, "fail", f"{type(exc).__name__}: {exc}"))
        return results
