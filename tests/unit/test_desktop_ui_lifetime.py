# ruff: noqa: E402
"""PR-205: widgets are freed when their last reference goes; the window is taken down on purpose.

Why this file exists. On CI the whole test run printed `QObject: shared QObject was deleted
directly`, then `corrupted double-linked list`, and aborted with exit status 134 -- after the last
test had already passed. The cause was `button.clicked.connect(lambda ...: self....)`. PySide keeps
the lambda in the C++ connection, where Python's garbage collector cannot see it, so
widget -> button -> connection -> lambda -> widget was a cycle that nothing freed until the
interpreter exited, and then Qt and Python each tried to delete the other's objects. It did not
always crash (it depends on how the heap happens to be laid out), which is why it had been written
off as a cosmetic message on the developer's machine.

So there are two kinds of test here: the rule itself (no signal is connected to a closure, checked
on the source), and its consequence (a widget that is let go of is actually freed, checked on real
widgets, the whole window included).
"""

from __future__ import annotations

import ast
import gc
import subprocess
import sys
import textwrap
import threading
import weakref
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tests.unit import desktop_ui_support as support

UI_SOURCE = Path(__file__).resolve().parents[2] / "src" / "prometheus" / "desktop" / "ui"

# ------------------------------------------------------------------ the rule


def _call_name(node: ast.expr) -> str:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def closure_connections(source: str, name: str) -> list[str]:
    """Where `source` hands a lambda, or a `partial`, to something called `connect`."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and _call_name(node.func) == "connect"):
            continue
        for argument in [*node.args, *(keyword.value for keyword in node.keywords)]:
            is_closure = isinstance(argument, ast.Lambda) or (
                isinstance(argument, ast.Call) and _call_name(argument.func) == "partial"
            )
            if is_closure:
                found.append(f"{name}:{node.lineno}")
    return found


def test_the_rule_recognises_the_patterns_it_forbids() -> None:
    bad = textwrap.dedent(
        """
        button.clicked.connect(lambda: self.go())
        button.clicked.connect(lambda _=False, k=key: self.go(k))
        button.clicked.connect(partial(self.go, key))
        button.clicked.connect(functools.partial(self.go, key))
        button.clicked.connect(slot=lambda: 1)
        connect(lambda: 1)
        """
    )
    assert len(closure_connections(bad, "x.py")) == 6
    fine = textwrap.dedent(
        """
        button.clicked.connect(self._go)
        button.clicked.connect(self.rerunRequested)
        timer.timeout.connect(self._tick)
        pump(app, lambda: False)
        sorted(rows, key=lambda row: row[1])
        """
    )
    assert closure_connections(fine, "x.py") == []


def test_no_signal_in_the_window_is_connected_to_a_closure() -> None:
    offenders: list[str] = []
    files = sorted(UI_SOURCE.rglob("*.py"))
    assert len(files) >= 15, "the scan found the window's source"
    for path in files:
        offenders += closure_connections(path.read_text(), str(path.relative_to(UI_SOURCE)))
    assert offenders == [], (
        "connect to a bound method and read `self.sender()` instead: "
        "see the note in prometheus/desktop/ui/__init__.py"
    )


# ------------------------------------------------------------------ the consequence

support.require_qt()

from prometheus.desktop import forms
from prometheus.desktop.results import analyze_payload
from prometheus.desktop.runner import WorkerLoop
from prometheus.desktop.session import LocalSession
from prometheus.desktop.ui import app as app_module
from prometheus.desktop.ui import theme
from prometheus.desktop.ui.main_window import PAGES, MainWindow
from prometheus.desktop.ui.resultview import ResultWidget


def is_freed(reference: Any) -> bool:
    gc.collect()
    support.settle(0.0)
    return bool(reference() is None)


def rich_view() -> Any:
    """A result with every kind of content: a comparison, charts, two tables, notes."""
    return analyze_payload(
        {
            "verdict": "classical_better",
            "models": {"a": {"mae": 1.0, "rmse": 2.0}, "b": {"mae": 3.0, "rmse": 4.0}},
            "curve": [3.0, 2.0, 1.0, 0.5],
            "steps": [{"step": i, "v": float(i)} for i in range(6)],
            "trades": [{"asset": "A", "qty": 2.0}, {"asset": "B", "qty": 3.0}],
            "limitations": ["synthetic data"],
        },
        kind="x",
        title="Rich",
        provenance=[("Result hash", "ab" * 32)],
        disclaimer="SIMULATED DATA -- RESEARCH ONLY.",
    )


def test_a_result_with_tables_is_freed_when_its_last_reference_goes(qapp: Any) -> None:
    widget = ResultWidget()
    widget.set_view(rich_view())
    assert len(widget.tables) == 2, "the case that corrupted the heap: tables with export buttons"
    reference = weakref.ref(widget)
    del widget
    assert is_freed(reference)


def test_a_result_that_was_replaced_and_cleared_is_freed_too(qapp: Any) -> None:
    widget = ResultWidget()
    for _ in range(3):
        widget.set_view(rich_view())
    widget.clear()
    reference = weakref.ref(widget)
    del widget
    assert is_freed(reference)


@pytest.fixture
def build_window(qapp: Any, tmp_path: Path) -> Callable[[], tuple[MainWindow, Path, WorkerLoop]]:
    """A factory for a window built the way `run` builds it. It is a factory, not the window, on
    purpose: pytest keeps what a fixture returns alive until the test ends, which would hold the
    very reference these tests are checking is released."""
    theme.apply_theme(qapp, "dark")
    forms.warm_up()

    def build() -> tuple[MainWindow, Path, WorkerLoop]:
        state = tmp_path / "state"
        session = LocalSession(state)
        runner = WorkerLoop(session, idle_seconds=0.05)
        runner.start()
        window = MainWindow(
            session, state_dir=state, runner=runner, theme_mode="dark", confirm_close=False
        )
        window.resize(1320, 860)
        window.show()
        support.settle()
        for key, _ in PAGES:  # every page built, the lazy ones included
            window.show_page(key)
            support.settle(0.05)
        return window, state, runner

    return build


def test_the_whole_window_is_freed_once_the_application_has_taken_it_down(
    build_window: Callable[[], tuple[MainWindow, Path, WorkerLoop]],
) -> None:
    window, _, _ = build_window()
    reference = weakref.ref(window)
    app_module.dispose(window)
    del window
    assert is_freed(reference), "something still holds the window: a closure in a connection?"


def test_a_window_nobody_disposes_is_still_freed_by_the_garbage_collector_alone(
    build_window: Callable[[], tuple[MainWindow, Path, WorkerLoop]],
) -> None:
    """The stronger form of the rule: with no explicit delete at all, letting go is enough. A
    single closure over `self` anywhere in the window would make this fail."""
    window, _, _ = build_window()
    window.shutdown()
    reference = weakref.ref(window)
    del window
    assert is_freed(reference)


def test_the_error_log_hooks_come_off_again_exactly_as_they_were_found(
    build_window: Callable[[], tuple[MainWindow, Path, WorkerLoop]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window, state, _ = build_window()
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    before = (sys.excepthook, threading.excepthook)
    uninstall = app_module.install_error_log(state, window.errorLogged.emit)
    assert (sys.excepthook, threading.excepthook) != before, "installed"
    uninstall()
    assert (sys.excepthook, threading.excepthook) == before, "put back exactly as found"
    uninstall()  # twice is harmless
    assert (sys.excepthook, threading.excepthook) == before
    app_module.dispose(window)


def test_uninstalling_leaves_alone_a_hook_someone_else_put_on_top(
    build_window: Callable[[], tuple[MainWindow, Path, WorkerLoop]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window, state, _ = build_window()
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    uninstall = app_module.install_error_log(state, None)

    def theirs(kind: Any, value: Any, trace: Any) -> None:
        return None

    sys.excepthook = theirs
    uninstall()
    assert sys.excepthook is theirs, "not ours to remove"
    app_module.dispose(window)


def test_disposing_stops_the_worker_and_is_safe_to_repeat(
    build_window: Callable[[], tuple[MainWindow, Path, WorkerLoop]],
) -> None:
    window, _, runner = build_window()
    app_module.dispose(window)
    app_module.dispose(window)  # a second call must not raise on the already deleted window
    assert not runner.alive


# ------------------------------------------------------------------ the end: a process that exits


@pytest.mark.skipif(sys.platform != "linux", reason="the offscreen run is checked on Linux")
def test_the_application_exits_cleanly_after_the_window_closes(tmp_path: Path) -> None:
    """`run` end to end in a real process: every page built, the event loop run and ended, then
    the interpreter exits. The exit status and stderr are what the CI run was failing on."""
    script = textwrap.dedent(
        """
        import os, sys
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from pathlib import Path
        from PySide6.QtCore import QTimer
        from prometheus.desktop import forms
        from prometheus.desktop.ui import app as ui

        forms.warm_up = lambda: None  # the real one imports torch in a thread; not what is tested
        application = ui.create_application()
        QTimer.singleShot(1200, application.quit)
        raise SystemExit(ui.run(Path(sys.argv[1]), theme="dark"))
        """
    )
    process = subprocess.run(  # noqa: S603 -- our own interpreter and our own script
        [sys.executable, "-c", script, str(tmp_path / "state")],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert process.returncode == 0, process.stderr[-1500:]
    assert "shared QObject" not in process.stderr and "corrupted" not in process.stderr
