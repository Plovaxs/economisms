"""The Linux installer must never delete anything that is not its own.

`ECONOSIM_HOME` is the application's STATE directory (where results are kept; README and DEPLOYMENT
document it). The first installer used the same variable for its own install directory, so a user
who had followed the README and then ran `install-linux.sh --uninstall` would have lost their
results. These tests run the real script (no network, no pip: every case here is a refusal or an
uninstall) and check that a directory that is not the installer's own is left exactly as it was.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "install-linux.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash is required")


def _run(tmp_path: Path, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("ECONOSIM_", "XDG_"))}
    clean.update(HOME=str(home), ECONOSIM_BIN=str(tmp_path / "bin"), **env)
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        env=clean,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _make_install(directory: Path, *, marker: bool) -> None:
    (directory / "venv" / "bin").mkdir(parents=True)
    stub = directory / "venv" / "bin" / "econosim"
    stub.write_text("#!/bin/sh\nexit 0\n")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    (directory / "src").mkdir()
    (directory / "src" / "pyproject.toml").write_text('[project]\nname = "prometheus-econ"\n')
    if marker:
        (directory / ".econosim-install").write_text("econosim installer\n")


def test_the_script_is_valid_bash() -> None:
    assert subprocess.run(["bash", "-n", str(SCRIPT)], check=False).returncode == 0


def test_uninstalling_nothing_is_not_an_error(tmp_path: Path) -> None:
    result = _run(tmp_path, "--uninstall", ECONOSIM_INSTALL_DIR=str(tmp_path / "absent"))
    assert result.returncode == 0 and "Nothing installed" in result.stdout


@pytest.mark.parametrize("marker", [True, False], ids=["marked", "installed-before-the-marker"])
def test_it_uninstalls_what_it_made_and_leaves_the_state_directory_alone(
    tmp_path: Path, marker: bool
) -> None:
    install, state = tmp_path / "app", tmp_path / "state"
    _make_install(install, marker=marker)
    state.mkdir()
    (state / "results.json").write_text("my results")
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "econosim").symlink_to(install / "venv" / "bin" / "econosim")

    result = _run(
        tmp_path, "--uninstall", ECONOSIM_INSTALL_DIR=str(install), ECONOSIM_HOME=str(state)
    )
    assert result.returncode == 0, result.stderr
    assert not install.exists() and not (tmp_path / "bin" / "econosim").exists()
    assert (state / "results.json").read_text() == "my results"


def test_it_refuses_to_use_the_applications_state_directory_as_its_own(tmp_path: Path) -> None:
    """The original defect: the same variable named both directories."""
    state = tmp_path / "state"
    state.mkdir()
    (state / "results.json").write_text("my results")
    _make_install(state, marker=True)  # even if it LOOKS like an install, it is the state directory

    for args in (("--uninstall",), ()):
        result = _run(tmp_path, *args, ECONOSIM_INSTALL_DIR=str(state), ECONOSIM_HOME=str(state))
        assert result.returncode == 1
        assert "state directory" in result.stderr and "ECONOSIM_INSTALL_DIR" in result.stderr
        assert (state / "results.json").read_text() == "my results"
        assert (state / "src").exists()


def test_the_old_variable_alone_no_longer_selects_where_to_delete(tmp_path: Path) -> None:
    """With only ECONOSIM_HOME set (the documented way to move the state), it is not touched."""
    state = tmp_path / "state"
    state.mkdir()
    (state / "results.json").write_text("my results")
    result = _run(tmp_path, "--uninstall", ECONOSIM_HOME=str(state))
    assert result.returncode == 0 and (state / "results.json").exists()


@pytest.mark.parametrize("args", [("--uninstall",), ()])
def test_it_refuses_a_non_empty_directory_it_did_not_make(
    tmp_path: Path, args: tuple[str, ...]
) -> None:
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "notes.txt").write_text("not yours")
    result = _run(
        tmp_path, *args, ECONOSIM_INSTALL_DIR=str(foreign), ECONOSIM_BASE_URL="file:///none"
    )
    assert result.returncode == 1 and "was not made by this installer" in result.stderr
    assert (foreign / "notes.txt").read_text() == "not yours"


def test_an_install_refuses_before_downloading_anything(tmp_path: Path) -> None:
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "notes.txt").write_text("not yours")
    result = _run(
        tmp_path, ECONOSIM_INSTALL_DIR=str(foreign), ECONOSIM_BASE_URL="file:///no/such/dir"
    )
    assert "Fetching the checksum list" not in result.stdout  # the refusal came first
    assert result.returncode == 1


@pytest.mark.parametrize("target", ["/", "HOME"])
def test_it_never_takes_the_root_or_the_home_directory(tmp_path: Path, target: str) -> None:
    directory = str(tmp_path / "home") if target == "HOME" else target
    (tmp_path / "home").mkdir(exist_ok=True)
    result = _run(tmp_path, "--uninstall", ECONOSIM_INSTALL_DIR=directory)
    assert result.returncode == 1 and "refusing" in result.stderr
    assert (tmp_path / "home").exists()
