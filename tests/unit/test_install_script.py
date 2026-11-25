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


# ---- offline bundles (audit item L-05) -----------------------------------------------------------
# A real offline install needs about 400 MB of wheels, so it is exercised by
# scripts/installer-smoke.sh with SMOKE_OFFLINE=1 (CI: the `offline` job). These tests run the real
# script on small hand-made bundles and check every way it must refuse, before it changes anything.

_PY = shutil.which("python3")


def _python_minor() -> str:
    assert _PY is not None
    out = subprocess.run(
        [_PY, "-c", 'import sys; print("%d.%d" % sys.version_info[:2])'],
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def _machine() -> str:
    return subprocess.run(
        ["uname", "-m"], capture_output=True, text=True, check=True
    ).stdout.strip()


needs_python = pytest.mark.skipif(
    _PY is None or tuple(map(int, _python_minor().split("."))) < (3, 11),
    reason="the installer needs python3 >= 3.11 before it reaches the offline checks",
)


def _make_bundle(
    directory: Path, *, python: str | None = None, machine: str | None = None, wheel_ok: bool = True
) -> Path:
    import hashlib

    (directory / "wheelhouse").mkdir(parents=True)
    archive = b"not really an archive; only its checksum is checked before the wheels"
    wheel = b"a wheel"
    (directory / "econosim-source-9.9.9.tar.gz").write_bytes(archive)
    (directory / "wheelhouse" / "a-1-py3-none-any.whl").write_bytes(wheel if wheel_ok else b"x")
    (directory / "SHA256SUMS").write_text(
        f"{hashlib.sha256(archive).hexdigest()}  econosim-source-9.9.9.tar.gz\n"
        f"{hashlib.sha256(wheel).hexdigest()}  wheelhouse/a-1-py3-none-any.whl\n"
    )
    (directory / "OFFLINE-BUNDLE").write_text(
        f"system=Linux\nmachine={machine or _machine()}\npython={python or _python_minor()}\n"
        "archive=econosim-source-9.9.9.tar.gz\n"
    )
    return directory


@needs_python
def test_a_directory_that_is_not_a_bundle_is_refused(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    result = _run(
        tmp_path,
        ECONOSIM_OFFLINE_DIR=str(tmp_path / "empty"),
        ECONOSIM_INSTALL_DIR=str(tmp_path / "app"),
    )
    assert result.returncode == 1 and "is not an offline bundle" in result.stderr
    assert not (tmp_path / "app").exists()


@needs_python
def test_a_bundle_for_another_python_or_architecture_is_refused_before_anything_is_changed(
    tmp_path: Path,
) -> None:
    wrong_python = _make_bundle(tmp_path / "py", python="2.7")
    result = _run(
        tmp_path, ECONOSIM_OFFLINE_DIR=str(wrong_python), ECONOSIM_INSTALL_DIR=str(tmp_path / "app")
    )
    assert result.returncode == 1 and "holds wheels for Python 2.7" in result.stderr
    wrong_machine = _make_bundle(tmp_path / "arch", machine="s390x")
    result = _run(
        tmp_path,
        ECONOSIM_OFFLINE_DIR=str(wrong_machine),
        ECONOSIM_INSTALL_DIR=str(tmp_path / "app"),
    )
    assert result.returncode == 1 and "the bundle is for s390x" in result.stderr
    assert not (tmp_path / "app").exists()


@needs_python
def test_a_corrupted_wheel_stops_the_install_before_anything_is_unpacked(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path / "bundle", wheel_ok=False)
    result = _run(
        tmp_path, ECONOSIM_OFFLINE_DIR=str(bundle), ECONOSIM_INSTALL_DIR=str(tmp_path / "app")
    )
    assert result.returncode == 1
    assert "does not match its SHA256SUMS" in result.stderr
    assert "Unpacking" not in result.stdout and not (tmp_path / "app").exists()


@needs_python
def test_a_corrupted_archive_is_caught_too(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path / "bundle")
    (bundle / "econosim-source-9.9.9.tar.gz").write_bytes(b"tampered")
    result = _run(
        tmp_path, ECONOSIM_OFFLINE_DIR=str(bundle), ECONOSIM_INSTALL_DIR=str(tmp_path / "app")
    )
    assert result.returncode == 1 and "does not match SHA256SUMS" in result.stderr
    assert not (tmp_path / "app").exists()


@needs_python
def test_an_offline_install_never_asks_the_network(tmp_path: Path) -> None:
    """The base URL is the bundle directory itself, whatever the release variables say."""
    bundle = _make_bundle(tmp_path / "bundle", wheel_ok=False)
    result = _run(
        tmp_path,
        ECONOSIM_OFFLINE_DIR=str(bundle),
        ECONOSIM_VERSION="1.2.3",
        ECONOSIM_REPO="nobody/nothing",
        ECONOSIM_INSTALL_DIR=str(tmp_path / "app"),
    )
    assert "github.com" not in result.stdout + result.stderr


@needs_python
def test_making_a_bundle_needs_a_directory_and_refuses_to_mix_into_old_wheels(
    tmp_path: Path,
) -> None:
    assert "usage" in _run(tmp_path, "--make-offline-bundle").stderr
    old = tmp_path / "old"
    (old / "wheelhouse").mkdir(parents=True)
    (old / "wheelhouse" / "stale.whl").write_text("old")
    result = _run(tmp_path, "--make-offline-bundle", str(old), ECONOSIM_BASE_URL="file:///none")
    assert result.returncode == 1 and "is not empty" in result.stderr
