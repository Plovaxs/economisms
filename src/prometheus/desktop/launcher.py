"""Make the application appear in the desktop's application menu, like any other program.

`install_launcher` writes two small files under the user's XDG data directory (never anywhere
else, never with elevated rights): a freedesktop *desktop entry* and its icon. Removing them is
`uninstall_launcher`. That is all "installing" means here; the program itself stays in the
environment it was installed into, and the entry points at that environment's interpreter by
absolute path, so moving or deleting the environment breaks the launcher (reinstall it).

Both operations are careful with files that are not theirs. A file is only overwritten or removed
if it carries this module's marker line (`X-Econosim-Launcher=1`), and a symlink in either place is
refused rather than followed, so a planted link cannot redirect a write to somewhere else.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

APP_ID = "econosim"
MARKER = "X-Econosim-Launcher=1"
ICON_MARK = 'aria-label="ECONOSIM"'
ENTRY_NAME = f"{APP_ID}.desktop"
ICON_NAME = f"{APP_ID}.svg"

ICON_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256" \
role="img" aria-label="ECONOSIM">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#6d28d9"/>
      <stop offset="1" stop-color="#0e7490"/>
    </linearGradient>
  </defs>
  <rect width="256" height="256" rx="56" fill="url(#bg)"/>
  <path d="M48 208H208" stroke="#ffffff" stroke-opacity="0.55" stroke-width="8" \
stroke-linecap="round"/>
  <path d="M48 176L96 128L136 152L208 72" fill="none" stroke="#ffffff" stroke-width="16" \
stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="208" cy="72" r="14" fill="#ffffff"/>
</svg>
"""


class LauncherError(OSError):
    """A launcher file could not be written or removed safely."""


def quote_exec_argument(argument: str) -> str:
    """One argument of a desktop entry's `Exec` line, per the freedesktop specification: always
    double-quoted, with `"`, `` ` ``, `$` and `\\` escaped inside the quotes and `%` doubled so it
    is not read as a field code."""
    escaped = argument.replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("`", "\\`").replace("$", "\\$").replace("%", "%%")
    return f'"{escaped}"'


def desktop_entry(python: str | None = None) -> str:
    interpreter = sys.executable if python is None else python
    command = f"{quote_exec_argument(interpreter)} -m prometheus.desktop"
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Version=1.5\n"
        "Name=ECONOSIM\n"
        "GenericName=Economics research workbench\n"
        "Comment=PROMETHEUS-X: simulation and deep-learning research for quantitative "
        "economics. Research only, not financial advice.\n"
        f"Exec={command}\n"
        f"Icon={APP_ID}\n"
        "Terminal=false\n"
        "Categories=Education;Science;Economy;ArtificialIntelligence;NumericalAnalysis;\n"
        "Keywords=economics;simulation;deep learning;finance;research;\n"
        f"StartupWMClass={APP_ID}\n"
        f"{MARKER}\n"
    )


def default_data_home(environ: dict[str, str] | None = None, *, home: Path | None = None) -> Path:
    env = os.environ if environ is None else environ
    configured = env.get("XDG_DATA_HOME")
    if configured and Path(configured).is_absolute():
        return Path(configured)
    return (home if home is not None else Path.home()) / ".local" / "share"


def _paths(data_home: Path) -> tuple[Path, Path]:
    return (
        data_home / "applications" / ENTRY_NAME,
        data_home / "icons" / "hicolor" / "scalable" / "apps" / ICON_NAME,
    )


def _is_ours(path: Path, mark: str) -> bool:
    try:
        return mark in path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False


def _write_atomically(path: Path, text: str, *, mark: str) -> None:
    if path.is_symlink():
        raise LauncherError(f"{path} is a symlink; refusing to write through it")
    if path.exists() and not _is_ours(path, mark):
        raise LauncherError(f"{path} exists and was not created by ECONOSIM; not overwriting it")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def install_launcher(
    data_home: Path | None = None, *, python: str | None = None
) -> tuple[Path, Path]:
    """Write the desktop entry and the icon; returns `(entry, icon)`. Re-running it updates our
    own files (for instance after the environment moved) and refuses to touch anyone else's."""
    entry, icon = _paths(default_data_home() if data_home is None else data_home)
    _write_atomically(entry, desktop_entry(python), mark=MARKER)
    _write_atomically(icon, ICON_SVG, mark=ICON_MARK)
    return entry, icon


def uninstall_launcher(data_home: Path | None = None) -> list[Path]:
    """Remove the files `install_launcher` wrote; returns what was removed. Anything that is not
    ours, or is a symlink, is left exactly as it is."""
    entry, icon = _paths(default_data_home() if data_home is None else data_home)
    removed: list[Path] = []
    for path, mark in ((entry, MARKER), (icon, ICON_MARK)):
        if path.is_symlink() or not path.exists():
            continue
        if _is_ours(path, mark):
            path.unlink()
            removed.append(path)
    return removed
