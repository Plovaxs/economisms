"""Streamed AES-256-GCM recovery snapshots on a trusted local Linux filesystem.

Decrypt/authenticate completely into private staging before parsing metadata.
Only a verified new state root is published; copied worker leases are fenced.
This does not implement offsite transfer, vault custody or production RPO/RTO.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import math
import os
import re
import sqlite3
import stat
import struct
import sys
import tempfile
import time
from collections import Counter
from contextlib import closing
from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from prometheus.evidence.integrity import (
    INTEGRITY_KEY,
    artifact_content_hash,
    is_sha256,
    seal_evidence_bundle,
    verify_artifact_integrity,
)
from prometheus.evidence.jsonio import strict_json_loads
from prometheus.experiments.manifest import runtime_provenance
from prometheus.jobs.artifacts import ArtifactStore
from prometheus.jobs.store import STATUSES, JobStore, QueuePolicy
from prometheus.orchestration.recipes import ResourceLimits

MAGIC = b"PMTHSNAP\x01"
CHUNK = 1_048_576


class RecoveryError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RecoveryLimits:
    max_snapshot_bytes: int = 2_147_483_648
    max_database_bytes: int = 268_435_456
    max_manifest_bytes: int = 1_048_576
    max_files: int = 10_001
    max_jobs: int = 10_000
    max_events: int = 100_000
    operation_seconds: float = 60.0

    def __post_init__(self) -> None:
        for field in fields(self):
            if field.name == "operation_seconds":
                continue
            if type(getattr(self, field.name)) is not int or getattr(self, field.name) < 1:
                raise ValueError("recovery capacities must be positive integers")
        value = self.operation_seconds
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0 < value <= 3600
        ):
            raise ValueError("recovery deadline must be finite seconds in (0,3600]")


@dataclass(frozen=True, slots=True)
class RecoveryReceipt:
    snapshot_sha256: str
    manifest_sha256: str
    source_audit_head_sha256: str
    current_audit_head_sha256: str
    job_count: int
    artifact_count: int
    copied_leases_fenced: int
    verified: bool = True


def _tick(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise RecoveryError("recovery operation deadline expired")


def _regular(path: Path, limit: int, *, private: bool = False) -> BinaryIO:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    stream = os.fdopen(descriptor, "rb")
    info = os.fstat(descriptor)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_size > limit
        or (private and (info.st_mode & 0o077 or info.st_uid != os.getuid()))
    ):
        stream.close()
        raise RecoveryError("input must be a bounded regular file with required private ownership")
    return stream


def read_key(path: Path) -> bytes:
    try:
        with _regular(path, 32, private=True) as stream:
            key = stream.read(33)
        if len(key) != 32:
            raise RecoveryError("snapshot key must contain exactly 32 random binary bytes")
        return key
    except OSError as exc:
        raise RecoveryError("snapshot key is unavailable") from exc


def generate_key(path: Path) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(os.urandom(32))
        stream.flush()
        os.fsync(stream.fileno())
    _sync_directory(path.parent)


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _file_digest(path: Path, limit: int, deadline: float) -> tuple[int, str]:
    size, hasher = 0, hashlib.sha256()
    with _regular(path, limit) as stream:
        for chunk in iter(lambda: stream.read(CHUNK), b""):
            _tick(deadline)
            size += len(chunk)
            if size > limit:
                raise RecoveryError("file grew beyond recovery byte budget")
            hasher.update(chunk)
    return size, hasher.hexdigest()


def _inspect_database(
    path: Path, limits: RecoveryLimits
) -> tuple[JobStore, list[dict[str, Any]], int]:
    with _regular(path, limits.max_database_bytes):
        pass
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=0.25)) as connection:
        connection.row_factory = sqlite3.Row
        if (
            connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
            or connection.execute("PRAGMA foreign_key_check").fetchone() is not None
            or connection.execute("PRAGMA user_version").fetchone()[0] != 1
            or connection.execute("PRAGMA journal_mode").fetchone()[0] != "delete"
        ):
            raise RecoveryError("snapshot database failed schema/integrity checks")
        counts = [
            connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
            for table in ("jobs", "events")
        ]
        if counts[0] > limits.max_jobs or counts[1] > limits.max_events:
            raise RecoveryError("snapshot state cardinality exceeds recovery budget")
        setting = connection.execute("SELECT value FROM settings WHERE key='policy'").fetchone()
        if setting is None:
            raise RecoveryError("snapshot queue policy is absent")
        policy = strict_json_loads(setting[0])
        if not isinstance(policy, dict) or set(policy) != {"queue", "resources"}:
            raise RecoveryError("invalid persisted queue policy")
        if set(policy["queue"]) != {field.name for field in fields(QueuePolicy)} or set(
            policy["resources"]
        ) != {field.name for field in fields(ResourceLimits)}:
            raise RecoveryError("incomplete persisted queue policy")
        queue, resources = QueuePolicy(**policy["queue"]), ResourceLimits(**policy["resources"])
        rows = [dict(row) for row in connection.execute("SELECT * FROM jobs ORDER BY job_id")]
    store = JobStore(path, policy=queue, limits=resources)
    store.verify_audit_chain()
    return store, rows, counts[1]


def _validate_objects(
    root: Path, store: JobStore, rows: list[dict[str, Any]], deadline: float
) -> set[str]:
    objects = ArtifactStore(
        root / "artifacts",
        max_bytes=store.policy.max_artifact_bytes,
        max_total_bytes=store.policy.max_store_bytes,
    )
    referenced: set[str] = set()
    total_bytes = 0
    for row in rows:
        _tick(deadline)
        digest = row["artifact_sha256"]
        if digest is None:
            continue
        artifact = objects.get(digest)
        context = artifact.get("job_context", {})
        if (
            any(
                context.get(key) != row[column]
                for key, column in (
                    ("job_id", "job_id"),
                    ("trace_id", "trace_id"),
                    ("kind", "kind"),
                    ("recipe_sha256", "recipe_sha256"),
                    ("attempt", "attempts"),
                )
            )
            or artifact["run_manifest"]["result_hash"] != row["result_hash"]
        ):
            raise RecoveryError("snapshot object differs from its job association")
        if digest not in referenced:
            total_bytes += objects._path(digest).stat().st_size
            if total_bytes > store.policy.max_store_bytes:
                raise RecoveryError("referenced artifacts exceed persisted storage budget")
            referenced.add(digest)
    return referenced


def _copy_database(
    source: Path, destination: Path, limits: RecoveryLimits, deadline: float
) -> None:
    with _regular(source, limits.max_database_bytes):
        pass
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=0.25)) as original:
        page_size = original.execute("PRAGMA page_size").fetchone()[0]
        with closing(sqlite3.connect(destination)) as copy:

            def progress(status: int, remaining: int, total: int) -> None:
                _tick(deadline)
                if total * page_size > limits.max_database_bytes:
                    raise RecoveryError("database grew beyond snapshot budget")

            original.backup(copy, pages=256, progress=progress, sleep=0.01)
    destination.chmod(0o600)


def _manifest_validate(raw: Any, limits: RecoveryLimits) -> dict[str, Any]:
    required = {
        "schema_version",
        "created_at",
        "runtime",
        "queue_policy",
        "resource_limits",
        "audit_head_sha256",
        "job_count",
        "event_count",
        "status_counts",
        "files",
        INTEGRITY_KEY,
    }
    if not isinstance(raw, dict) or set(raw) != required:
        raise RecoveryError("snapshot manifest has invalid fields")
    verify_artifact_integrity(raw, require=True)
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        raise RecoveryError("unsupported snapshot manifest version")
    if (
        not is_sha256(raw["audit_head_sha256"])
        or not isinstance(raw["created_at"], str)
        or (datetime.fromisoformat(raw["created_at"]).tzinfo is None)
    ):
        raise RecoveryError("invalid snapshot identity/time")
    for key, maximum in (("job_count", limits.max_jobs), ("event_count", limits.max_events)):
        if type(raw[key]) is not int or not 0 <= raw[key] <= maximum:
            raise RecoveryError("snapshot state exceeds cardinality budget")
    if (
        not isinstance(raw["queue_policy"], dict)
        or set(raw["queue_policy"]) != {field.name for field in fields(QueuePolicy)}
        or not isinstance(raw["resource_limits"], dict)
        or set(raw["resource_limits"]) != {field.name for field in fields(ResourceLimits)}
    ):
        raise RecoveryError("snapshot policy fields are incomplete")
    queue = QueuePolicy(**raw["queue_policy"])
    ResourceLimits(**raw["resource_limits"])
    runtime = raw["runtime"]
    if (
        not isinstance(runtime, dict)
        or set(runtime) != {"python", "platform", "dependencies", "source_sha256"}
        or not is_sha256(runtime["source_sha256"])
        or any(
            not isinstance(runtime[key], str) or not runtime[key].strip()
            for key in ("python", "platform")
        )
        or not isinstance(runtime["dependencies"], dict)
        or not runtime["dependencies"]
        or any(
            not isinstance(key, str)
            or not key.strip()
            or not isinstance(value, str)
            or not value.strip()
            for key, value in runtime["dependencies"].items()
        )
    ):
        raise RecoveryError("snapshot runtime provenance is malformed")
    counts = raw["status_counts"]
    if (
        not isinstance(counts, dict)
        or set(counts) - STATUSES
        or any(type(value) is not int or value < 0 for value in counts.values())
        or sum(counts.values()) != raw["job_count"]
    ):
        raise RecoveryError("invalid snapshot status summary")
    files = raw["files"]
    if not isinstance(files, list) or not 1 <= len(files) <= limits.max_files:
        raise RecoveryError("snapshot file count exceeds budget")
    names, total = [], 0
    for item in files:
        if not isinstance(item, dict) or set(item) != {"path", "size_bytes", "sha256"}:
            raise RecoveryError("invalid snapshot file declaration")
        name = item["path"]
        if not isinstance(name, str) or (
            name != "jobs.sqlite3"
            and re.fullmatch(r"artifacts/([a-f0-9]{2})/([a-f0-9]{64})\.json", name) is None
        ):
            raise RecoveryError("snapshot path is not allowlisted")
        if name != "jobs.sqlite3" and name.split("/")[1] != name.split("/")[2][:2]:
            raise RecoveryError("snapshot artifact prefix differs from content identity")
        maximum = (
            limits.max_database_bytes
            if name == "jobs.sqlite3"
            else min(queue.max_artifact_bytes, limits.max_snapshot_bytes)
        )
        if (
            type(item["size_bytes"]) is not int
            or not 0 < item["size_bytes"] <= maximum
            or not is_sha256(item["sha256"])
        ):
            raise RecoveryError("invalid snapshot file size/hash")
        names.append(name)
        total += item["size_bytes"]
    if (
        names[0] != "jobs.sqlite3"
        or names[1:] != sorted(names[1:])
        or len(names) != len(set(names))
        or total > limits.max_snapshot_bytes
    ):
        raise RecoveryError("snapshot file ordering/size is invalid")
    return raw


def _pack(
    root: Path,
    manifest: dict[str, Any],
    output: Path,
    key: bytes,
    limits: RecoveryLimits,
    deadline: float,
) -> str:
    encoded = json.dumps(manifest, sort_keys=True, allow_nan=False).encode("utf-8")
    if len(encoded) > limits.max_manifest_bytes:
        raise RecoveryError("snapshot manifest exceeds byte budget")
    expected_bytes = (
        len(MAGIC)
        + 12
        + 4
        + len(encoded)
        + 16
        + sum(item["size_bytes"] for item in manifest["files"])
    )
    if expected_bytes > limits.max_snapshot_bytes:
        raise RecoveryError("encrypted snapshot exceeds byte budget")
    header = MAGIC + os.urandom(12)
    encryptor = Cipher(algorithms.AES(key), modes.GCM(header[-12:])).encryptor()
    encryptor.authenticate_additional_data(header)
    with output.open("xb") as stream:
        stream.write(header)
        stream.write(encryptor.update(struct.pack(">I", len(encoded)) + encoded))
        for item in manifest["files"]:
            hasher, size = hashlib.sha256(), 0
            with _regular(root / item["path"], item["size_bytes"]) as source:
                for chunk in iter(lambda: source.read(CHUNK), b""):
                    _tick(deadline)
                    size += len(chunk)
                    hasher.update(chunk)
                    stream.write(encryptor.update(chunk))
            if size != item["size_bytes"] or hasher.hexdigest() != item["sha256"]:
                raise RecoveryError("snapshot input changed while encrypting")
        stream.write(encryptor.finalize())
        stream.write(encryptor.tag)
        stream.flush()
        os.fsync(stream.fileno())
    output.chmod(0o600)
    return _file_digest(output, limits.max_snapshot_bytes, deadline)[1]


def create_snapshot(
    root: Path, output: Path, *, key_file: Path, limits: RecoveryLimits | None = None
) -> RecoveryReceipt:
    limits, root, output = limits or RecoveryLimits(), root.resolve(), output.absolute()
    deadline = time.monotonic() + limits.operation_seconds
    key = read_key(key_file)
    if output.exists() or output.is_symlink():
        raise RecoveryError("snapshot destination already exists")
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".prometheus-snapshot-", dir=output.parent
    ) as temporary:
        staging = Path(temporary)
        if (root / "artifacts").is_symlink() or not (root / "artifacts").is_dir():
            raise RecoveryError("source artifact directory is unavailable or a symlink")
        _copy_database(root / "jobs.sqlite3", staging / "jobs.sqlite3", limits, deadline)
        store, rows, event_count = _inspect_database(staging / "jobs.sqlite3", limits)
        source_objects = ArtifactStore(
            root / "artifacts",
            max_bytes=store.policy.max_artifact_bytes,
            max_total_bytes=store.policy.max_store_bytes,
        )
        referenced = _validate_objects(root, store, rows, deadline)
        if len(referenced) + 1 > limits.max_files:
            raise RecoveryError("referenced object count exceeds recovery budget")
        for digest in sorted(referenced):
            _tick(deadline)
            source_objects.get(digest)
            target = staging / "artifacts" / digest[:2] / (digest + ".json")
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with _regular(source_objects._path(digest), store.policy.max_artifact_bytes) as source:
                with target.open("xb") as destination:
                    copied = 0
                    for chunk in iter(lambda: source.read(CHUNK), b""):
                        _tick(deadline)
                        copied += len(chunk)
                        if copied > store.policy.max_artifact_bytes:
                            raise RecoveryError("object grew beyond snapshot byte budget")
                        destination.write(chunk)
            target.chmod(0o600)
        _validate_objects(staging, store, rows, deadline)
        paths = ["jobs.sqlite3"] + [
            "artifacts/" + digest[:2] + "/" + digest + ".json" for digest in sorted(referenced)
        ]
        files = []
        for name in paths:
            size, digest = _file_digest(staging / name, limits.max_snapshot_bytes, deadline)
            files.append({"path": name, "size_bytes": size, "sha256": digest})
        manifest = seal_evidence_bundle(
            {
                "schema_version": 1,
                "created_at": datetime.now(UTC).isoformat(),
                "runtime": runtime_provenance(),
                "queue_policy": asdict(store.policy),
                "resource_limits": asdict(store.limits),
                "audit_head_sha256": store.verify_audit_chain(),
                "job_count": len(rows),
                "event_count": event_count,
                "status_counts": dict(Counter(row["status"] for row in rows)),
                "files": files,
            }
        )
        _manifest_validate(manifest, limits)
        encrypted = staging / "snapshot.encrypted"
        digest = _pack(staging, manifest, encrypted, key, limits, deadline)
        os.link(
            encrypted, output
        )  # Atomic no-clobber publication; never replaces a previous snapshot.
        _sync_directory(output.parent)
        return RecoveryReceipt(
            digest,
            artifact_content_hash(manifest),
            manifest["audit_head_sha256"],
            manifest["audit_head_sha256"],
            len(rows),
            len(referenced),
            0,
        )


def _unpack(
    snapshot: Path,
    staging: Path,
    key: bytes,
    limits: RecoveryLimits,
    deadline: float,
    expected_sha256: str | None,
) -> tuple[dict[str, Any], str]:
    if expected_sha256 is not None and not is_sha256(expected_sha256):
        raise RecoveryError("snapshot differs from supplied SHA-256 checkpoint")
    plaintext = staging / "authenticated.payload"
    with _regular(snapshot, limits.max_snapshot_bytes) as source:
        size = os.fstat(source.fileno()).st_size
        if size < len(MAGIC) + 12 + 16 + 4:
            raise RecoveryError("encrypted snapshot is truncated")
        header = source.read(len(MAGIC) + 12)
        if header[: len(MAGIC)] != MAGIC:
            raise RecoveryError("unsupported encrypted snapshot format")
        source.seek(size - 16)
        tag = source.read(16)
        source.seek(len(header))
        decryptor = Cipher(algorithms.AES(key), modes.GCM(header[-12:], tag)).decryptor()
        decryptor.authenticate_additional_data(header)
        hasher = hashlib.sha256(header)
        remaining = size - len(header) - 16
        with plaintext.open("xb") as destination:
            while remaining:
                _tick(deadline)
                chunk = source.read(min(CHUNK, remaining))
                if not chunk:
                    raise RecoveryError("encrypted snapshot is truncated")
                remaining -= len(chunk)
                hasher.update(chunk)
                destination.write(decryptor.update(chunk))
            try:
                destination.write(decryptor.finalize())
            except InvalidTag as exc:
                raise RecoveryError("snapshot authentication failed") from exc
        hasher.update(tag)
        if os.fstat(source.fileno()).st_size != size:
            raise RecoveryError("encrypted snapshot size changed during verification")
        digest = hasher.hexdigest()
        if expected_sha256 is not None and digest != expected_sha256:
            raise RecoveryError("snapshot differs from supplied SHA-256 checkpoint")
    # Authenticate the entire payload before parsing names/JSON or opening a copied database.
    with plaintext.open("rb") as stream:
        length_bytes = stream.read(4)
        if len(length_bytes) != 4:
            raise RecoveryError("snapshot manifest is truncated")
        length = struct.unpack(">I", length_bytes)[0]
        if not 1 <= length <= limits.max_manifest_bytes:
            raise RecoveryError("snapshot manifest exceeds byte budget")
        manifest = _manifest_validate(
            strict_json_loads(stream.read(length).decode("utf-8")), limits
        )
        for item in manifest["files"]:
            target = staging / item["path"]
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            hasher, remaining = hashlib.sha256(), item["size_bytes"]
            with target.open("xb") as destination:
                while remaining:
                    _tick(deadline)
                    chunk = stream.read(min(CHUNK, remaining))
                    if not chunk:
                        raise RecoveryError("snapshot file content is truncated")
                    remaining -= len(chunk)
                    hasher.update(chunk)
                    destination.write(chunk)
                destination.flush()
                os.fsync(destination.fileno())
            target.chmod(0o600)
            if hasher.hexdigest() != item["sha256"]:
                raise RecoveryError("snapshot file checksum differs")
        if stream.read(1):
            raise RecoveryError("snapshot contains undeclared trailing content")
    plaintext.unlink()
    return manifest, digest


def _verified_staging(
    staging: Path, manifest: dict[str, Any], limits: RecoveryLimits, deadline: float
) -> tuple[JobStore, int]:
    store, rows, events = _inspect_database(staging / "jobs.sqlite3", limits)
    if (
        asdict(store.policy) != manifest["queue_policy"]
        or asdict(store.limits) != manifest["resource_limits"]
        or len(rows) != manifest["job_count"]
        or events != manifest["event_count"]
        or dict(Counter(row["status"] for row in rows)) != manifest["status_counts"]
    ):
        raise RecoveryError("snapshot manifest differs from its database projection")
    store.verify_audit_chain(expected_head=manifest["audit_head_sha256"])
    referenced = _validate_objects(staging, store, rows, deadline)
    declared = {item["path"].split("/")[-1][:-5] for item in manifest["files"][1:]}
    if declared != referenced:
        raise RecoveryError("snapshot objects differ from job references")
    return store, len(referenced)


def _publish_directory(source: Path, destination: Path) -> None:
    if sys.platform != "linux":
        raise RecoveryError("atomic no-clobber restore requires Linux renameat2")
    library = ctypes.CDLL(None, use_errno=True)
    function = getattr(library, "renameat2", None)
    if function is None:
        raise RecoveryError("atomic no-clobber directory publication is unavailable")
    function.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    function.restype = ctypes.c_int
    if function(-100, os.fsencode(source), -100, os.fsencode(destination), 1) != 0:
        raise RecoveryError("restore destination exists or atomic publication failed")
    _sync_directory(destination.parent)


def restore_snapshot(
    snapshot: Path,
    destination: Path | None,
    *,
    key_file: Path,
    expected_sha256: str | None = None,
    limits: RecoveryLimits | None = None,
) -> RecoveryReceipt:
    limits = limits or RecoveryLimits()
    deadline = time.monotonic() + limits.operation_seconds
    key = read_key(key_file)
    parent = None
    if destination is not None:
        destination = destination.absolute()
        if destination.exists() or destination.is_symlink():
            raise RecoveryError("restore requires a new state directory")
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        parent = destination.parent
    try:
        with tempfile.TemporaryDirectory(prefix=".prometheus-restore-", dir=parent) as temporary:
            staging = Path(temporary) / "state"
            staging.mkdir(mode=0o700)
            manifest, digest = _unpack(snapshot, staging, key, limits, deadline, expected_sha256)
            store, object_count = _verified_staging(staging, manifest, limits, deadline)
            fenced = 0
            if destination is not None:
                fenced = store.recover_after_restore(
                    snapshot_sha256=digest, expected_head=manifest["audit_head_sha256"]
                )
            current_head = store.verify_audit_chain()
            if destination is not None:
                # Restored immutable objects become readonly; queue metadata stays private/writable.
                for item in manifest["files"][1:]:
                    (staging / item["path"]).chmod(0o400)
                for directory in sorted(
                    (p for p in staging.rglob("*") if p.is_dir()),
                    key=lambda p: len(p.parts),
                    reverse=True,
                ):
                    _sync_directory(directory)
                with (staging / "jobs.sqlite3").open("rb") as stream:
                    os.fsync(stream.fileno())
                _sync_directory(staging)
                _tick(deadline)
                _publish_directory(staging, destination)
            return RecoveryReceipt(
                digest,
                artifact_content_hash(manifest),
                manifest["audit_head_sha256"],
                current_head,
                manifest["job_count"],
                object_count,
                fenced,
            )
    except RecoveryError:
        raise
    except (
        ValueError,
        TypeError,
        KeyError,
        OSError,
        sqlite3.Error,
        UnicodeError,
        RecursionError,
    ) as exc:
        raise RecoveryError(
            "snapshot failed authenticated state verification or publication"
        ) from exc
