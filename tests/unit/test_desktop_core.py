"""PR-205: the health report, the findings page's source, the application-menu launcher, the
self-test and the command line -- everything of the desktop application that needs no window."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import types
import xml.etree.ElementTree as ET  # noqa: S405 - parsing this module's own constant icon
from pathlib import Path
from typing import Any

import pytest

from prometheus import cli
from prometheus.data_ingestion.snapshot_integrity import (
    COMMITTED_DATA_DIR,
    MANIFEST_FILENAME,
    compute_manifest,
    load_manifest,
)
from prometheus.desktop import __main__ as entry
from prometheus.desktop import findings, health, launcher, selfcheck
from prometheus.desktop.findings import FindingsDocument, parse
from prometheus.desktop.launcher import (
    ICON_SVG,
    LauncherError,
    desktop_entry,
    install_launcher,
    quote_exec_argument,
    uninstall_launcher,
)
from prometheus.desktop.paths import InstanceLock
from prometheus.doctor import Check
from prometheus.evidence.repository_status import current_repository_gate_report

# ------------------------------------------------------------------ health


def test_the_gate_summary_is_the_codes_own_decision() -> None:
    summary = health.gate_summary()
    form = current_repository_gate_report()
    assert summary.decision == form.decision == "NO-GO"
    assert summary.gate == form.gate and summary.decided_at == form.decided_at.isoformat()
    assert any("Live trading" in item for item in summary.scope_prohibited)
    assert summary.open_findings, "the open findings are shown, not hidden"


def test_every_committed_data_file_is_listed_and_verified() -> None:
    rows = health.data_files()
    assert {row.name for row in rows} == set(load_manifest(COMMITTED_DATA_DIR))
    assert {row.name for row in rows} == set(compute_manifest(COMMITTED_DATA_DIR)), (
        "the table covers exactly what is on disk: nothing hidden, nothing invented"
    )
    assert {row.status for row in rows} == {"ok"}
    assert all(row.size > 0 and len(row.sha256) == 64 for row in rows)
    assert [row.name for row in rows] == sorted(row.name for row in rows)


def _copy_data(tmp_path: Path) -> Path:
    target = tmp_path / "data_cache"
    shutil.copytree(COMMITTED_DATA_DIR, target)
    return target


def test_a_modified_missing_and_unlisted_file_are_each_reported(tmp_path: Path) -> None:
    data = _copy_data(tmp_path)
    names = sorted(p.name for p in data.iterdir() if p.name != MANIFEST_FILENAME)
    (data / names[0]).write_bytes((data / names[0]).read_bytes() + b"x")
    (data / names[1]).unlink()
    (data / "extra.csv").write_text("a,b\n")
    status = {row.name: row.status for row in health.data_files(data)}
    assert status[names[0]] == "modified"
    assert status[names[1]] == "missing"
    assert status["extra.csv"] == "unlisted"
    assert status[names[2]] == "ok"
    report = health.collect_health(data_dir=data)
    assert report.failures == 0, "the environment checks look at the committed data, not this copy"


def test_an_unreadable_manifest_yields_no_rows_not_a_crash(tmp_path: Path) -> None:
    data = _copy_data(tmp_path)
    (data / MANIFEST_FILENAME).write_text("{not json")
    assert health.data_files(data) == ()
    assert health.data_files(tmp_path / "absent") == ()


def test_the_health_report_gathers_the_environment() -> None:
    report = health.collect_health()
    facts = dict(report.environment)
    assert facts["Python"].count(".") == 2 and facts["Application"] == health.app_version()
    assert facts["numpy"] != "not installed"
    assert (
        facts["PySide6-Essentials"] == "not installed" or facts["PySide6-Essentials"][0].isdigit()
    )
    assert report.disclaimer.startswith("SIMULATED DATA -- RESEARCH ONLY")
    assert {c.name for c in report.checks} >= {"python", "data_integrity", "state_directory"}
    assert report.ok and report.failures == 0


def test_a_failed_check_makes_the_report_not_ok() -> None:
    report = health.collect_health()
    broken = health.HealthReport(
        report.app_version,
        report.disclaimer,
        report.gate,
        (*report.checks, Check("x", "fail", "boom"), Check("y", "warn", "hm")),
        report.data_files,
        report.environment,
    )
    assert not broken.ok and broken.failures == 1 and broken.warnings == report.warnings + 1


def test_a_missing_frontend_build_is_not_a_warning_of_the_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Found by the first CI run: a machine that never ran `npm run build` showed "1 warning" on
    the overview of a program that does not use the web frontend at all."""
    from prometheus import doctor

    missing = Check("frontend_build", "warn", "frontend/dist is missing")
    monkeypatch.setattr(doctor, "check_frontend_build", lambda *args, **kwargs: missing)
    assert missing in doctor.run_checks(), "doctor itself still reports it, for the web stack"
    report = health.collect_health()
    assert "frontend_build" not in {c.name for c in report.checks}
    assert report.warnings == 0 and report.ok


def test_the_state_directory_is_checked_when_one_is_given(tmp_path: Path) -> None:
    ok = health.collect_health(state_dir=tmp_path)
    assert next(c for c in ok.checks if c.name == "state_directory").status == "ok"
    bad = health.collect_health(state_dir=tmp_path / "absent")
    assert not bad.ok


# ------------------------------------------------------------------ findings


def test_the_real_document_yields_every_finding_in_order() -> None:
    document = findings.load()
    assert document.available
    numbers = [f.number for f in document.findings]
    assert numbers == list(range(1, len(numbers) + 1)) and len(numbers) >= 18
    for finding in document.findings:
        assert finding.title and finding.pr.startswith("PR-") and finding.markdown
        assert finding.summary and "\n" not in finding.summary
    assert document.get(6).pr == "PR-153, revised PR-177"
    assert document.limitations_markdown.startswith("- ")
    with pytest.raises(KeyError):
        document.get(9999)


def test_the_documents_gate_decision_is_the_codes_gate_decision() -> None:
    """The prose says NO-GO and so does the code that generates every artifact's gate report;
    this is the check that they cannot quietly disagree."""
    assert findings.load().gate_decision == str(current_repository_gate_report().decision)


SAMPLE = """\
# Title

intro text

## The overall gate decision: NO-GO

Nothing here is a trading system.

## Finding 2 (PR-20): the second one

Second **summary** sentence. More.

```
## Finding 9 (PR-1): a fake heading inside a code fence
```

still the second finding

## Finding 1 (PR-10, revised PR-11): the first one

| a | b |
|---|---|

The table above is skipped for the summary; this paragraph is not.

~~~
## Another fake
~~~

## Appendix: unrelated

must not leak into any finding

## Known limitations that are not findings

- one
- two
"""


def test_the_parser_splits_sections_and_ignores_headings_inside_code_fences() -> None:
    document = parse(SAMPLE)
    assert [f.number for f in document.findings] == [1, 2], "sorted, and the fenced ones ignored"
    second = document.get(2)
    assert "a fake heading inside a code fence" in second.markdown
    assert "still the second finding" in second.markdown
    assert second.summary == "Second summary sentence. More."
    first = document.get(1)
    assert first.pr == "PR-10, revised PR-11" and first.title == "the first one"
    assert first.summary.startswith("The table above is skipped")
    assert "Another fake" in first.markdown and "must not leak" not in first.markdown
    assert document.gate_decision == "NO-GO" and "trading system" in document.gate_markdown
    assert document.limitations_markdown == "- one\n- two"


@pytest.mark.parametrize(
    "text",
    ["", "no headings at all", "## Finding x (PR-1): not a number\nbody", "## Finding 1 PR-1: x"],
)
def test_text_without_findings_is_not_available(text: str) -> None:
    document = parse(text)
    assert not document.available and document.findings == ()


def test_a_missing_or_unreadable_document_is_reported_as_unavailable(tmp_path: Path) -> None:
    assert not findings.load(tmp_path / "absent.md").available
    assert not findings.load(tmp_path).available, "a directory is not a document"
    broken = tmp_path / "broken.md"
    broken.write_bytes(b"\xff\xfe\x00## Finding 1 (PR-1): x")
    assert not findings.load(broken).available
    assert isinstance(findings.load(tmp_path / "absent.md"), FindingsDocument)


# ------------------------------------------------------------------ the launcher


def test_the_desktop_entry_has_the_fields_a_menu_needs() -> None:
    text = desktop_entry("/opt/env/bin/python")
    lines = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    assert text.startswith("[Desktop Entry]\n")
    assert lines["Type"] == "Application" and lines["Name"] == "ECONOSIM"
    assert lines["Exec"] == '"/opt/env/bin/python" -m prometheus.desktop'
    assert lines["Icon"] == "econosim" and lines["Terminal"] == "false"
    assert lines["Categories"].endswith(";") and "Education" in lines["Categories"]
    assert "not financial advice" in lines["Comment"]
    assert lines["X-Econosim-Launcher"] == "1" and lines["StartupWMClass"] == "econosim"


@pytest.mark.parametrize(
    ("argument", "quoted"),
    [
        ("/usr/bin/python3", '"/usr/bin/python3"'),
        ("/home/a b/env/python", '"/home/a b/env/python"'),
        ('/x/"quoted"/py', '"/x/\\"quoted\\"/py"'),
        ("/x/$HOME/py", '"/x/\\$HOME/py"'),
        ("/x/`id`/py", '"/x/\\`id\\`/py"'),
        ("/x/back\\slash", '"/x/back\\\\slash"'),
        ("/x/100%/py", '"/x/100%%/py"'),
    ],
)
def test_exec_arguments_are_quoted_as_the_specification_requires(
    argument: str, quoted: str
) -> None:
    assert quote_exec_argument(argument) == quoted


@pytest.mark.skipif(
    shutil.which("desktop-file-validate") is None, reason="desktop-file-utils absent"
)
@pytest.mark.parametrize(
    "interpreter",
    ["/usr/bin/python3", "/home/a b/env/bin/python", "/home/it's/$HOME/`x`/100%/py"],
)
def test_the_real_validator_accepts_the_entry(tmp_path: Path, interpreter: str) -> None:
    path = tmp_path / "econosim.desktop"
    path.write_text(desktop_entry(interpreter))
    done = subprocess.run(  # noqa: S603 - fixed argv; validates a file this test just wrote
        ["desktop-file-validate", str(path)], capture_output=True, text=True
    )
    assert done.returncode == 0, done.stdout + done.stderr


def test_the_icon_is_a_small_self_contained_svg() -> None:
    root = ET.fromstring(ICON_SVG)  # noqa: S314 - our own constant, not input
    assert root.tag == "{http://www.w3.org/2000/svg}svg" and root.get("viewBox") == "0 0 256 256"
    assert root.get("aria-label") == "ECONOSIM"
    lowered = ICON_SVG.lower()
    assert "<script" not in lowered and "http://" not in lowered.replace(
        "http://www.w3.org/2000/svg", ""
    )
    assert "href" not in lowered, "no external or internal references to load"


def test_installing_writes_the_entry_and_the_icon_under_the_data_home(tmp_path: Path) -> None:
    entry_path, icon_path = install_launcher(tmp_path, python="/opt/py")
    assert entry_path == tmp_path / "applications" / "econosim.desktop"
    assert icon_path == tmp_path / "icons" / "hicolor" / "scalable" / "apps" / "econosim.svg"
    assert stat.S_IMODE(entry_path.stat().st_mode) == 0o644
    assert '"/opt/py" -m prometheus.desktop' in entry_path.read_text()
    assert icon_path.read_text() == ICON_SVG
    assert sorted(p.name for p in entry_path.parent.iterdir()) == ["econosim.desktop"], (
        "no temp files"
    )


def test_reinstalling_updates_our_own_files(tmp_path: Path) -> None:
    install_launcher(tmp_path, python="/old/python")
    entry_path, _ = install_launcher(tmp_path, python="/new/python")
    text = entry_path.read_text()
    assert "/new/python" in text and "/old/python" not in text


def test_a_file_that_is_not_ours_is_never_overwritten(tmp_path: Path) -> None:
    entry_path = tmp_path / "applications" / "econosim.desktop"
    entry_path.parent.mkdir(parents=True)
    entry_path.write_text("[Desktop Entry]\nName=Someone else's app\n")
    with pytest.raises(LauncherError, match="not created by ECONOSIM"):
        install_launcher(tmp_path)
    assert "Someone else" in entry_path.read_text()
    assert not (tmp_path / "icons").exists(), "nothing was half-installed"


def test_a_foreign_icon_is_never_overwritten_either(tmp_path: Path) -> None:
    icon = tmp_path / "icons" / "hicolor" / "scalable" / "apps" / "econosim.svg"
    icon.parent.mkdir(parents=True)
    icon.write_text("<svg>mine</svg>")
    with pytest.raises(LauncherError, match="not created by ECONOSIM"):
        install_launcher(tmp_path)
    assert icon.read_text() == "<svg>mine</svg>"


def test_a_symlink_is_not_followed(tmp_path: Path) -> None:
    victim = tmp_path / "victim.txt"
    victim.write_text("precious")
    entry_path = tmp_path / "applications" / "econosim.desktop"
    entry_path.parent.mkdir(parents=True)
    entry_path.symlink_to(victim)
    with pytest.raises(LauncherError, match="symlink"):
        install_launcher(tmp_path)
    assert victim.read_text() == "precious"
    assert uninstall_launcher(tmp_path) == [], "and it is not removed through the link either"
    assert victim.exists() and entry_path.is_symlink()


def test_uninstalling_removes_only_what_installing_wrote(tmp_path: Path) -> None:
    assert uninstall_launcher(tmp_path) == []
    entry_path, icon_path = install_launcher(tmp_path)
    assert sorted(uninstall_launcher(tmp_path)) == sorted([entry_path, icon_path])
    assert not entry_path.exists() and not icon_path.exists()
    foreign = tmp_path / "applications" / "econosim.desktop"
    foreign.write_text("[Desktop Entry]\nName=not ours\n")
    assert uninstall_launcher(tmp_path) == [] and foreign.exists()


def test_a_failed_write_leaves_neither_a_temp_file_nor_a_changed_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry_path, _ = install_launcher(tmp_path, python="/orig/python")

    def refuse(*_: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(launcher.os, "replace", refuse)
    with pytest.raises(OSError, match="disk full"):
        install_launcher(tmp_path, python="/new/python")
    assert "/orig/python" in entry_path.read_text()
    assert sorted(p.name for p in entry_path.parent.iterdir()) == ["econosim.desktop"]


def test_the_data_home_follows_the_xdg_variable(tmp_path: Path) -> None:
    assert launcher.default_data_home({"XDG_DATA_HOME": str(tmp_path)}) == tmp_path
    assert launcher.default_data_home({"XDG_DATA_HOME": "rel"}, home=tmp_path) == (
        tmp_path / ".local" / "share"
    )
    assert launcher.default_data_home({}, home=tmp_path) == tmp_path / ".local" / "share"


# ------------------------------------------------------------------ the self-test's steps


def test_the_qt_step_reports_what_is_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(selfcheck.importlib.util, "find_spec", lambda name: None)
    assert selfcheck.check_qt().status == "skip"
    monkeypatch.setattr(selfcheck.importlib.util, "find_spec", lambda name: object())
    assert selfcheck.check_qt().status == "ok"


def test_the_findings_step_fails_on_a_gap_and_skips_when_the_document_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(selfcheck.findings, "load", lambda: parse(""))
    assert selfcheck.check_findings().status == "skip"
    gappy = "## Finding 1 (PR-1): a\nx\n\n## Finding 3 (PR-3): c\ny\n"
    monkeypatch.setattr(selfcheck.findings, "load", lambda: parse(gappy))
    check = selfcheck.check_findings()
    assert check.status == "fail" and "[1, 3]" in check.detail


def test_the_health_step_fails_if_the_gate_ever_stops_saying_no_go(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = health.collect_health()
    fake_gate = health.GateSummary("R0", "GO", "2026-01-01", ("x",), ())
    altered = health.HealthReport(
        real.app_version, real.disclaimer, fake_gate, real.checks, real.data_files, real.environment
    )
    monkeypatch.setattr(selfcheck.health, "collect_health", lambda: altered)
    check = selfcheck.check_health()
    assert check.status == "fail" and "not NO-GO" in check.detail


def test_the_job_step_skips_where_the_worker_cannot_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from prometheus.desktop import session as session_module

    monkeypatch.setattr(session_module, "sys", types.SimpleNamespace(platform="darwin"))
    check = selfcheck.check_job(tmp_path)
    assert check.status == "skip" and "Linux" in check.detail


def test_a_step_that_raises_is_reported_and_the_others_still_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode() -> Check:
        raise RuntimeError("kaboom")

    monkeypatch.setattr(selfcheck, "check_forms", explode)
    monkeypatch.setattr(selfcheck, "check_explorers", lambda: Check("explorers", "ok", "stub"))
    monkeypatch.setattr(selfcheck, "check_job", lambda root: Check("job", "ok", "stub"))
    results = selfcheck.run_checks()
    names = [c.name for c in results]
    assert names == ["forms", "explorers", "job", "findings", "health", "qt", "display", "launcher"]
    assert results[0].status == "fail" and "RuntimeError: kaboom" in results[0].detail
    assert all(c.status != "fail" for c in results[1:])


# ------------------------------------------------------------------ the command line


def test_the_whole_self_test_passes_on_this_checkout(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # whether a *window* could open is a fact about the machine's screen, not about this checkout
    # (it is tested in test_desktop_display.py); here the run is headless on every machine
    for name in ("DISPLAY", "WAYLAND_DISPLAY"):
        monkeypatch.delenv(name, raising=False)
    assert entry.main(["--check"]) == 0
    output = capsys.readouterr().out
    assert "desktop check: all clear" in output
    for step in ("forms", "explorers", "job", "findings", "health", "qt", "display", "launcher"):
        assert f"] {step}:" in output
    assert "[fail]" not in output


def test_the_self_test_exits_non_zero_when_a_step_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        selfcheck, "run_checks", lambda: [Check("a", "ok", "fine"), Check("b", "fail", "broken")]
    )
    assert entry.main(["--check"]) == 1
    output = capsys.readouterr().out
    assert "[fail] b: broken" in output and "1 failed" in output


def test_installing_and_removing_the_launcher_from_the_command_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert entry.main(["--install-launcher"]) == 0
    assert "installed" in capsys.readouterr().out
    assert (tmp_path / "applications" / "econosim.desktop").is_file()
    assert entry.main(["--uninstall-launcher"]) == 0
    assert "removed" in capsys.readouterr().out
    assert entry.main(["--uninstall-launcher"]) == 0
    assert "nothing to remove" in capsys.readouterr().out


def test_a_foreign_launcher_file_makes_the_command_fail_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    target = tmp_path / "applications" / "econosim.desktop"
    target.parent.mkdir(parents=True)
    target.write_text("[Desktop Entry]\nName=other\n")
    assert entry.main(["--install-launcher"]) == 1
    assert "not created by ECONOSIM" in capsys.readouterr().err


def test_without_qt_the_window_says_how_to_get_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(entry.importlib.util, "find_spec", lambda name: None)
    assert entry.main([]) == 1
    error = capsys.readouterr().err
    assert "uv sync --extra desktop" in error and "prometheus-econ[desktop]" in error


@pytest.fixture
def qt_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """Qt is installed and the screen is fine -- whatever this machine really has (what a missing
    display library does is tested in test_desktop_display.py)."""
    monkeypatch.setattr(entry.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(entry.displaycheck, "check_display", lambda *args, **kwargs: [])


def test_an_open_state_directory_is_refused_before_any_window(
    tmp_path: Path, qt_present: None, capsys: pytest.CaptureFixture[str]
) -> None:
    loose = tmp_path / "loose"
    loose.mkdir()
    loose.chmod(0o755)
    assert entry.main(["--state-dir", str(loose)]) == 1
    assert "chmod 700" in capsys.readouterr().err


def test_a_second_window_on_the_same_state_is_refused(
    tmp_path: Path, qt_present: None, capsys: pytest.CaptureFixture[str]
) -> None:
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    with InstanceLock(state):
        assert entry.main(["--state-dir", str(state)]) == 1
    assert "already using" in capsys.readouterr().err


def test_the_window_is_opened_with_the_chosen_state_and_theme(
    tmp_path: Path, qt_present: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # the command sets QT_QPA_PLATFORM for the rest of the process; set-then-delete makes the
    # undo remove it again, so it cannot leak into the tests that run after this one
    monkeypatch.setenv("QT_QPA_PLATFORM", "placeholder")
    monkeypatch.delenv("QT_QPA_PLATFORM")
    calls: list[tuple[Any, ...]] = []
    stub = types.SimpleNamespace(
        run=lambda state, theme: calls.append(("run", state, theme)) or 0,
        screenshots=lambda out, theme: calls.append(("shots", out, theme)) or 0,
    )
    monkeypatch.setattr(entry, "_ui_app", lambda: stub)
    state = tmp_path / "state"
    assert entry.main(["--state-dir", str(state), "--theme", "dark"]) == 0
    assert stat.S_IMODE(state.stat().st_mode) == 0o700, "the state directory was created private"
    shots_state = tmp_path / "never-created"
    assert (
        entry.main(["--state-dir", str(shots_state), "--screenshots", str(tmp_path / "out")]) == 0
    )
    assert calls[0] == ("run", state.resolve(), "dark")
    assert calls[1] == ("shots", tmp_path / "out", "system")
    assert os.environ["QT_QPA_PLATFORM"] == "offscreen"
    assert not shots_state.exists(), "screenshots use a throwaway state directory, not the person's"


def test_the_actions_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit) as raised:
        entry.main(["--check", "--install-launcher"])
    assert raised.value.code == 2


def test_the_subcommand_is_reachable_from_the_econosim_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main(["desktop", "--help"])
    assert raised.value.code == 0
    help_text = capsys.readouterr().out
    assert "NO-GO" in help_text and "--check" in help_text and "--install-launcher" in help_text
    assert cli.main(["--help"]) == 0
    assert "desktop" in capsys.readouterr().out


def test_the_module_runs_as_a_script() -> None:
    done = subprocess.run(  # noqa: S603 - fixed argv, this interpreter
        [sys.executable, "-m", "prometheus.desktop", "--help"], capture_output=True, text=True
    )
    assert done.returncode == 0 and "--screenshots" in done.stdout
