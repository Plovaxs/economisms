"""Where the desktop application keeps its state, and the checks that keep that place private.

The state directory holds the job database, the verified result artifacts and a lock file. It is
created `0700` and an existing one is *refused* -- never silently `chmod`-ed -- when it is a
symlink, belongs to someone else, or is readable or writable by group or others: quietly changing
the permissions of a directory the user pointed us at would be a surprise, and so would running
with results other users can edit.

One window per state directory: two workers claiming from one queue would not corrupt it (SQLite
serialises the claims) but would double the CPU load behind a single progress display, so a second
instance is told so and exits.
"""

from __future__ import annotations

import fcntl
import os
import stat
from collections.abc import Mapping
from pathlib import Path
from types import TracebackType

APP_DIRECTORY = "econosim"
HOME_ENVIRONMENT_VARIABLE = "ECONOSIM_HOME"
LOCK_FILENAME = "desktop.lock"


class StateDirectoryError(OSError):
    """The state directory is missing, not private, or not ours."""


class AlreadyRunningError(RuntimeError):
    """Another desktop instance holds this state directory."""


def default_state_dir(
    environ: Mapping[str, str] | None = None, *, home: Path | None = None
) -> Path:
    """`$ECONOSIM_HOME`, else `$XDG_DATA_HOME/econosim`, else `~/.local/share/econosim`.

    A relative path is refused: where "relative to the working directory" lands depends on how
    the program was launched (a menu entry starts in `$HOME`, a terminal wherever you were), and
    results written to a different place each time would look like lost work.
    """
    env = os.environ if environ is None else environ
    explicit = env.get(HOME_ENVIRONMENT_VARIABLE)
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_absolute():
            raise StateDirectoryError(f"{HOME_ENVIRONMENT_VARIABLE} must be an absolute path")
        return path
    data_home = env.get("XDG_DATA_HOME")
    if data_home and Path(data_home).is_absolute():
        return Path(data_home) / APP_DIRECTORY
    return (home if home is not None else Path.home()) / ".local" / "share" / APP_DIRECTORY


def ensure_private_directory(path: Path) -> Path:
    """Create `path` (mode 0700) or accept it only if it is already a private directory of ours."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(path, 0o700)  # the umask can only remove bits, but say what we mean
        return path.resolve()
    except OSError as exc:
        raise StateDirectoryError(f"cannot inspect {path}: {type(exc).__name__}") from exc
    if stat.S_ISLNK(info.st_mode):
        raise StateDirectoryError(f"{path} is a symlink; refusing to keep state behind one")
    if not stat.S_ISDIR(info.st_mode):
        raise StateDirectoryError(f"{path} exists and is not a directory")
    if info.st_uid != os.getuid():
        raise StateDirectoryError(f"{path} is owned by another user")
    if info.st_mode & 0o077:
        raise StateDirectoryError(
            f"{path} has mode {stat.S_IMODE(info.st_mode):04o}: readable or writable by group or "
            f"others. Run `chmod 700 {path}` or choose another directory."
        )
    return path.resolve()


class InstanceLock:
    """An exclusive advisory lock on `<state>/desktop.lock`, released when the process ends."""

    def __init__(self, directory: Path) -> None:
        self._path = directory / LOCK_FILENAME
        self._descriptor: int | None = None

    def acquire(self) -> None:
        if self._descriptor is not None:
            return
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self._path, flags, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(descriptor)
            raise AlreadyRunningError(
                f"another ECONOSIM window is already using {self._path.parent}"
            ) from exc
        except BaseException:
            os.close(descriptor)
            raise
        self._descriptor = descriptor

    def release(self) -> None:
        if self._descriptor is None:
            return
        descriptor, self._descriptor = self._descriptor, None
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)

    @property
    def held(self) -> bool:
        return self._descriptor is not None

    def __enter__(self) -> InstanceLock:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release()
