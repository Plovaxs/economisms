"""Fixtures for the desktop window's tests (Qt, headless). Nothing here is imported unless a test
asks for it, so the rest of the suite is unaffected and PySide6 stays optional."""

from __future__ import annotations

import gc
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.unit import desktop_ui_support as support


@pytest.fixture(scope="session")
def qapp() -> Iterator[Any]:
    """One `QApplication` for the whole run (Qt allows only one)."""
    support.require_qt()
    from prometheus.desktop.session import configure_worker_environment
    from prometheus.desktop.ui.app import create_application

    configure_worker_environment()
    app = create_application()
    yield app
    # let Python drop its wrappers of Qt-owned singletons (the clipboard) while the application
    # object still exists, rather than in an arbitrary order at interpreter exit
    app.closeAllWindows()
    app.processEvents()
    gc.collect()


@pytest.fixture
def theme_dark(qapp: Any) -> Iterator[Any]:
    """The dark theme in force for one test; the previous palette is restored afterwards."""
    from prometheus.desktop.ui import theme

    before = theme.current()
    palette = theme.apply_theme(qapp, "dark")
    yield palette
    if theme.current() is not before:
        theme.apply_theme(qapp, before.name)


@pytest.fixture
def theme_light(qapp: Any) -> Iterator[Any]:
    from prometheus.desktop.ui import theme

    before = theme.current()
    palette = theme.apply_theme(qapp, "light")
    yield palette
    if theme.current() is not before:
        theme.apply_theme(qapp, before.name)


@pytest.fixture
def ui_session(tmp_path: Path) -> Any:
    """A real `LocalSession` in a private temporary state directory."""
    from prometheus.desktop.session import LocalSession

    return LocalSession(tmp_path / "state")


@pytest.fixture
def window(qapp: Any, ui_session: Any, theme_dark: Any, tmp_path: Path) -> Iterator[Any]:
    """The whole window over a real session with a real worker thread, closed without a prompt."""
    from prometheus.desktop import forms
    from prometheus.desktop.runner import WorkerLoop
    from prometheus.desktop.ui.main_window import MainWindow

    forms.warm_up()
    runner = WorkerLoop(ui_session, idle_seconds=0.05)
    runner.start()
    shown = MainWindow(
        ui_session,
        state_dir=tmp_path / "state",
        runner=runner,
        theme_mode="dark",
        confirm_close=False,
    )
    shown.resize(1320, 860)
    shown.show()
    support.settle()
    yield shown
    shown.shutdown()
    shown.close()
    shown.deleteLater()  # a window left alive makes every later style change slower
    support.settle(0.05)
