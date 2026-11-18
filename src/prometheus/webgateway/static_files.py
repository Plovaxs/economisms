"""Pure, ASGI-free static-file resolution over a built frontend
directory (`frontend/dist/`). No socket, no ASGI scope -- a plain
function from (root, request path) to file bytes, fully unit-testable.
"""

from __future__ import annotations

import gzip
import hashlib
import threading
from collections import OrderedDict
from dataclasses import dataclass, replace
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


_COMPRESSIBLE = (
    "text/",
    "application/json",
    "application/manifest+json",
    "image/svg+xml",
)
_MIN_COMPRESS_BYTES = 1024


@dataclass(frozen=True, slots=True)
class StaticFile:
    body: bytes
    content_type: str
    relative_path: str
    is_spa_fallback: bool
    etag: str = ""
    gzipped: bytes | None = None

    @property
    def is_html(self) -> bool:
        return self.content_type.startswith("text/html")


class StaticFileNotFoundError(ValueError):
    """Raised when neither the requested path nor the SPA fallback
    (`index.html`) exist under the configured dist root, or when a path
    that names a file (it has an extension) matches nothing."""


def locate_static_file(dist_root: Path, request_path: str) -> tuple[Path, str, bool]:
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
    return target, target.relative_to(resolved_root).as_posix(), is_fallback


def _load(target: Path, relative_path: str, is_fallback: bool) -> StaticFile:
    body = target.read_bytes()
    content_type = _CONTENT_TYPES.get(target.suffix.lower(), _FALLBACK_CONTENT_TYPE)
    packed: bytes | None = None
    if len(body) >= _MIN_COMPRESS_BYTES and content_type.startswith(_COMPRESSIBLE):
        # mtime=0 and a fixed level: the same bytes always compress to the same bytes.
        candidate = gzip.compress(body, compresslevel=6, mtime=0)
        packed = candidate if len(candidate) < len(body) else None
    return StaticFile(
        body=body,
        content_type=content_type,
        relative_path=relative_path,
        is_spa_fallback=is_fallback,
        etag='"' + hashlib.sha256(body).hexdigest()[:32] + '"',
        gzipped=packed,
    )


def resolve_static_file(dist_root: Path, request_path: str) -> StaticFile:
    return _load(*locate_static_file(dist_root, request_path))


class StaticCache:
    """A bounded in-memory cache over `locate_static_file`.

    Without it the gateway re-reads, re-hashes and re-compresses the ~740 kB
    bundle from disk on every request. An entry is reused only while the file's
    (mtime, size) is unchanged, so a rebuilt frontend is picked up without a
    restart; the cache is capped by entry count AND total bytes (least recently
    used out first), so it cannot grow with what a client asks for -- the set of
    files under the dist root is finite, and the paths are validated before they
    ever reach it."""

    def __init__(self, *, max_entries: int = 512, max_bytes: int = 64 * 1024 * 1024) -> None:
        self.max_entries, self.max_bytes = max_entries, max_bytes
        self._entries: OrderedDict[str, tuple[tuple[int, int], StaticFile]] = OrderedDict()
        self._lock = threading.Lock()
        self.total_bytes = 0

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, dist_root: Path, request_path: str) -> StaticFile:
        target, relative, fallback = locate_static_file(dist_root, request_path)
        info = target.stat()
        signature = (info.st_mtime_ns, info.st_size)
        key = str(target)
        with self._lock:
            cached = self._entries.get(key)
            if cached is not None and cached[0] == signature:
                self._entries.move_to_end(key)
                return replace(cached[1], relative_path=relative, is_spa_fallback=fallback)
        loaded = _load(target, relative, fallback)
        size = len(loaded.body) + len(loaded.gzipped or b"")
        with self._lock:
            old = self._entries.pop(key, None)
            if old is not None:
                self.total_bytes -= len(old[1].body) + len(old[1].gzipped or b"")
            self._entries[key] = (signature, loaded)
            self.total_bytes += size
            while len(self._entries) > self.max_entries or self.total_bytes > self.max_bytes:
                if len(self._entries) <= 1:
                    break
                _, (_, evicted) = self._entries.popitem(last=False)
                self.total_bytes -= len(evicted.body) + len(evicted.gzipped or b"")
        return loaded
