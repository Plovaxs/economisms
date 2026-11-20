"""`econosim desktop` / `python -m prometheus.desktop`: open the application.

econosim desktop                      open the window
econosim desktop --check              test everything that does not need a display, and exit
econosim desktop --install-launcher   add ECONOSIM to the application menu
econosim desktop --uninstall-launcher remove it again
econosim desktop --screenshots DIR    render every page to PNG files (headless) and exit
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from prometheus.desktop import displaycheck, launcher
from prometheus.desktop.paths import (
    AlreadyRunningError,
    InstanceLock,
    StateDirectoryError,
    default_state_dir,
    ensure_private_directory,
)
from prometheus.desktop.session import configure_worker_environment

STARTUP_ERROR_FILE = "startup-error.txt"
MISSING_QT = (
    "econosim desktop: the window needs PySide6, which is not installed.\n"
    "  with uv:   uv sync --extra desktop\n"
    "  with pip:  pip install 'prometheus-econ[desktop]'\n"
    "Everything else works without it (`econosim desktop --check` shows what)."
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="econosim desktop",
        description="ECONOSIM / PROMETHEUS-X as a desktop application. Research and simulation "
        "only: not financial advice, not a trading system (gate decision: NO-GO).",
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        help="where jobs and results are kept (default: $ECONOSIM_HOME, else "
        "$XDG_DATA_HOME/econosim, else ~/.local/share/econosim)",
    )
    parser.add_argument("--theme", choices=("system", "dark", "light"), default="system")
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--check", action="store_true", help="self-test without a window, then exit"
    )
    action.add_argument(
        "--install-launcher", action="store_true", help="add ECONOSIM to the application menu"
    )
    action.add_argument(
        "--uninstall-launcher", action="store_true", help="remove the application-menu entry"
    )
    action.add_argument(
        "--screenshots",
        type=Path,
        metavar="DIR",
        help="render every page to a PNG in DIR (no display needed), then exit",
    )
    return parser


def _ui_app() -> Any:
    """The Qt side, imported only now: nothing else in this package needs PySide6."""
    return importlib.import_module("prometheus.desktop.ui.app")


def _run_check() -> int:
    from prometheus.desktop import selfcheck

    results = selfcheck.run_checks()
    for check in results:
        print(f"[{check.status:4}] {check.name}: {check.detail}")
    failed = [check for check in results if check.status == "fail"]
    print("desktop check: all clear" if not failed else f"desktop check: {len(failed)} failed")
    return 1 if failed else 0


def _cannot_open(state: Path, problems: list[displaycheck.DisplayProblem]) -> int:
    """Say why the window cannot open, everywhere a person might look: the terminal, a desktop
    notification (a menu entry has no terminal) and a file in the state directory."""
    message = displaycheck.report(problems)
    print(f"econosim desktop: the window cannot open here.\n{message}", file=sys.stderr)
    displaycheck.notify(message)
    note = state / STARTUP_ERROR_FILE
    try:
        note.write_text(f"{message}\n", encoding="utf-8")
        note.chmod(0o600)
    except OSError:
        pass
    return 1


def _launcher(install: bool) -> int:
    try:
        if install:
            entry, icon = launcher.install_launcher()
            print(f"installed {entry}\ninstalled {icon}")
            print("It may take a moment (or a re-login) for the menu to show ECONOSIM.")
            for problem in displaycheck.check_display():
                print(
                    f"warning: the menu entry will not open a window yet.\n{problem.text()}",
                    file=sys.stderr,
                )
        else:
            removed = launcher.uninstall_launcher()
            print("\n".join(f"removed {path}" for path in removed) or "nothing to remove")
    except OSError as exc:
        print(f"econosim desktop: {exc}", file=sys.stderr)
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    configure_worker_environment()
    if args.check:
        return _run_check()
    if args.install_launcher or args.uninstall_launcher:
        return _launcher(args.install_launcher)
    if importlib.util.find_spec("PySide6") is None:
        print(MISSING_QT, file=sys.stderr)
        return 1
    if args.screenshots is not None:
        # a throwaway state directory: this reads and writes nothing of the person's
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        return int(_ui_app().screenshots(args.screenshots, theme=args.theme))
    try:
        state = ensure_private_directory(args.state_dir or default_state_dir())
    except StateDirectoryError as exc:
        print(f"econosim desktop: {exc}", file=sys.stderr)
        return 1
    problems = displaycheck.check_display()
    if problems:
        return _cannot_open(state, problems)
    try:
        with InstanceLock(state):
            return int(_ui_app().run(state, theme=args.theme))
    except AlreadyRunningError as exc:
        print(f"econosim desktop: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
