"""PR-201: the committed data snapshots are verified byte-for-byte on load.

Known-answer tests for the manifest, adversarial tests for what a hostile or
careless change could try (a tampered file, a planted file, a symlink, a poisoned
manifest), and one end-to-end test that every loader of a committed snapshot
actually refuses an altered file.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from prometheus.data_ingestion import snapshot_integrity as integrity
from prometheus.data_ingestion.french_factors import load_cached_ff3_snapshot
from prometheus.data_ingestion.kaggle_cpi_index import load_cpi_index as load_cpi_index_levels
from prometheus.data_ingestion.kaggle_fed_policy import load_fed_policy_months
from prometheus.data_ingestion.kaggle_macro import load_kaggle_us_macro_observations
from prometheus.data_ingestion.kaggle_macro_extended import load_extended_macro_observations
from prometheus.data_ingestion.kaggle_sp500 import load_daily_closes, load_sp500_closes
from prometheus.data_ingestion.kaggle_term_spread import load_term_spread_observations
from prometheus.data_ingestion.snapshot_integrity import (
    COMMITTED_DATA_DIR,
    MANIFEST_FILENAME,
    DataFileError,
    SnapshotIntegrityError,
    SnapshotParseError,
    compute_manifest,
    iter_csv_rows,
    load_manifest,
    main,
    read_verified_bytes,
    read_verified_text,
    render_manifest,
    verified_dict_reader,
    verify_directory,
)
from prometheus.data_ingestion.treasury_yield_spread import (
    load_treasury_yield_spread_observations,
)
from prometheus.inflationcast.data import load_cpi_observations

REPO_ROOT = Path(__file__).resolve().parents[2]


def _data_dir(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    (root / "sub").mkdir(parents=True)
    (root / "a.csv").write_text("date,x\n202001,1.5\n")
    (root / "sub" / "b.json").write_text('{"k": 1}\n')
    (root / MANIFEST_FILENAME).write_text(render_manifest(compute_manifest(root)))
    return root


# ------------------------------------------------------------------ the manifest itself


def test_the_manifest_lists_every_regular_file_with_its_real_digest(tmp_path: Path) -> None:
    root = _data_dir(tmp_path)
    entries = compute_manifest(root)
    assert list(entries) == ["a.csv", "sub/b.json"], "sorted, recursive, manifest excluded"
    raw = (root / "a.csv").read_bytes()
    assert entries["a.csv"].sha256 == hashlib.sha256(raw).hexdigest()
    assert entries["a.csv"].size == len(raw)


def test_rendering_is_deterministic_and_round_trips(tmp_path: Path) -> None:
    root = _data_dir(tmp_path)
    entries = compute_manifest(root)
    assert render_manifest(entries) == render_manifest(dict(reversed(list(entries.items()))))
    assert load_manifest(root) == entries
    assert render_manifest(entries).endswith("\n")


def test_a_clean_directory_has_no_problems(tmp_path: Path) -> None:
    assert verify_directory(_data_dir(tmp_path)) == []


def test_modified_missing_and_unlisted_files_are_each_named(tmp_path: Path) -> None:
    root = _data_dir(tmp_path)
    (root / "a.csv").write_text("date,x\n202001,1.6\n")  # one digit changed
    (root / "sub" / "b.json").unlink()
    (root / "planted.csv").write_text("date,x\n")
    problems = {(p.kind, p.name) for p in verify_directory(root)}
    assert problems == {
        ("modified", "a.csv"),
        ("missing", "sub/b.json"),
        ("unlisted", "planted.csv"),
    }


def test_a_same_length_edit_is_still_caught(tmp_path: Path) -> None:
    """The size is not the check: replacing one character keeps the length."""
    root = _data_dir(tmp_path)
    original = (root / "a.csv").read_bytes()
    (root / "a.csv").write_bytes(original.replace(b"1.5", b"9.5"))
    assert len((root / "a.csv").read_bytes()) == len(original)
    assert [p.kind for p in verify_directory(root)] == ["modified"]


def test_symlinks_cannot_be_part_of_a_data_directory(tmp_path: Path) -> None:
    root = _data_dir(tmp_path)
    (root / "link.csv").symlink_to(root / "a.csv")
    with pytest.raises(SnapshotIntegrityError, match="only regular files"):
        compute_manifest(root)
    (root / "link.csv").unlink()
    (root / "dirlink").symlink_to(root / "sub", target_is_directory=True)
    with pytest.raises(SnapshotIntegrityError, match="symlinks"):
        compute_manifest(root)


# ------------------------------------------------------------------ a poisoned manifest


@pytest.mark.parametrize(
    "name",
    ["../x.csv", "/etc/passwd", "a//b.csv", "a/./b.csv", "a\\b.csv", "", "a/../b.csv", "a\x00.csv"],
)
def test_manifest_keys_must_be_plain_relative_paths(tmp_path: Path, name: str) -> None:
    root = _data_dir(tmp_path)
    digest = "0" * 64
    payload = {
        "format": integrity.MANIFEST_FORMAT,
        "algorithm": "sha256",
        "files": {name: {"sha256": digest, "bytes": 1}},
    }
    (root / MANIFEST_FILENAME).write_text(json.dumps(payload))
    with pytest.raises(SnapshotIntegrityError):
        load_manifest(root)


def _write_manifest(root: Path, payload: Any) -> None:
    (root / MANIFEST_FILENAME).write_text(
        payload if isinstance(payload, str) else json.dumps(payload)
    )


_GOOD_ENTRY = {"sha256": "a" * 64, "bytes": 3}


@pytest.mark.parametrize(
    "payload",
    [
        "not json at all",
        "[]",
        {"format": "other/1", "algorithm": "sha256", "files": {}},
        {"format": integrity.MANIFEST_FORMAT, "algorithm": "md5", "files": {}},
        {"format": integrity.MANIFEST_FORMAT, "algorithm": "sha256", "files": []},
        {"format": integrity.MANIFEST_FORMAT, "algorithm": "sha256", "files": {"a": "x"}},
        {
            "format": integrity.MANIFEST_FORMAT,
            "algorithm": "sha256",
            "files": {"a.csv": {"sha256": "A" * 64, "bytes": 3}},
        },
        {
            "format": integrity.MANIFEST_FORMAT,
            "algorithm": "sha256",
            "files": {"a.csv": {"sha256": "a" * 63, "bytes": 3}},
        },
        {
            "format": integrity.MANIFEST_FORMAT,
            "algorithm": "sha256",
            "files": {"a.csv": {"sha256": "a" * 64, "bytes": -1}},
        },
        {
            "format": integrity.MANIFEST_FORMAT,
            "algorithm": "sha256",
            "files": {"a.csv": {"sha256": "a" * 64, "bytes": True}},
        },
    ],
)
def test_malformed_manifests_are_refused(tmp_path: Path, payload: Any) -> None:
    root = _data_dir(tmp_path)
    _write_manifest(root, payload)
    with pytest.raises(SnapshotIntegrityError):
        load_manifest(root)


def test_a_manifest_with_a_duplicate_key_is_refused(tmp_path: Path) -> None:
    """`json.loads` keeps the LAST duplicate silently; a manifest must not hide a
    second, contradictory entry for the same file."""
    root = _data_dir(tmp_path)
    entry = json.dumps(_GOOD_ENTRY)
    _write_manifest(
        root,
        '{"format": "' + integrity.MANIFEST_FORMAT + '", "algorithm": "sha256", '
        f'"files": {{"a.csv": {entry}, "a.csv": {entry}}}}}',
    )
    with pytest.raises(SnapshotIntegrityError, match="duplicate key"):
        load_manifest(root)


def test_a_missing_manifest_fails_closed(tmp_path: Path) -> None:
    root = _data_dir(tmp_path)
    (root / MANIFEST_FILENAME).unlink()
    with pytest.raises(SnapshotIntegrityError, match="missing"):
        read_verified_bytes(root / "a.csv", data_dir=root)


# ------------------------------------------------------------------ verified reads


def test_a_verified_read_returns_exactly_the_bytes_on_disk(tmp_path: Path) -> None:
    root = _data_dir(tmp_path)
    assert read_verified_bytes(root / "a.csv", data_dir=root) == (root / "a.csv").read_bytes()
    assert read_verified_text(root / "sub" / "b.json", data_dir=root) == '{"k": 1}\n'


def test_a_tampered_file_is_refused_with_the_way_forward(tmp_path: Path) -> None:
    root = _data_dir(tmp_path)
    (root / "a.csv").write_text("date,x\n202001,99\n")
    with pytest.raises(SnapshotIntegrityError, match="does not match") as caught:
        read_verified_bytes(root / "a.csv", data_dir=root)
    assert "snapshot_integrity write" in str(caught.value)


def test_a_file_the_manifest_does_not_list_is_refused_inside_the_directory(tmp_path: Path) -> None:
    root = _data_dir(tmp_path)
    (root / "planted.csv").write_text("date,x\n")
    with pytest.raises(SnapshotIntegrityError, match="not listed"):
        read_verified_bytes(root / "planted.csv", data_dir=root)


def test_a_file_outside_the_directory_is_read_without_verification(tmp_path: Path) -> None:
    root = _data_dir(tmp_path)
    elsewhere = tmp_path / "mine.csv"
    elsewhere.write_text("anything\n")
    assert read_verified_bytes(elsewhere, data_dir=root) == b"anything\n"


def test_a_symlink_that_escapes_the_directory_is_refused(tmp_path: Path) -> None:
    root = _data_dir(tmp_path)
    outside = tmp_path / "outside.csv"
    outside.write_text("date,x\n")
    (root / "link.csv").symlink_to(outside)
    with pytest.raises(SnapshotIntegrityError, match="resolves outside"):
        read_verified_bytes(root / "link.csv", data_dir=root)


def test_a_symlink_inside_the_directory_is_refused(tmp_path: Path) -> None:
    root = _data_dir(tmp_path)
    (root / "alias.csv").symlink_to(root / "a.csv")
    with pytest.raises(SnapshotIntegrityError, match="symlink"):
        read_verified_bytes(root / "alias.csv", data_dir=root)


def test_the_read_ceiling_applies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _data_dir(tmp_path)
    monkeypatch.setattr(integrity, "MAX_SNAPSHOT_BYTES", 4)
    with pytest.raises(SnapshotIntegrityError, match="ceiling"):
        read_verified_bytes(root / "a.csv", data_dir=root)


def test_text_must_be_valid_utf8(tmp_path: Path) -> None:
    elsewhere = tmp_path / "latin.csv"
    elsewhere.write_bytes(b"date,x\n\xff\xfe,1\n")
    with pytest.raises(SnapshotParseError, match="UTF-8"):
        read_verified_text(elsewhere, data_dir=tmp_path / "nowhere")


def test_the_dict_reader_parses_what_was_verified(tmp_path: Path) -> None:
    root = _data_dir(tmp_path)
    rows = list(verified_dict_reader(root / "a.csv", required=("date", "x"), data_dir=root))
    assert rows == [{"date": "202001", "x": "1.5"}]


def test_the_dict_reader_verifies_at_the_call_not_at_the_first_row(tmp_path: Path) -> None:
    root = _data_dir(tmp_path)
    (root / "a.csv").write_text("date,x\n202001,9.9\n")
    with pytest.raises(SnapshotIntegrityError):
        verified_dict_reader(root / "a.csv", required=("date",), data_dir=root)  # never iterated


def test_csv_rows_report_missing_columns_short_rows_and_oversized_fields_as_parse_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(SnapshotParseError, match=r"missing column\(s\) \['y'\]"):
        list(iter_csv_rows("date,x\n1,2\n", "f.csv", ("date", "y")))
    with pytest.raises(SnapshotParseError, match="line 3: short row"):
        list(iter_csv_rows("date,x\n1,2\n3\n", "f.csv", ("date", "x")))
    with pytest.raises(SnapshotParseError, match="field larger than field limit"):
        list(iter_csv_rows("date,x\n1," + "9" * 200_000 + "\n", "f.csv", ("date", "x")))
    monkeypatch.setattr(integrity, "MAX_CSV_ROWS", 2)
    with pytest.raises(SnapshotParseError, match="more than 2 rows"):
        list(iter_csv_rows("date\n1\n2\n3\n", "f.csv", ("date",)))
    assert list(iter_csv_rows("date,x,extra\n1,2,3\n", "f.csv", ("date", "x"))) == [
        (2, {"date": "1", "x": "2"})
    ], "extra columns are ignored; only the required ones are returned"


def test_both_error_types_are_value_errors() -> None:
    """Existing `except ValueError` handlers must keep working."""
    assert issubclass(SnapshotIntegrityError, DataFileError)
    assert issubclass(SnapshotParseError, DataFileError)
    assert issubclass(DataFileError, ValueError)


# ------------------------------------------------------------------ the command line


def test_the_cli_writes_then_checks_clean_and_reports_changes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "d"
    root.mkdir()
    (root / "x.csv").write_text("a\n")
    assert main(["write", "--data-dir", str(root)]) == 0
    assert "+ x.csv" in capsys.readouterr().out
    assert main(["check", "--data-dir", str(root)]) == 0
    assert "OK: 1 files" in capsys.readouterr().out
    (root / "x.csv").write_text("b\n")
    assert main(["check", "--data-dir", str(root)]) == 1
    assert "MODIFIED" in capsys.readouterr().err
    assert main(["write", "--data-dir", str(root)]) == 0
    assert "~ x.csv" in capsys.readouterr().out
    assert main(["check", "--data-dir", str(root)]) == 0


def test_the_cli_check_fails_cleanly_without_a_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["check", "--data-dir", str(tmp_path)]) == 1
    assert "FAIL" in capsys.readouterr().err


# ------------------------------------------------------------------ the real repository


def test_the_committed_manifest_matches_every_committed_snapshot() -> None:
    """The control's own tripwire: edit a snapshot (or add one) without running
    `snapshot_integrity write` and this fails."""
    assert COMMITTED_DATA_DIR.is_dir()
    assert verify_directory(COMMITTED_DATA_DIR) == []
    assert len(load_manifest(COMMITTED_DATA_DIR)) >= 18


def test_the_committed_directory_is_protected_from_line_ending_conversion() -> None:
    """A Windows checkout with autocrlf would rewrite every CSV and make the manifest
    fail for no real reason; `.gitattributes` turns text conversion off for the directory."""
    attributes = (REPO_ROOT / ".gitattributes").read_text()
    assert "data_cache/** -text" in attributes.splitlines()


_LOADERS: list[tuple[str, Callable[[Path], Any]]] = [
    ("kaggle_us_macro_monthly.csv", load_kaggle_us_macro_observations),
    ("kaggle_us_macro_extended_monthly.csv", load_extended_macro_observations),
    ("kaggle_term_spread_monthly.csv", load_term_spread_observations),
    ("kaggle_sp500_daily_close.csv", load_sp500_closes),
    ("kaggle_sp500_spliced_daily_close.csv", load_daily_closes),
    ("kaggle_nasdaq_daily_close.csv", load_daily_closes),
    ("kaggle_cpi_index_monthly.csv", load_cpi_index_levels),
    ("kaggle_fed_policy_monthly.csv", load_fed_policy_months),
    ("treasury_yield_spread_monthly.csv", load_treasury_yield_spread_observations),
    ("us_cpi_monthly.csv", load_cpi_observations),
    ("ff3_monthly_snapshot.csv", load_cached_ff3_snapshot),
]


@pytest.fixture
def committed_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A private copy of the real `data_cache` that the loaders treat as THE committed
    directory, so a test can damage it without touching the repository."""
    copy = tmp_path / "data_cache"
    shutil.copytree(COMMITTED_DATA_DIR, copy)
    monkeypatch.setattr(integrity, "COMMITTED_DATA_DIR", copy)
    return copy


@pytest.mark.parametrize(("name", "loader"), _LOADERS, ids=[n for n, _ in _LOADERS])
def test_every_snapshot_loader_loads_the_real_file_and_refuses_an_altered_one(
    committed_copy: Path, name: str, loader: Callable[[Path], Any]
) -> None:
    loaded = loader(committed_copy / name)
    rows = loaded[0] if isinstance(loaded, tuple) else loaded  # S&P returns (dates, closes)
    assert len(rows) > 100, "the untouched copy loads"
    original = (committed_copy / name).read_bytes()
    (committed_copy / name).write_bytes(original + b"\n")
    with pytest.raises(SnapshotIntegrityError, match="does not match"):
        loader(committed_copy / name)


def test_the_loaders_cover_every_csv_in_the_committed_directory() -> None:
    """Adding a snapshot without routing its loader through the verified reader would
    leave it unprotected; this makes the omission visible."""
    csvs = {p.name for p in COMMITTED_DATA_DIR.glob("*.csv")}
    assert csvs == {name for name, _ in _LOADERS}
