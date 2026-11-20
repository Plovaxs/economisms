"""Integrity manifest for the committed data snapshots in `data_cache/`.

Every model result in this repository is only as trustworthy as the CSV it was
trained on, and a CSV is exactly the kind of file a review skims: a one-cell edit
in a 500-row snapshot is invisible in a diff. PR-197 found a real defect in one of
them (a look-ahead in the GDP column); the same channel would carry a deliberate
change. `data_cache/MANIFEST.sha256.json` records the SHA-256 and size of every
file in that directory, and every loader of a committed snapshot reads its bytes
through `read_verified_bytes` / `verified_dict_reader`, which refuse a file whose
digest differs. A snapshot can therefore change only together with a manifest
change, and the manifest change is the small, reviewable artefact that says so.

    python -m prometheus.data_ingestion.snapshot_integrity check
    python -m prometheus.data_ingestion.snapshot_integrity write   # after a deliberate refresh

What this is NOT: the manifest is not signed. Someone who can rewrite a CSV can
rewrite the manifest too. What it gives is (1) no silent drift or partial edit (a
bad merge, a refresh script, an editor that rewrote line endings), (2) a forced,
visible, deliberate step -- `write` -- whenever data changes, and (3) the bytes
that are parsed are exactly the bytes that were verified (one read; no
check-then-open gap). Authenticity against a malicious committer is the job of
required reviews and signed commits (SECURITY.md), not of this file. Files OUTSIDE
the committed directory (a caller's own CSV) are read unverified, because nothing
vouches for them.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

MANIFEST_FILENAME = "MANIFEST.sha256.json"
MANIFEST_FORMAT = "econosim-data-manifest/1"
COMMITTED_DATA_DIR = Path(__file__).resolve().parents[3] / "data_cache"
"""The directory whose files are verified on load."""
MAX_SNAPSHOT_BYTES = 64 * 1024 * 1024
"""A hard ceiling on one verified read: the real snapshots are under 0.5 MB."""
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_CSV_ROWS = 2_000_000
"""Rows accepted from one CSV (the real files have at most ~26,000)."""
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")
_REMEDIATION = (
    "If this change is deliberate, review the diff and run "
    "`python -m prometheus.data_ingestion.snapshot_integrity write`, "
    "then commit the snapshot and the manifest together."
)


class DataFileError(ValueError):
    """A data file cannot be trusted: it is altered or malformed. A `ValueError`, so
    existing `except ValueError` handlers keep working."""


class SnapshotIntegrityError(DataFileError):
    """A committed snapshot does not match its manifest entry (or has none)."""


class SnapshotParseError(DataFileError):
    """A data file is structurally malformed; the message names the row."""


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    sha256: str
    size: int


@dataclass(frozen=True, slots=True)
class IntegrityProblem:
    kind: str
    """`modified`, `missing` (listed but absent) or `unlisted` (present but not listed)."""
    name: str
    detail: str


def _read_capped(path: Path, limit: int) -> bytes:
    with path.open("rb") as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise SnapshotIntegrityError(f"{path.name} is larger than the {limit}-byte ceiling")
    return data


def _digest(data: bytes) -> ManifestEntry:
    return ManifestEntry(hashlib.sha256(data).hexdigest(), len(data))


def _check_name(name: object) -> str:
    """A manifest key must be a plain relative POSIX path: no traversal, no absolute
    path, no backslash, no empty or dot segment, no NUL."""
    if not isinstance(name, str) or not name:
        raise SnapshotIntegrityError("manifest file names must be non-empty strings")
    parts = name.split("/")
    if (
        name.startswith("/")
        or "\\" in name
        or "\x00" in name
        or any(part in ("", ".", "..") for part in parts)
        or PurePosixPath(name).as_posix() != name
    ):
        raise SnapshotIntegrityError(f"unsafe file name in manifest: {name!r}")
    return name


def compute_manifest(data_dir: Path) -> dict[str, ManifestEntry]:
    """Digest every regular file under `data_dir` (recursively, in sorted order),
    except the manifest itself. Symlinks and special files are refused."""
    entries: dict[str, ManifestEntry] = {}
    for current, dirnames, filenames in os.walk(data_dir, followlinks=False):
        dirnames.sort()
        base = Path(current)
        for directory in dirnames:
            if (base / directory).is_symlink():
                raise SnapshotIntegrityError(
                    f"{(base / directory).relative_to(data_dir).as_posix()}: "
                    "a data directory may not contain symlinks"
                )
        for name in sorted(filenames):
            path = base / name
            relative = path.relative_to(data_dir).as_posix()
            if relative == MANIFEST_FILENAME:
                continue
            if path.is_symlink() or not path.is_file():
                raise SnapshotIntegrityError(
                    f"{relative}: only regular files may live in a data directory"
                )
            entries[relative] = _digest(_read_capped(path, MAX_SNAPSHOT_BYTES))
    return dict(sorted(entries.items()))


def render_manifest(entries: dict[str, ManifestEntry]) -> str:
    payload = {
        "format": MANIFEST_FORMAT,
        "algorithm": "sha256",
        "files": {
            name: {"sha256": entry.sha256, "bytes": entry.size}
            for name, entry in sorted(entries.items())
        },
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    out: dict[str, object] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate key {key!r}")
        out[key] = value
    return out


def load_manifest(data_dir: Path) -> dict[str, ManifestEntry]:
    path = data_dir / MANIFEST_FILENAME
    if not path.is_file():
        raise SnapshotIntegrityError(f"{MANIFEST_FILENAME} is missing from {data_dir.name}/")
    raw = _read_capped(path, MAX_MANIFEST_BYTES)
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicate_keys)
    except ValueError as exc:
        raise SnapshotIntegrityError(f"{MANIFEST_FILENAME} is not valid JSON: {exc}") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("format") != MANIFEST_FORMAT
        or payload.get("algorithm") != "sha256"
        or not isinstance(payload.get("files"), dict)
    ):
        raise SnapshotIntegrityError(f"{MANIFEST_FILENAME} has an unexpected structure")
    entries: dict[str, ManifestEntry] = {}
    for name, raw_entry in payload["files"].items():
        _check_name(name)
        digest = raw_entry.get("sha256") if isinstance(raw_entry, dict) else None
        size = raw_entry.get("bytes") if isinstance(raw_entry, dict) else None
        if (
            not isinstance(digest, str)
            or _SHA256_HEX.fullmatch(digest) is None
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
        ):
            raise SnapshotIntegrityError(f"malformed manifest entry for {name!r}")
        entries[name] = ManifestEntry(digest, size)
    return entries


def verify_directory(data_dir: Path) -> list[IntegrityProblem]:
    """Compare the directory with its manifest; an empty list means they agree."""
    expected = load_manifest(data_dir)
    actual = compute_manifest(data_dir)
    problems: list[IntegrityProblem] = []
    for name, entry in expected.items():
        found = actual.get(name)
        if found is None:
            problems.append(
                IntegrityProblem("missing", name, "listed in the manifest, not on disk")
            )
        elif found != entry:
            problems.append(
                IntegrityProblem(
                    "modified",
                    name,
                    f"sha256 {found.sha256[:12]}... ({found.size} B) "
                    f"!= manifest {entry.sha256[:12]}... ({entry.size} B)",
                )
            )
    for name in actual:
        if name not in expected:
            problems.append(IntegrityProblem("unlisted", name, "on disk, not in the manifest"))
    return sorted(problems, key=lambda problem: (problem.name, problem.kind))


def _manifest_name(path: Path, data_dir: Path) -> str | None:
    """The manifest key for `path` if it lives inside `data_dir`, else None.

    A path that LOOKS inside the directory but resolves outside it (a symlink
    escape) is refused, so a link cannot launder an unverified file as a
    committed one."""
    real_root = data_dir.resolve()
    real_path = path.resolve()
    try:
        relative = real_path.relative_to(real_root)
    except ValueError:
        relative = None
    looks_inside = Path(os.path.abspath(path)).is_relative_to(Path(os.path.abspath(data_dir)))
    if relative is None:
        if looks_inside:
            raise SnapshotIntegrityError(
                f"{path.name} appears to be in {data_dir.name}/ but resolves outside it"
            )
        return None
    if path.is_symlink():
        raise SnapshotIntegrityError(f"{path.name} is a symlink inside {data_dir.name}/")
    return relative.as_posix()


def read_verified_bytes(path: Path, *, data_dir: Path | None = None) -> bytes:
    """The file's bytes, verified against the manifest when the file lives in the
    committed data directory (read once: the bytes returned are the bytes
    verified). A file elsewhere is returned unverified."""
    root = COMMITTED_DATA_DIR if data_dir is None else data_dir
    name = _manifest_name(path, root)
    data = _read_capped(path, MAX_SNAPSHOT_BYTES)
    if name is None:
        return data
    entry = load_manifest(root).get(name)
    if entry is None:
        raise SnapshotIntegrityError(f"{name} is not listed in {MANIFEST_FILENAME}. {_REMEDIATION}")
    found = _digest(data)
    if found != entry:
        raise SnapshotIntegrityError(
            f"{name} does not match {MANIFEST_FILENAME} "
            f"(sha256 {found.sha256[:12]}... vs {entry.sha256[:12]}...). {_REMEDIATION}"
        )
    return data


def read_verified_text(path: Path, *, data_dir: Path | None = None) -> str:
    data = read_verified_bytes(path, data_dir=data_dir)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SnapshotParseError(f"{path.name} is not valid UTF-8: {exc}") from exc


def iter_csv_rows(
    text: str, source: str, required: Sequence[str]
) -> Iterator[tuple[int, dict[str, str]]]:
    """Rows of a headed CSV as (line number, {required column: text}).

    The contract every reader of a data file shares: a missing required column, a
    row too short to hold one, a file longer than `MAX_CSV_ROWS` and any `csv.Error`
    (an oversized field, say) all surface as `SnapshotParseError` naming `source` --
    never as a bare `KeyError`, `TypeError` on a `None` cell, or `csv.Error`."""
    reader = csv.DictReader(io.StringIO(text, newline=""))
    try:
        fields = reader.fieldnames or ()
        missing = [name for name in required if name not in fields]
        if missing:
            raise SnapshotParseError(f"{source}: missing column(s) {missing}")
        for count, record in enumerate(reader, start=1):
            if count > MAX_CSV_ROWS:
                raise SnapshotParseError(f"{source}: more than {MAX_CSV_ROWS} rows")
            if any(record[name] is None for name in required):
                raise SnapshotParseError(f"{source}: line {reader.line_num}: short row")
            yield reader.line_num, {name: record[name] for name in required}
    except csv.Error as exc:
        raise SnapshotParseError(f"{source}: {exc}") from exc


def verified_dict_reader(
    path: Path, *, required: Sequence[str], data_dir: Path | None = None
) -> Iterator[dict[str, str]]:
    """Rows of the verified CSV at `path`, restricted to the `required` columns -- the
    one entry point the snapshot loaders use. Verification happens NOW (a tampered
    file fails at the call), the parsing as the rows are consumed."""
    text = read_verified_text(path, data_dir=data_dir)
    return (row for _, row in iter_csv_rows(text, path.name, required))


def _describe_changes(
    before: dict[str, ManifestEntry] | None, after: dict[str, ManifestEntry]
) -> list[str]:
    old = before or {}
    lines = [f"  + {name}" for name in after if name not in old]
    lines += [f"  ~ {name}" for name in after if name in old and old[name] != after[name]]
    lines += [f"  - {name}" for name in old if name not in after]
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="snapshot_integrity", description="Verify or regenerate the data_cache manifest."
    )
    parser.add_argument("command", choices=("check", "write"))
    parser.add_argument("--data-dir", type=Path, default=COMMITTED_DATA_DIR)
    args = parser.parse_args(argv)
    data_dir: Path = args.data_dir
    if args.command == "check":
        try:
            problems = verify_directory(data_dir)
        except DataFileError as exc:
            print(f"FAIL: {exc}", file=sys.stderr)
            return 1
        for problem in problems:
            print(f"{problem.kind.upper():9} {problem.name}: {problem.detail}", file=sys.stderr)
        if problems:
            print(_REMEDIATION, file=sys.stderr)
            return 1
        print(f"OK: {len(load_manifest(data_dir))} files match {MANIFEST_FILENAME}")
        return 0
    try:
        before: dict[str, ManifestEntry] | None = load_manifest(data_dir)
    except DataFileError:
        before = None
    after = compute_manifest(data_dir)
    (data_dir / MANIFEST_FILENAME).write_text(render_manifest(after), encoding="utf-8")
    changes = _describe_changes(before, after)
    print(f"wrote {MANIFEST_FILENAME}: {len(after)} files, {len(changes)} changed")
    for line in changes:
        print(line)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
