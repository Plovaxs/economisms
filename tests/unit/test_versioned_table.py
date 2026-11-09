import json
from pathlib import Path

import pytest

from prometheus.evidence.versioned_table import (
    VersionedTable,
    build_versioned_table,
    verify_versioned_table,
)

_REQUIREMENTS_SCRIPT = (
    Path(__file__).resolve().parents[2] / "src/prometheus/evidence/requirements.py"
)
_REGISTER_PATH = (
    Path(__file__).resolve().parents[2] / "docs/implementation/blueprint_register.json"
)


def test_versioned_table_rejects_an_empty_table_name() -> None:
    with pytest.raises(ValueError, match="table_name"):
        VersionedTable(
            table_name="", rows=(("a", "1"),), source_script_path="s.py",
            source_script_sha256="0" * 64, data_sha256="1" * 64,
        )


def test_versioned_table_rejects_empty_rows() -> None:
    with pytest.raises(ValueError, match="rows"):
        VersionedTable(
            table_name="t", rows=(), source_script_path="s.py",
            source_script_sha256="0" * 64, data_sha256="1" * 64,
        )


def test_versioned_table_rejects_an_empty_source_script_path() -> None:
    with pytest.raises(ValueError, match="source_script_path"):
        VersionedTable(
            table_name="t", rows=(("a", "1"),), source_script_path="",
            source_script_sha256="0" * 64, data_sha256="1" * 64,
        )


def test_versioned_table_rejects_a_malformed_script_hash() -> None:
    with pytest.raises(ValueError, match="source_script_sha256"):
        VersionedTable(
            table_name="t", rows=(("a", "1"),), source_script_path="s.py",
            source_script_sha256="not-a-hash", data_sha256="1" * 64,
        )


def test_versioned_table_rejects_a_malformed_data_hash() -> None:
    with pytest.raises(ValueError, match="data_sha256"):
        VersionedTable(
            table_name="t", rows=(("a", "1"),), source_script_path="s.py",
            source_script_sha256="0" * 64, data_sha256="not-a-hash",
        )


def _real_category_rows() -> list[tuple[str, str, str]]:
    """A real analytical table: the per-category blueprint coverage
    breakdown actually recorded in this repository's own real
    docs/implementation/blueprint_register.json, produced by the real
    evidence.requirements script."""
    register = json.loads(_REGISTER_PATH.read_text())
    counts: dict[str, list[int]] = {}
    for item in register["items"]:
        category = item["id"].split("-")[0]
        counts.setdefault(category, [0, 0])
        counts[category][1] += 1
        if item.get("repository_notes"):
            counts[category][0] += 1
    return sorted(
        (category, str(done), str(total)) for category, (done, total) in counts.items()
    )


def test_a_real_versioned_table_verifies_against_its_real_source_script() -> None:
    """Grounded against a REAL script in this repository
    (`evidence.requirements`, the actual script that produces
    `blueprint_register.json`) and REAL data (its own per-category
    coverage counts, read fresh from the real file on disk)."""
    rows = _real_category_rows()
    table = build_versioned_table(
        "blueprint_category_coverage", rows, _REQUIREMENTS_SCRIPT
    )
    assert table.table_name == "blueprint_category_coverage"
    assert len(table.rows) == len(rows)
    assert verify_versioned_table(table, _REQUIREMENTS_SCRIPT) is True


def test_verification_fails_when_the_source_script_is_tampered(tmp_path: Path) -> None:
    """The discriminating half: if the source script's content
    changes after the table was built, verification must genuinely
    detect it -- not report 'verified' unconditionally."""
    rows = _real_category_rows()
    table = build_versioned_table(
        "blueprint_category_coverage", rows, _REQUIREMENTS_SCRIPT
    )

    tampered_script = tmp_path / "requirements.py"
    tampered_script.write_text(_REQUIREMENTS_SCRIPT.read_text() + "\n# tampered\n")

    assert verify_versioned_table(table, tampered_script) is False


def test_verification_fails_when_the_recorded_data_no_longer_matches() -> None:
    """A table whose rows were edited after hashing no longer matches
    its own recorded data_sha256."""
    rows = _real_category_rows()
    table = build_versioned_table(
        "blueprint_category_coverage", rows, _REQUIREMENTS_SCRIPT
    )
    tampered_rows = tuple(table.rows[:-1]) + (("FAKE", "999", "999"),)
    tampered_table = VersionedTable(
        table_name=table.table_name,
        rows=tampered_rows,
        source_script_path=table.source_script_path,
        source_script_sha256=table.source_script_sha256,
        data_sha256=table.data_sha256,
    )
    assert verify_versioned_table(tampered_table, _REQUIREMENTS_SCRIPT) is False
