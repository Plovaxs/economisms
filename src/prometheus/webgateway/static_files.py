"""Pure, ASGI-free static-file resolution over a built frontend
directory (`frontend/dist/`). No socket, no ASGI scope -- a plain
function from (root, request path) to file bytes, fully unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_FALLBACK_CONTENT_TYPE = "application/octet-stream"
_INDEX_FILE_NAME = "index.html"

# An explicit table, never `mimetypes.guess_type`: that consults the host's
# `/etc/mime.types` and the running Python's own defaults, so the same
# `.js` file could be served as `text/javascript`, `application/javascript`
# or -- on a slim image with no mime database -- `application/octet-stream`
# depending on where the gateway happened to run. With `nosniff` set, a
# browser REFUSES to execute a module script served with the wrong type,
# so this must be deterministic.
_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".map": "application/json",
    ".webmanifest": "application/manifest+json",
    ".txt": "text/plain; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".wasm": "application/wasm",
}


@dataclass(frozen=True, slots=True)
class StaticFile:
    body: bytes
    content_type: str
    relative_path: str
    is_spa_fallback: bool

    @property
    def is_html(self) -> bool:
        return self.content_type.startswith("text/html")


class StaticFileNotFoundError(ValueError):
    """Raised when neither the requested path nor the SPA fallback
    (`index.html`) exist under the configured dist root, or when a path
    that names a file (it has an extension) matches nothing."""


def resolve_static_file(dist_root: Path, request_path: str) -> StaticFile:
    """Resolve `request_path` (an already percent-decoded, already
    validated absolute path, e.g. "/assets/index-abc123.js") to a file
    under `dist_root`.

    Rejects any path that would resolve OUTSIDE `dist_root` (an absolute
    escape via a symlink, etc.) by resolving the candidate path and
    checking containment -- never by just screening for the substring
    "..", which a smarter traversal can route around -- and refuses
    hidden files and directories (`.env`, `.git/...`) outright.

    A request for a directory, or an extension-less path with no matching
    file, falls back to `index.html` (the SPA client-side router then
    resolves the real view). A path that NAMES a file -- its last segment
    has an extension, like `/assets/app.js` -- and matches nothing is a
    404, never a 200 carrying HTML: serving the shell there turns a
    missing script into a baffling "unexpected token <" in the browser."""
    resolved_root = dist_root.resolve()
    segments = [segment for segment in request_path.split("/") if segment]
    if any(segment.startswith(".") and segment != ".well-known" for segment in segments):
        raise StaticFileNotFoundError(f"no file at {request_path!r}")
    try:
        candidate = (resolved_root / "/".join(segments)).resolve()
        is_file = candidate != resolved_root and candidate.is_relative_to(resolved_root)
        is_file = is_file and candidate.is_file()
    except (OSError, ValueError) as exc:
        # An embedded NUL or an over-long name: not a file, and never a 500.
        raise StaticFileNotFoundError(f"no file at {request_path!r}") from exc
    if is_file:
        target = candidate
        is_fallback = False
    else:
        if segments and "." in segments[-1]:
            raise StaticFileNotFoundError(f"no file at {request_path!r}")
        target = resolved_root / _INDEX_FILE_NAME
        is_fallback = True
        if not target.is_file():
            raise StaticFileNotFoundError(
                f"no file at {request_path!r} and no {_INDEX_FILE_NAME} fallback "
                f"under {resolved_root} -- has the frontend actually been built "
                f"('npm run build' in frontend/)?"
            )
    content_type = _CONTENT_TYPES.get(target.suffix.lower(), _FALLBACK_CONTENT_TYPE)
    return StaticFile(
        body=target.read_bytes(),
        content_type=content_type,
        relative_path=target.relative_to(resolved_root).as_posix(),
        is_spa_fallback=is_fallback,
    )
