"""Start the application: create Qt's application object, the session, the worker thread, the
window -- and, headlessly, render every page to a PNG (`econosim desktop --screenshots DIR`).
"""

from __future__ import annotations

import contextlib
import os
import sys
import tempfile
import threading
import time
import traceback
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import shiboken6
from PySide6.QtCore import QByteArray, QCoreApplication, QEvent, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

from prometheus.desktop import forms, launcher
from prometheus.desktop.runner import WorkerLoop
from prometheus.desktop.session import LocalSession, configure_worker_environment
from prometheus.desktop.ui import theme as theme_module
from prometheus.desktop.ui.main_window import MainWindow

WINDOW_SIZE = (1320, 860)


def app_icon() -> QIcon:
    """The launcher's icon (one SVG, drawn by `launcher.ICON_SVG`) at the sizes a window needs."""
    renderer = QSvgRenderer(QByteArray(launcher.ICON_SVG.encode()))
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        icon.addPixmap(pixmap)
    return icon


def create_application() -> QApplication:
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    app = QApplication(sys.argv[:1])
    app.setApplicationName("econosim")
    app.setApplicationDisplayName("ECONOSIM")
    app.setDesktopFileName("econosim")
    app.setWindowIcon(app_icon())
    return app


ERROR_LOG = "errors.log"


def install_error_log(
    state: Path, on_error: Callable[[str], None] | None = None
) -> Callable[[], None]:
    """Write every uncaught exception (in the window's thread or any other) to
    `<state>/errors.log` and tell `on_error` in one line.

    A program started from an application menu has no terminal, so an exception that nobody
    catches would otherwise vanish without a trace. The usual hooks still run afterwards, so a
    terminal still shows it. Returns the function that takes the hooks off again, so that a caller
    that is finished with the window leaves the interpreter's hooks as it found them.
    """
    log = state / ERROR_LOG

    def record(kind: type[BaseException], value: BaseException | None, trace: Any) -> None:
        shown = value if value is not None else kind()
        text = "".join(traceback.format_exception(kind, shown, trace))
        stamp = datetime.now(UTC).isoformat(timespec="seconds")
        with contextlib.suppress(OSError):  # a full disk must not turn one error into two
            with open(log, "a", encoding="utf-8") as stream:
                stream.write(f"--- {stamp}\n{text}\n")
            os.chmod(log, 0o600)
        if on_error is not None:
            on_error(f"An internal error was logged to {log.name}: {kind.__name__}: {shown}")

    def main_hook(kind: type[BaseException], value: BaseException, trace: Any) -> None:
        record(kind, value, trace)
        sys.__excepthook__(kind, value, trace)

    def thread_hook(args: threading.ExceptHookArgs) -> None:
        record(args.exc_type, args.exc_value, args.exc_traceback)
        threading.__excepthook__(args)

    previous_main, previous_thread = sys.excepthook, threading.excepthook
    sys.excepthook = main_hook
    threading.excepthook = thread_hook

    def uninstall() -> None:
        # only our own hooks: if something else was put on top since, it is not ours to remove
        if sys.excepthook is main_hook:
            sys.excepthook = previous_main
        if threading.excepthook is thread_hook:
            threading.excepthook = previous_thread

    return uninstall


def dispose(window: MainWindow) -> None:
    """Take the window down on purpose, while Qt is still running.

    A window that nobody deletes is deleted when the interpreter exits, in an arbitrary order
    alongside Qt's own objects; this program once ended that way with a heap corruption instead of
    an exit status. Stopping what runs behind the window and deleting it now, with the event
    loop's deferred deletions delivered, keeps the end of the program as ordinary as the rest of
    it, whatever might still refer to the window.
    """
    if not shiboken6.isValid(window):  # already taken down: nothing left to do
        return
    window.shutdown()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def preferred_size(app: QApplication) -> tuple[int, int]:
    """Most of the screen, but never more than the layouts are designed for."""
    screen = app.primaryScreen()
    if screen is None:
        return WINDOW_SIZE
    area = screen.availableGeometry()
    return min(1500, int(area.width() * 0.92)), min(1000, int(area.height() * 0.92))


def run(state: Path, *, theme: str = "system") -> int:
    """Open the window and block until it is closed; returns the process exit status."""
    configure_worker_environment()
    app = create_application()
    theme_module.apply_theme(app, theme)
    session = LocalSession(state)
    runner = WorkerLoop(session)
    runner.start()
    # the first time a lab is opened its config type has to be imported (it loads torch);
    # doing that now, behind the window, makes the first click instant
    threading.Thread(target=forms.warm_up, name="econosim-warm-up", daemon=True).start()
    window = MainWindow(session, state_dir=state, runner=runner, theme_mode=theme)
    uninstall = install_error_log(state, window.errorLogged.emit)
    window.resize(*preferred_size(app))
    window.show()
    try:
        return app.exec()
    finally:
        uninstall()
        dispose(window)


def pump(app: QApplication, until: Callable[[], bool], *, timeout: float = 120.0) -> bool:
    """Run Qt's event loop until `until()` is true; False if it never became true."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if until():
            return True
        time.sleep(0.02)
    return False


def screenshots(out_dir: Path, *, theme: str = "system") -> int:
    """Render each page to `out_dir/NN-name.png`. Uses a throwaway state directory, so it neither
    reads nor writes anything of the person's; the lab result it shows is a real (small) run."""
    configure_worker_environment()
    app = create_application()
    theme_module.apply_theme(app, theme)
    out_dir.mkdir(parents=True, exist_ok=True)
    forms.warm_up()
    with tempfile.TemporaryDirectory(prefix="econosim-shots-") as scratch:
        session = LocalSession(Path(scratch) / "state")
        runner = WorkerLoop(session)
        runner.start()
        window = MainWindow(
            session,
            state_dir=Path(scratch) / "state",
            runner=runner,
            theme_mode=theme,
            confirm_close=False,
        )
        window.resize(*WINDOW_SIZE)
        window.show()
        written: list[Path] = []

        def shot(name: str) -> None:
            pump(app, lambda: False, timeout=0.35)  # let the (asynchronous) layout finish
            path = out_dir / f"{len(written) + 1:02d}-{name}.png"
            window.grab().save(str(path))
            written.append(path)

        try:
            pump(app, lambda: False, timeout=0.3)
            shot("overview")
            window.show_page("labs")
            window.labs.select_kind("inflationcast")
            form = window.labs.form()
            form.set_values({("max_epochs",): "3", ("bootstrap_resamples",): "40"})
            shot("labs-parameters")
            job_id = window.labs.run()
            if job_id is not None:
                pump(app, lambda: window.labs.result.view is not None, timeout=120)
                window.tick()
                pump(app, lambda: False, timeout=0.3)
                shot("labs-result")
            window.show_page("explorers")
            window.explorers.select("market_paths")
            pump(app, lambda: window.explorers.result.view is not None, timeout=60)
            shot("explorers-market-paths")
            window.explorers.select("pricing")
            pump(app, lambda: window.explorers.result.view is not None, timeout=60)
            shot("explorers-pricing")
            window.show_page("findings")
            if window.findings.document.available:
                window.findings.select("finding:18")
            shot("findings")
            window.show_page("atlas")
            window.atlas.view3d.configure(auto_rotate=False, reduce_motion=False, labels="selected")
            window.atlas.select("fno")
            shot("atlas")
            window.atlas.show_view("2d")
            shot("atlas-2d")
            window.show_page("history")
            shot("history")
            window.show_page("system")
            shot("system")
            window.show_page("settings")
            shot("settings")
        finally:
            dispose(window)
    for path in written:
        print(path)
    return 0
