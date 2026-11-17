"""Pure, ASGI-free static-file resolution over a built frontend
directory (`frontend/dist/`). No socket, no ASGI scope -- a plain
function from (root, request path) to file bytes, fully unit-testable.
"""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import Path

_FALLBACK_CONTENT_TYPE = "application/octet-stream"
_INDEX_FILE_NAME = "index.html"


@dataclass(frozen=True, slots=True)
class StaticFile:
    body: bytes
    content_type: str


class StaticFileNotFoundError(ValueError):
    """Raised when neither the requested path nor the SPA fallback
    (`index.html`) exist under the configured dist root."""


def resolve_static_file(dist_root: Path, request_path: str) -> StaticFile:
    """Resolve `request_path` (an ASGI scope's already percent-decoded
    `path`, e.g. "/assets/index-abc123.js") to a file under `dist_root`.

    Rejects any path that would resolve OUTSIDE `dist_root` (`..`
    traversal, an absolute escape via a symlink, etc.) by resolving the
    candidate path and checking containment -- never by just screening
    for the substring ".." , which a smarter traversal can route around.
    A request for a directory, or any path with no matching file, falls
    back to `index.html` (the SPA client-side router then resolves the
    real view) -- UNLESS the fallback itself is missing, which is a
    real misconfiguration (no build has ever been produced here)."""
    resolved_root = dist_root.resolve()
    candidate = (resolved_root / request_path.lstrip("/")).resolve()
    if candidate.is_relative_to(resolved_root) and candidate.is_file():
        target = candidate
    else:
        target = resolved_root / _INDEX_FILE_NAME
        if not target.is_file():
            raise StaticFileNotFoundError(
                f"no file at {request_path!r} and no {_INDEX_FILE_NAME} fallback "
                f"under {resolved_root} -- has the frontend actually been built "
                f"('npm run build' in frontend/)?"
            )
    content_type, _ = mimetypes.guess_type(target.name)
    return StaticFile(body=target.read_bytes(), content_type=content_type or _FALLBACK_CONTENT_TYPE)
