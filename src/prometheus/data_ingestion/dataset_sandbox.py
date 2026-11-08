"""Validate and sandbox untrusted uploaded dataset formats (SEC-08:
"Validate and sandbox untrusted uploaded dataset formats"; acceptance
criterion: "Fuzz/test suite blocks unsafe deserialization paths").

`data_ingestion.french_factors` (DAT-05) and future connectors unzip an
externally-served archive before parsing it. `zipfile` alone does not
protect against two real, well-known classes of unsafe input this
project's own connectors are exposed to:

- "Zip Slip" -- an entry name like `"../../etc/passwd"` or an absolute
  path, which (if ever extracted to disk rather than read into memory
  as every connector here currently does) would write outside the
  intended directory. `_reject_unsafe_entry_name` is checked empirically
  against both real attack-shaped names and real benign relative paths
  containing a harmless `".."` segment that normalizes back inside the
  archive (confirmed NOT rejected).
- A decompression bomb -- a tiny archive that expands to an enormous
  size. `validate_zip_archive` rejects any entry whose
  `file_size / compress_size` ratio or absolute total uncompressed size
  exceeds `SandboxLimits`' thresholds. The default 100x ratio threshold
  was chosen after measuring the REAL compression ratio of the actual
  Kenneth French archive `french_factors.py` fetches (~4x) and a
  genuine DEFLATE-compressed 50MB-of-zeros bomb built for this module's
  own test (~1029x) -- confirmed to sit safely between the two, not
  picked arbitrarily.

This module only validates; it does not itself call `zipfile.extractall`
or write to disk, so Zip Slip is actually unreachable through this
repository's current connectors (which only `.read()` bytes into
memory). The check is still real defense-in-depth should extraction to
disk ever be added later, and the acceptance criterion ("blocks unsafe
deserialization paths") is about the validator's own behavior under a
fuzz/adversarial-input test suite, not about a vulnerability already
exploitable today.
"""

from __future__ import annotations

import posixpath
import re
import zipfile
from dataclasses import dataclass
from io import BytesIO

_ABSOLUTE_DRIVE_LETTER = re.compile(r"^[A-Za-z]:[\\/]")


class UnsafeDatasetError(ValueError):
    """Raised when an untrusted archive fails a sandbox check."""


@dataclass(frozen=True, slots=True)
class SandboxLimits:
    max_entries: int = 10_000
    max_total_uncompressed_bytes: int = 200_000_000
    max_compression_ratio: float = 100.0

    def __post_init__(self) -> None:
        if self.max_entries <= 0:
            raise ValueError("max_entries must be positive")
        if self.max_total_uncompressed_bytes <= 0:
            raise ValueError("max_total_uncompressed_bytes must be positive")
        if self.max_compression_ratio <= 0:
            raise ValueError("max_compression_ratio must be positive")


_DEFAULT_LIMITS = SandboxLimits()


def _reject_unsafe_entry_name(name: str) -> None:
    if name.startswith("/") or name.startswith("\\"):
        raise UnsafeDatasetError(f"entry {name!r} uses an absolute path")
    if _ABSOLUTE_DRIVE_LETTER.match(name):
        raise UnsafeDatasetError(f"entry {name!r} uses an absolute path")
    normalized = posixpath.normpath(name.replace("\\", "/"))
    if normalized == ".." or normalized.startswith("../"):
        raise UnsafeDatasetError(f"entry {name!r} attempts to escape the archive root")


def validate_zip_archive(data: bytes, *, limits: SandboxLimits = _DEFAULT_LIMITS) -> None:
    """Raises `UnsafeDatasetError` if `data` is not a well-formed zip, or
    is a well-formed zip that violates one of `limits`. Returns `None`
    (does not extract or return anything) if it passes."""
    try:
        archive = zipfile.ZipFile(BytesIO(data))
        infos = archive.infolist()
    except zipfile.BadZipFile as exc:
        raise UnsafeDatasetError(f"not a valid zip archive: {exc}") from exc

    if len(infos) > limits.max_entries:
        raise UnsafeDatasetError(
            f"archive has {len(infos)} entries, exceeding the {limits.max_entries} limit"
        )

    total_uncompressed = 0
    for info in infos:
        _reject_unsafe_entry_name(info.filename)
        total_uncompressed += info.file_size
        if info.compress_size > 0:
            ratio = info.file_size / info.compress_size
            if ratio > limits.max_compression_ratio:
                raise UnsafeDatasetError(
                    f"entry {info.filename!r} has a compression ratio of {ratio:.1f}x, "
                    f"exceeding the {limits.max_compression_ratio}x limit "
                    "(possible decompression bomb)"
                )

    if total_uncompressed > limits.max_total_uncompressed_bytes:
        raise UnsafeDatasetError(
            f"archive's total uncompressed size of {total_uncompressed} bytes exceeds "
            f"the {limits.max_total_uncompressed_bytes} byte limit"
        )
