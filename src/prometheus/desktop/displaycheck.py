"""Will Qt be able to open a window on this machine? Answered *before* Qt is asked.

Qt 6.5 and later cannot load its X11 platform plugin without the system library `libxcb-cursor`
(the Qt wheel does not bundle it). When it is missing Qt does not raise an error a program can
catch: it prints one line and aborts the process, leaving a core dump. Run from a terminal that is
a poor message; started from an application-menu entry, where nobody sees the line, it is a program
that silently does nothing -- which is the worst way for "software you open" to fail.

So the desktop command checks first, in plain Python, for the one thing that is both common and
fixable, and says exactly what to install. It also notices the other way a window cannot open: no
graphical session at all.

What it does not do: it does not install anything (that needs your administrator rights and your
say-so), and it does not claim the window will open -- only that this known cause is absent.
"""

from __future__ import annotations

import ctypes.util
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass

XCB_REMEDY = (
    "Debian/Ubuntu: sudo apt install libxcb-cursor0   |   "
    "Fedora: sudo dnf install xcb-util-cursor   |   Arch: sudo pacman -S xcb-util-cursor"
)
NO_SESSION_REMEDY = (
    "Run this from a desktop session. Without one, `econosim desktop --check` and "
    "`econosim desktop --screenshots DIR` still work."
)


@dataclass(frozen=True, slots=True)
class DisplayProblem:
    summary: str
    remedy: str

    def text(self) -> str:
        return f"{self.summary}\n  {self.remedy}"


def effective_platform(environ: Mapping[str, str] | None = None) -> str:
    """The Qt platform that would be used: `offscreen`, `xcb` (X11), `wayland` or `none`."""
    env = os.environ if environ is None else environ
    explicit = env.get("QT_QPA_PLATFORM", "").split(":")[0].strip()
    if explicit:
        return explicit
    if env.get("XDG_SESSION_TYPE") == "wayland" and env.get("WAYLAND_DISPLAY"):
        return "wayland"
    if env.get("DISPLAY"):
        return "xcb"
    if env.get("WAYLAND_DISPLAY"):
        return "wayland"
    return "none"


def check_display(
    environ: Mapping[str, str] | None = None,
    *,
    platform: str = sys.platform,
    find_library: Callable[[str], str | None] | None = None,
) -> list[DisplayProblem]:
    """The known reasons a window cannot open here (empty when none is found).

    The library lookup is resolved when called, not when the module is imported, so that what is
    installed *now* is what is asked about.
    """
    if not platform.startswith("linux"):
        return []
    lookup = find_library if find_library is not None else ctypes.util.find_library
    kind = effective_platform(environ)
    if kind == "none":
        return [
            DisplayProblem(
                "No graphical session was found (neither DISPLAY nor WAYLAND_DISPLAY is set).",
                NO_SESSION_REMEDY,
            )
        ]
    if kind == "xcb" and lookup("xcb-cursor") is None:
        return [
            DisplayProblem(
                "Qt's X11 plugin needs the system library libxcb-cursor, which is not installed; "
                "without it the window cannot open.",
                XCB_REMEDY,
            )
        ]
    return []


def report(problems: list[DisplayProblem]) -> str:
    return "\n".join(problem.text() for problem in problems)


def notify(message: str, *, which: Callable[[str], str | None] = shutil.which) -> bool:
    """Best-effort desktop notification, for the case that matters: a program started from the
    application menu has no terminal to print to. Returns whether a notifier ran."""
    tool = which("notify-send")
    if tool is None:
        return False
    try:
        # S603: a fixed tool path from `which`, fixed flags, and the text as ONE argument (never
        # parsed by a shell)
        subprocess.run(  # noqa: S603
            [tool, "--app-name=ECONOSIM", "ECONOSIM could not open its window", message],
            timeout=5,
            check=False,
            capture_output=True,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return True
