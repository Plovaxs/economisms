"""PR-204: `econosim doctor`, the preflight check.

Each check is exercised on throwaway files and fake `importlib.metadata` answers, so the verdicts
are known in advance; one test runs the whole thing against this very checkout.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from importlib import metadata
from pathlib import Path

import pytest

from prometheus import doctor
from prometheus.cli import main as cli_main
from prometheus.data_ingestion.snapshot_integrity import (
    MANIFEST_FILENAME,
    compute_manifest,
    render_manifest,
)
from prometheus.doctor import (
    Check,
    check_credentials_file,
    check_data_integrity,
    check_frontend_build,
    check_locked_dependencies,
    check_python,
    check_state_directory,
    main,
    run_checks,
)

_LOCK = """\
version = 1
requires-python = ">=3.11"

[[package]]
name = "numpy"
version = "2.4.6"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "numpy"
version = "2.5.4"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "torch"
version = "2.15.0+cpu"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "attrs"
version = "26.1.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "prometheus-econ"
version = "0.4.0"
source = { editable = "." }

[[package]]
name = "only-on-windows"
version = "1.0"
source = { registry = "https://pypi.org/simple" }
"""


def _lock(tmp_path: Path, text: str = _LOCK) -> Path:
    path = tmp_path / "uv.lock"
    path.write_text(text)
    return path


def _versions(mapping: dict[str, str]) -> Callable[[str], str]:
    def installed(name: str) -> str:
        if name not in mapping:
            raise metadata.PackageNotFoundError(name)
        return mapping[name]

    return installed


# ------------------------------------------------------------------ python


@pytest.mark.parametrize(
    ("version", "status"),
    [((3, 11, 0), "ok"), ((3, 14, 7), "ok"), ((3, 10, 14), "fail"), ((2, 7, 18), "fail")],
)
def test_the_python_version_must_be_supported(version: tuple[int, ...], status: str) -> None:
    assert check_python(version).status == status


# ------------------------------------------------------------------ locked dependencies


def test_matching_versions_pass_and_uninstalled_locked_packages_are_skipped(tmp_path: Path) -> None:
    check = check_locked_dependencies(
        _lock(tmp_path),
        installed=_versions({"numpy": "2.5.4", "torch": "2.15.0", "attrs": "26.1.0"}),
    )
    assert check.status == "ok"
    assert "3 installed packages checked, 1 locked but not installed" in check.detail


def test_a_lock_holding_several_versions_per_name_accepts_any_of_them(tmp_path: Path) -> None:
    for version in ("2.4.6", "2.5.4"):
        assert (
            check_locked_dependencies(
                _lock(tmp_path), installed=_versions({"numpy": version})
            ).status
            == "ok"
        )


def test_a_local_version_tag_is_a_build_detail_not_a_different_release(tmp_path: Path) -> None:
    for torch in ("2.15.0", "2.15.0+cpu", "2.15.0+cu128"):
        assert (
            check_locked_dependencies(_lock(tmp_path), installed=_versions({"torch": torch})).status
            == "ok"
        ), torch


def test_a_numerical_stack_mismatch_is_a_failure_that_names_the_package(tmp_path: Path) -> None:
    check = check_locked_dependencies(
        _lock(tmp_path), installed=_versions({"numpy": "2.0.1", "attrs": "26.1.0"})
    )
    assert check.status == "fail"
    assert "numpy 2.0.1 (locked 2.4.6/2.5.4)" in check.detail


def test_any_other_mismatch_is_only_a_warning(tmp_path: Path) -> None:
    check = check_locked_dependencies(
        _lock(tmp_path), installed=_versions({"numpy": "2.4.6", "attrs": "25.0.0"})
    )
    assert check.status == "warn" and "attrs 25.0.0" in check.detail


def test_the_project_itself_is_not_compared(tmp_path: Path) -> None:
    check = check_locked_dependencies(
        _lock(tmp_path), installed=_versions({"prometheus-econ": "9.9.9", "numpy": "2.4.6"})
    )
    assert check.status == "ok"


def test_a_missing_or_corrupt_lock_is_reported_not_guessed_at(tmp_path: Path) -> None:
    assert check_locked_dependencies(tmp_path / "absent.lock").status == "skip"
    assert check_locked_dependencies(_lock(tmp_path, "this is [not toml")).status == "fail"
    binary = tmp_path / "bin.lock"
    binary.write_bytes(b"\xff\xfe\x00")
    assert check_locked_dependencies(binary).status == "fail"


# ------------------------------------------------------------------ data integrity


def test_data_integrity_follows_the_manifest(tmp_path: Path) -> None:
    root = tmp_path / "data"
    root.mkdir()
    (root / "a.csv").write_text("x\n")
    (root / MANIFEST_FILENAME).write_text(render_manifest(compute_manifest(root)))
    assert check_data_integrity(root).status == "ok"
    (root / "a.csv").write_text("y\n")
    check = check_data_integrity(root)
    assert check.status == "fail" and "modified a.csv" in check.detail
    (root / MANIFEST_FILENAME).unlink()
    assert check_data_integrity(root).status == "fail"
    assert check_data_integrity(tmp_path / "absent").status == "skip"


# ------------------------------------------------------------------ the credentials file


def test_a_credentials_file_must_be_private(tmp_path: Path) -> None:
    secret = tmp_path / "credentials"
    secret.write_text("x")
    secret.chmod(0o600)
    assert check_credentials_file(secret).status == "ok"
    for mode in (0o640, 0o604, 0o644, 0o666):
        secret.chmod(mode)
        check = check_credentials_file(secret)
        assert check.status == "fail" and f"{mode:04o}" in check.detail


def test_a_credentials_symlink_directory_or_missing_file_fails(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.write_text("x")
    real.chmod(0o600)
    link = tmp_path / "link"
    link.symlink_to(real)
    assert check_credentials_file(link).status == "fail"
    assert check_credentials_file(tmp_path).status == "fail"
    assert check_credentials_file(tmp_path / "absent").status == "fail"
    assert check_credentials_file(None).status == "skip"


# ------------------------------------------------------------------ the state directory


def test_the_state_directory_must_exist_and_be_writable(tmp_path: Path) -> None:
    assert check_state_directory(tmp_path).status == "ok"
    assert list(tmp_path.iterdir()) == [], "the probe file is removed"
    assert check_state_directory(tmp_path / "absent").status == "fail"
    assert check_state_directory(None).status == "skip"


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write to a read-only directory")
def test_a_read_only_state_directory_fails(tmp_path: Path) -> None:
    locked = tmp_path / "ro"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        assert check_state_directory(locked).status == "fail"
    finally:
        locked.chmod(0o700)


# ------------------------------------------------------------------ the frontend


def test_a_missing_frontend_build_is_only_a_warning(tmp_path: Path) -> None:
    assert check_frontend_build(tmp_path).status == "warn"
    (tmp_path / "index.html").write_text("<!doctype html>")
    assert check_frontend_build(tmp_path).status == "ok"


# ------------------------------------------------------------------ the command


def test_run_checks_reports_all_six_in_a_fixed_order() -> None:
    names = [c.name for c in run_checks()]
    assert names == [
        "python",
        "locked_dependencies",
        "data_integrity",
        "credentials_file",
        "state_directory",
        "frontend_build",
    ]


def test_the_exit_code_follows_the_failures(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    good = tmp_path / "credentials"
    good.write_text("x")
    good.chmod(0o600)
    no_lock = str(tmp_path / "no.lock")  # skips the dependency comparison: the verdict is ours
    assert main(["--credentials", str(good), "--state-dir", str(tmp_path), "--lock", no_lock]) == 0
    assert "doctor: all clear" in capsys.readouterr().out
    good.chmod(0o644)
    assert main(["--credentials", str(good), "--lock", no_lock]) == 1
    output = capsys.readouterr().out
    assert "[fail] credentials_file" in output and "1 check(s) failed" in output


def test_json_output_is_machine_readable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "credentials"
    bad.write_text("x")
    bad.chmod(0o644)
    assert main(["--json", "--credentials", str(bad), "--lock", str(tmp_path / "no.lock")]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    failing = [c["name"] for c in payload["checks"] if c["status"] == "fail"]
    assert failing == ["credentials_file"]


def test_the_command_is_reachable_from_the_econosim_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli_main(["doctor", "--json", "--lock", str(tmp_path / "no.lock")]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True and payload["checks"][0]["name"] == "python"


def test_this_checkout_passes_every_check_that_can_be_decided_here() -> None:
    """The real environment: Python, the data manifest and (when `uv sync --locked` made this
    environment, as in CI) every locked dependency version."""
    results = {c.name: c for c in run_checks()}
    assert results["python"].status == "ok"
    assert results["data_integrity"].status == "ok"
    assert results["locked_dependencies"].status in ("ok", "warn", "skip"), results[
        "locked_dependencies"
    ].detail
    assert isinstance(results["frontend_build"], Check)


def test_the_module_states_what_it_does_not_do() -> None:
    doc = doctor.__doc__ or ""
    assert "makes no network call" in doc and "not a security control" in doc
