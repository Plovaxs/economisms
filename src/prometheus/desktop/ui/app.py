"""Start the application: create Qt's application object, the session, the worker thread, the
window -- and, headlessly, render every page to a PNG (`econosim desktop --screenshots DIR`).
"""

from __future__ import annotations

import sys
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
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
    window.resize(*preferred_size(app))
    window.show()
    try:
        return app.exec()
    finally:
        window.shutdown()


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
            window.show_page("history")
            shot("history")
            window.show_page("system")
            shot("system")
        finally:
            window.shutdown()
    for path in written:
        print(path)
    return 0
