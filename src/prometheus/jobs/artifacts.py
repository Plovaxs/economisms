"""Content-addressed, no-clobber artifact storage on a trusted local filesystem.

Files are verified on read. Atomic hard-link publication can leave an
unreferenced valid object after a database failure; it cannot publish a
partial JSON object as a successful result. This is not signed/WORM storage.
"""

from __future__ import annotations

import fcntl
import json
import os
import stat
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from prometheus.evidence.contracts import verified_payload
from prometheus.evidence.integrity import is_sha256, seal_evidence_bundle
from prometheus.evidence.jsonio import strict_json_loads
from prometheus.evidence.verify import audit_evidence_bundle


class ArtifactError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class StoredArtifact:
    content_sha256: str
    result_hash: str
    payload_kind: str
    size_bytes: int


class ArtifactStore:
    def __init__(
        self, root: Path, *, max_bytes: int = 134_217_728, max_total_bytes: int = 1_073_741_824
    ) -> None:
        if any(type(v) is not int or v < 1 for v in (max_bytes, max_total_bytes)):
            raise ValueError("max_bytes must be a positive integer")
        self.root = root.resolve()
        self.max_bytes, self.max_total_bytes = max_bytes, max_total_bytes
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)

    def _path(self, digest: str) -> Path:
        if not is_sha256(digest):
            raise ArtifactError("artifact identifier must be lowercase SHA-256")
        return self.root / digest[:2] / f"{digest}.json"

    def get(self, digest: str) -> dict[str, Any]:
        path = self._path(digest)
        if path.parent.resolve() != path.parent:
            raise ArtifactError("artifact directory must not be a symlink")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        try:
            fd = os.open(path, flags)
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > self.max_bytes:
                    raise ArtifactError("artifact is not a bounded regular file")
                content = stream.read(self.max_bytes + 1)
        except OSError as exc:
            raise ArtifactError("artifact object is unavailable") from exc
        if len(content) > self.max_bytes:
            raise ArtifactError("artifact exceeds configured byte budget")
        try:
            body = strict_json_loads(content.decode("utf-8"))
            if not isinstance(body, dict):
                raise ArtifactError("artifact must contain a JSON object")
            audit_evidence_bundle(body, expected_sha256=digest)
        except (ValueError, UnicodeError, TypeError) as exc:
            raise ArtifactError("stored artifact failed integrity/metadata verification") from exc
        return body

    def usage_bytes(self) -> int:
        """Total bytes currently stored, including any orphan staging
        files left behind by a crashed publisher (OPS-09: "track
        artifact storage utilization")."""
        return self._usage_bytes()

    def _usage_bytes(self) -> int:
        total = 0
        for prefix in self.root.iterdir():
            if prefix.name == "publish.lock":
                continue
            if (
                prefix.is_symlink()
                or not prefix.is_dir()
                or len(prefix.name) != 2
                or any(c not in "0123456789abcdef" for c in prefix.name)
            ):
                raise ArtifactError("unexpected artifact-store entry")
            for entry in prefix.iterdir():
                info = entry.lstat()
                if not stat.S_ISREG(info.st_mode):
                    raise ArtifactError("unexpected artifact object type")
                total += info.st_size  # Includes orphan staging files after a crashed publisher.
        return total

    def put(self, bundle: Mapping[str, Any]) -> StoredArtifact:
        body = seal_evidence_bundle(bundle)
        audit = audit_evidence_bundle(body)
        kind, _, result_hash = verified_payload(body, require_integrity=True)
        data = json.dumps(body, sort_keys=True, indent=2, allow_nan=False).encode("utf-8")
        if len(data) > self.max_bytes:
            raise ArtifactError("artifact exceeds configured byte budget")
        path = self._path(audit.content_sha256)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        lock_descriptor = os.open(self.root / "publish.lock", flags, 0o600)
        with os.fdopen(lock_descriptor, "rb+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            path.parent.mkdir(mode=0o700, exist_ok=True)
            if path.parent.resolve() != path.parent:
                raise ArtifactError("artifact directory must not be a symlink")
            if path.exists() or path.is_symlink():
                self.get(audit.content_sha256)
                return StoredArtifact(audit.content_sha256, result_hash, kind, path.stat().st_size)
            if self._usage_bytes() + len(data) > self.max_total_bytes:
                raise ArtifactError("artifact store exceeds total byte budget")
            temporary: str | None = None
            try:
                with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
                    temporary = stream.name
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                    os.fchmod(stream.fileno(), 0o444)
                os.link(temporary, path)
                for directory_path in (path.parent, self.root):
                    directory = os.open(directory_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                    try:
                        os.fsync(directory)
                    finally:
                        os.close(directory)
            finally:
                if temporary is not None:
                    Path(temporary).unlink(missing_ok=True)
        return StoredArtifact(audit.content_sha256, result_hash, kind, path.stat().st_size)
