"""Versioned analytical tables with reproducible-script and
data-hash linkage (AUD-10: "Version final analytical paper figures
and tables"; acceptance criterion: "Figures link to reproducible
scripts and data hashes").

This repository has no plotting ("figure") infrastructure and no
paper-writing pipeline -- fabricating a chart-generation claim would
misrepresent what exists. "Tables" is the genuinely reachable half:
`build_versioned_table` packages a real analytical result table
together with the exact script path that produced its underlying
data and a content hash of both the table's own data and the
script's current source, reusing `experiments.manifest.compute_result_hash`
-- the same canonical-JSON hashing convention this project's other
reproducibility manifests already use, not a second one invented here.

`verify_versioned_table` is the item's own "link to ... data hashes,"
checked directly: it re-reads the script from disk and recomputes
both hashes, confirming they still match what the table recorded --
demonstrated in this module's tests against a REAL script in this
repository (`evidence.requirements`, the actual script that produces
`docs/implementation/blueprint_register.json`) and REAL data (the
blueprint's own per-category coverage counts), including a genuine
tamper-detection case where the script's content is confirmed to have
changed.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from prometheus.evidence.integrity import is_sha256
from prometheus.experiments.manifest import compute_result_hash


@dataclass(frozen=True, slots=True)
class VersionedTable:
    table_name: str
    rows: tuple[tuple[str, ...], ...]
    source_script_path: str
    source_script_sha256: str
    data_sha256: str

    def __post_init__(self) -> None:
        if not self.table_name:
            raise ValueError("table_name must not be empty")
        if not self.rows:
            raise ValueError("rows must not be empty")
        if not self.source_script_path:
            raise ValueError("source_script_path must not be empty")
        if not is_sha256(self.source_script_sha256):
            raise ValueError("source_script_sha256 must be a lowercase SHA-256 digest")
        if not is_sha256(self.data_sha256):
            raise ValueError("data_sha256 must be a lowercase SHA-256 digest")


def _data_hash(table_name: str, rows: Sequence[Sequence[str]]) -> str:
    return compute_result_hash({"table_name": table_name, "rows": [list(row) for row in rows]})


def build_versioned_table(
    table_name: str, rows: Sequence[Sequence[str]], source_script_path: Path
) -> VersionedTable:
    script_sha256 = hashlib.sha256(source_script_path.read_bytes()).hexdigest()
    return VersionedTable(
        table_name=table_name,
        rows=tuple(tuple(row) for row in rows),
        source_script_path=str(source_script_path),
        source_script_sha256=script_sha256,
        data_sha256=_data_hash(table_name, rows),
    )


def verify_versioned_table(table: VersionedTable, source_script_path: Path) -> bool:
    current_script_sha256 = hashlib.sha256(source_script_path.read_bytes()).hexdigest()
    current_data_sha256 = _data_hash(table.table_name, table.rows)
    return (
        current_script_sha256 == table.source_script_sha256
        and current_data_sha256 == table.data_sha256
    )
