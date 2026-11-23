"""PR-205: knowing, before Qt is asked, that a window cannot open.

Found on a real desktop: Qt 6.5+ aborts the whole process (a core dump, nothing to catch) when the
system library `libxcb-cursor` is missing, and from an application-menu entry nobody would see why.
These tests pin the check that replaces that with one clear message.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from prometheus.desktop import __main__ as entry
from prometheus.desktop import displaycheck, selfcheck
from prometheus.desktop.displaycheck import (
    NO_SESSION_REMEDY,
    XCB_REMEDY,
    check_display,
    effective_platform,
    notify,
    report,
)

X11 = {"DISPLAY": ":0", "XDG_SESSION_TYPE": "x11"}
WAYLAND = {"WAYLAND_DISPLAY": "wayland-0", "XDG_SESSION_TYPE": "wayland"}


def have(*names: str) -> Any:
    return lambda name: f"lib{name}.so.1" if name in names else None


# ------------------------------------------------------------------ which platform would Qt use


@pytest.mark.parametrize(
    ("environ", "platform"),
    [
        ({}, "none"),
        (X11, "xcb"),
        (WAYLAND, "wayland"),
        (
            {"DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0", "XDG_SESSION_TYPE": "wayland"},
            "wayland",
        ),
        ({"DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0", "XDG_SESSION_TYPE": "x11"}, "xcb"),
        ({"WAYLAND_DISPLAY": "wayland-0"}, "wayland"),
        ({"QT_QPA_PLATFORM": "offscreen", "DISPLAY": ":0"}, "offscreen"),
        ({"QT_QPA_PLATFORM": "xcb:xcb_xinput=0"}, "xcb"),
        ({"QT_QPA_PLATFORM": " "}, "none"),
    ],
)
def test_the_platform_is_read_the_way_qt_would_choose_it(
    environ: dict[str, str], platform: str
) -> None:
    assert effective_platform(environ) == platform


# ------------------------------------------------------------------ what is wrong, and the fix


def test_a_missing_xcb_cursor_library_is_named_with_the_package_to_install() -> None:
    problems = check_display(X11, platform="linux", find_library=have("xcb"))
    assert len(problems) == 1
    assert "libxcb-cursor" in problems[0].summary and problems[0].remedy == XCB_REMEDY
    for package in ("libxcb-cursor0", "xcb-util-cursor"):
        assert package in XCB_REMEDY
    assert "sudo apt install libxcb-cursor0" in report(problems)


def test_a_library_supplied_through_ld_library_path_counts(tmp_path: Path) -> None:
    """The no-administrator way to supply it: unpack the package into a folder and point the
    loader there. The system lookup cannot see that, the loader (and so Qt) can."""
    (tmp_path / "libxcb-cursor.so.0").write_bytes(b"")
    with_path = {**X11, "LD_LIBRARY_PATH": f"/nonexistent:{tmp_path}"}
    assert check_display(with_path, platform="linux", find_library=have("xcb")) == []
    elsewhere = {**X11, "LD_LIBRARY_PATH": "/nonexistent"}
    assert len(check_display(elsewhere, platform="linux", find_library=have("xcb"))) == 1
    assert len(check_display(X11, platform="linux", find_library=have("xcb"))) == 1


def test_nothing_is_reported_when_the_library_is_there() -> None:
    assert check_display(X11, platform="linux", find_library=have("xcb-cursor")) == []


@pytest.mark.parametrize("environ", [WAYLAND, {"QT_QPA_PLATFORM": "offscreen"}])
def test_platforms_that_do_not_need_it_are_not_checked_for_it(environ: dict[str, str]) -> None:
    assert check_display(environ, platform="linux", find_library=have()) == []


def test_no_graphical_session_is_its_own_problem_with_the_headless_alternatives() -> None:
    [problem] = check_display({}, platform="linux", find_library=have("xcb-cursor"))
    assert "No graphical session" in problem.summary and problem.remedy == NO_SESSION_REMEDY
    assert "--check" in problem.remedy and "--screenshots" in problem.remedy


def test_only_linux_is_checked() -> None:
    assert check_display({}, platform="darwin", find_library=have()) == []
    assert check_display(X11, platform="win32", find_library=have()) == []


def test_the_library_lookup_happens_when_asked_not_when_the_module_was_imported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(displaycheck.ctypes.util, "find_library", lambda name: None)
    assert len(check_display(X11, platform="linux")) == 1
    monkeypatch.setattr(displaycheck.ctypes.util, "find_library", lambda name: "libxcb-cursor.so.0")
    assert check_display(X11, platform="linux") == []


# ------------------------------------------------------------------ telling the person


def test_a_notification_is_sent_when_a_notifier_exists_and_never_fails_the_program(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **kwargs: Any) -> Any:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(displaycheck.subprocess, "run", fake_run)
    assert notify("install libxcb-cursor0", which=lambda name: "/usr/bin/notify-send") is True
    assert calls[0][0] == "/usr/bin/notify-send" and calls[0][-1] == "install libxcb-cursor0"
    assert notify("x", which=lambda name: None) is False and len(calls) == 1

    def boom(argv: list[str], **kwargs: Any) -> Any:
        raise subprocess.TimeoutExpired(argv, 5)

    monkeypatch.setattr(displaycheck.subprocess, "run", boom)
    assert notify("x", which=lambda name: "/usr/bin/notify-send") is False

    def missing(argv: list[str], **kwargs: Any) -> Any:
        raise FileNotFoundError

    monkeypatch.setattr(displaycheck.subprocess, "run", missing)
    assert notify("x", which=lambda name: "/gone") is False


def test_the_message_travels_as_one_argument_never_through_a_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def fake_run(argv: list[str], **kwargs: Any) -> Any:
        seen.update(argv=argv, kwargs=kwargs)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(displaycheck.subprocess, "run", fake_run)
    hostile = "$(touch /tmp/pwned); `id` \n --flag"
    notify(hostile, which=lambda name: "/usr/bin/notify-send")
    assert seen["argv"][-1] == hostile and "shell" not in seen["kwargs"]


# ------------------------------------------------------------------ the command and the self-test


@pytest.fixture
def broken_x11(monkeypatch: pytest.MonkeyPatch) -> None:
    """An X11 session on a machine without libxcb-cursor, however this machine really is."""
    monkeypatch.setattr(entry.importlib.util, "find_spec", lambda name: object())
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.setattr(displaycheck.ctypes.util, "find_library", lambda name: None)
    monkeypatch.setattr(displaycheck, "notify", lambda message: True)


def test_the_window_refuses_to_start_and_says_what_to_install(
    tmp_path: Path, broken_x11: None, capsys: pytest.CaptureFixture[str]
) -> None:
    state = tmp_path / "state"
    assert entry.main(["--state-dir", str(state)]) == 1
    error = capsys.readouterr().err
    assert "the window cannot open here" in error and "sudo apt install libxcb-cursor0" in error
    assert "Traceback" not in error
    note = state / entry.STARTUP_ERROR_FILE
    assert "libxcb-cursor" in note.read_text() and oct(note.stat().st_mode)[-3:] == "600"


def test_the_desktop_notification_is_tried_for_a_launch_without_a_terminal(
    tmp_path: Path, broken_x11: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[str] = []
    monkeypatch.setattr(displaycheck, "notify", lambda message: sent.append(message) or True)
    assert entry.main(["--state-dir", str(tmp_path / "state")]) == 1
    assert len(sent) == 1 and "libxcb-cursor" in sent[0]


def test_installing_the_launcher_warns_that_the_entry_will_not_open_a_window_yet(
    tmp_path: Path,
    broken_x11: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    assert entry.main(["--install-launcher"]) == 0, "it still installs: that part works"
    captured = capsys.readouterr()
    assert "installed" in captured.out
    assert "will not open a window yet" in captured.err and "libxcb-cursor" in captured.err


def test_the_self_test_fails_a_desktop_that_cannot_open_a_window(
    broken_x11: None,
) -> None:
    check = selfcheck.check_display()
    assert (
        check.status == "fail" and "libxcb-cursor" in check.detail and "apt install" in check.detail
    )


def test_the_self_test_skips_the_display_where_there_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("DISPLAY", "WAYLAND_DISPLAY", "QT_QPA_PLATFORM"):
        monkeypatch.delenv(name, raising=False)
    assert selfcheck.check_display().status == "skip"
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    assert selfcheck.check_display().status == "skip"


def test_the_self_test_passes_a_desktop_that_has_what_qt_needs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(displaycheck.ctypes.util, "find_library", lambda name: "libxcb-cursor.so.0")
    check = selfcheck.check_display()
    assert check.status == "ok" and "xcb" in check.detail
