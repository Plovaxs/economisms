"""The person's settings for the desktop application, kept as one small JSON file.

Framework-free (no Qt) so it is tested without a display. The rules mirror the web app's: a value
that is not one of the listed choices is never accepted (an old or hand-edited file cannot put the
window into a state nobody designed), a missing or corrupt file means the defaults, and writing is
atomic and private (the file is `0600` in a `0700` state directory, like everything else the
application keeps).
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

FILE_NAME = "settings.json"
THEMES = ("system", "dark", "light")
TEXT_SCALES = (0.85, 1.0, 1.15, 1.3, 1.5)
ATLAS_VIEWS = ("3d", "2d")
LABELS = ("selected", "all", "none")


@dataclass(frozen=True, slots=True)
class DesktopSettings:
    theme: str = "system"
    text_scale: float = 1.0
    high_contrast: bool = False
    reduce_motion: bool = False
    atlas_view: str = "3d"
    auto_rotate: bool = True
    labels_3d: str = "selected"

    def with_changes(self, **changes: Any) -> DesktopSettings:
        return sanitize({**asdict(self), **changes})


DEFAULTS = DesktopSettings()


def sanitize(raw: object) -> DesktopSettings:
    """Keep the values this version knows; every other field takes its default."""
    if not isinstance(raw, dict):
        return DEFAULTS
    out = asdict(DEFAULTS)
    if raw.get("theme") in THEMES:
        out["theme"] = raw["theme"]
    scale = raw.get("text_scale")
    if (
        isinstance(scale, (int, float))
        and not isinstance(scale, bool)
        and float(scale) in TEXT_SCALES
    ):
        out["text_scale"] = float(scale)
    for name in ("high_contrast", "reduce_motion", "auto_rotate"):
        if isinstance(raw.get(name), bool):
            out[name] = raw[name]
    if raw.get("atlas_view") in ATLAS_VIEWS:
        out["atlas_view"] = raw["atlas_view"]
    if raw.get("labels_3d") in LABELS:
        out["labels_3d"] = raw["labels_3d"]
    return DesktopSettings(**out)


def settings_path(state_dir: Path) -> Path:
    return state_dir / FILE_NAME


def load(state_dir: Path) -> DesktopSettings:
    try:
        return sanitize(json.loads(settings_path(state_dir).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return DEFAULTS


def save(state_dir: Path, settings: DesktopSettings) -> bool:
    """Write atomically and privately; False if the directory cannot be written (the settings still
    apply for this session)."""
    try:
        created = not state_dir.exists()
        state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        if created:
            os.chmod(state_dir, 0o700)  # the state directory is private, whoever makes it first
        descriptor, temporary = tempfile.mkstemp(dir=state_dir, prefix=".settings-", suffix=".tmp")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(asdict(settings), handle, indent=2, sort_keys=True)
                handle.write("\n")
            os.chmod(temporary, 0o600)
            os.replace(temporary, settings_path(state_dir))
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
        return True
    except OSError:
        return False


def field_names() -> tuple[str, ...]:
    return tuple(f.name for f in fields(DesktopSettings))


__all__ = [
    "DEFAULTS",
    "DesktopSettings",
    "field_names",
    "load",
    "sanitize",
    "save",
    "settings_path",
]
