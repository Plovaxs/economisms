"""Shared helpers for the desktop window's tests, which run Qt headlessly (`offscreen`).

If PySide6 (the `desktop` extra) is not installed the window tests are skipped -- unless
`ECONOSIM_REQUIRE_DESKTOP_TESTS=1`, which CI sets: there the same condition is a failure, so a
broken install cannot quietly turn every window test into a skip.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REQUIRE_ENV = "ECONOSIM_REQUIRE_DESKTOP_TESTS"


def require_qt() -> None:
    """Skip the calling test module when Qt is unavailable (or fail, under `REQUIRE_ENV`)."""
    try:
        import PySide6.QtWidgets  # noqa: F401
    except ImportError as exc:
        if os.environ.get(REQUIRE_ENV) == "1":
            raise
        pytest.skip(f"PySide6 is not available: {exc}", allow_module_level=True)


def pump(until: Callable[[], bool] = lambda: False, *, timeout: float = 30.0) -> bool:
    """Run Qt's event loop until `until()` holds (or `timeout` passes); True if it held."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    deadline = time.monotonic() + timeout
    while True:
        if app is not None:
            app.processEvents()
        if until():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.01)


def settle(seconds: float = 0.15) -> None:
    """Let queued layout and paint events run (a few event-loop turns), and really delete what
    `deleteLater()` was called on.

    `processEvents()` alone never delivers the deferred-delete event, so windows a test "deleted"
    would pile up for the whole run and make every later style change (which re-polishes every
    live widget) slower: 12 leaked windows turned a 0.2 s theme change into 2.7 s.
    """
    from PySide6.QtCore import QCoreApplication, QEvent

    pump(lambda: False, timeout=seconds)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def grab_pixels(widget: Any) -> Any:
    """The widget rendered to a `QImage`."""
    settle(0.05)
    return widget.grab().toImage()


def distinct_colors(image: Any, *, step: int = 4) -> int:
    """How many different colours an image has (sampled): a blank render has one or two."""
    seen = set()
    for y in range(0, image.height(), step):
        for x in range(0, image.width(), step):
            seen.add(image.pixel(x, y))
    return len(seen)


def focus(widget: Any) -> None:
    """Give `widget` keyboard focus *and* deliver the focus-in event.

    On the headless platform a window is not active, so `setFocus()` alone records the focus but
    never sends the event a chart reacts to; real use (a person tabbing into it) always does.
    """
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QFocusEvent
    from PySide6.QtWidgets import QApplication

    widget.setFocus()
    QApplication.sendEvent(widget, QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.TabFocusReason))
    settle(0.05)
