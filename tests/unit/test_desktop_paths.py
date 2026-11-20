"""PR-205: where the desktop application keeps its state, and how it is kept private."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from prometheus.desktop import paths
from prometheus.desktop.paths import (
    AlreadyRunningError,
    InstanceLock,
    StateDirectoryError,
    default_state_dir,
    ensure_private_directory,
)

# ------------------------------------------------------------------ choosing the directory


def test_the_explicit_variable_wins_over_the_xdg_default(tmp_path: Path) -> None:
    environ = {"ECONOSIM_HOME": str(tmp_path / "mine"), "XDG_DATA_HOME": str(tmp_path / "xdg")}
    assert default_state_dir(environ) == tmp_path / "mine"


def test_xdg_data_home_is_used_when_there_is_no_explicit_variable(tmp_path: Path) -> None:
    assert default_state_dir({"XDG_DATA_HOME": str(tmp_path)}) == tmp_path / "econosim"


def test_the_home_directory_is_the_last_resort(tmp_path: Path) -> None:
    assert default_state_dir({}, home=tmp_path) == tmp_path / ".local" / "share" / "econosim"


def test_a_relative_xdg_value_is_ignored_as_the_spec_requires(tmp_path: Path) -> None:
    assert default_state_dir({"XDG_DATA_HOME": "relative/dir"}, home=tmp_path) == (
        tmp_path / ".local" / "share" / "econosim"
    )


def test_a_relative_explicit_path_is_refused_not_resolved_against_the_working_directory() -> None:
    with pytest.raises(StateDirectoryError, match="absolute"):
        default_state_dir({"ECONOSIM_HOME": "results/here"})


def test_the_explicit_variable_expands_a_leading_tilde(tmp_path: Path) -> None:
    resolved = default_state_dir({"ECONOSIM_HOME": "~/econ"})
    assert resolved.is_absolute() and resolved.name == "econ"


def test_an_empty_explicit_variable_is_treated_as_unset(tmp_path: Path) -> None:
    assert default_state_dir({"ECONOSIM_HOME": "", "XDG_DATA_HOME": str(tmp_path)}) == (
        tmp_path / "econosim"
    )


# ------------------------------------------------------------------ keeping it private


def test_a_new_directory_is_created_private_with_its_parents(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "state"
    assert ensure_private_directory(target) == target.resolve()
    assert stat.S_IMODE(target.stat().st_mode) == 0o700


def test_an_existing_private_directory_is_accepted_unchanged(tmp_path: Path) -> None:
    target = tmp_path / "state"
    target.mkdir(mode=0o700)
    (target / "keep.txt").write_text("x")
    assert ensure_private_directory(target) == target.resolve()
    assert (target / "keep.txt").read_text() == "x"


@pytest.mark.parametrize("mode", [0o755, 0o750, 0o705, 0o770, 0o777])
def test_a_directory_open_to_group_or_others_is_refused_and_left_alone(
    tmp_path: Path, mode: int
) -> None:
    target = tmp_path / "state"
    target.mkdir()
    target.chmod(mode)
    with pytest.raises(StateDirectoryError, match=f"{mode:04o}.*chmod 700"):
        ensure_private_directory(target)
    assert stat.S_IMODE(target.stat().st_mode) == mode, "the user's directory must not be changed"


def test_a_symlink_is_refused_even_when_it_points_at_a_private_directory(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    link = tmp_path / "link"
    link.symlink_to(real)
    with pytest.raises(StateDirectoryError, match="is a symlink"):  # not in the tmp path
        ensure_private_directory(link)


def test_a_regular_file_is_refused(tmp_path: Path) -> None:
    target = tmp_path / "file"
    target.write_text("x")
    with pytest.raises(StateDirectoryError, match="not a directory"):
        ensure_private_directory(target)


def test_a_directory_owned_by_someone_else_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "state"
    target.mkdir(mode=0o700)
    real_uid = os.getuid()  # captured first: `paths.os` is the global `os` module
    monkeypatch.setattr(paths.os, "getuid", lambda: real_uid + 1)
    with pytest.raises(StateDirectoryError, match="another user"):
        ensure_private_directory(target)


def test_an_uninspectable_path_is_reported_not_leaked_as_a_raw_oserror(tmp_path: Path) -> None:
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    (blocked / "inner").mkdir()
    blocked.chmod(0o000)
    try:
        if os.access(blocked, os.X_OK):
            pytest.skip("running with privileges that ignore directory permissions")
        with pytest.raises(StateDirectoryError, match="cannot inspect"):
            ensure_private_directory(blocked / "inner")
    finally:
        blocked.chmod(0o700)


# ------------------------------------------------------------------ one window per directory


def test_a_second_instance_is_refused_until_the_first_lets_go(tmp_path: Path) -> None:
    first, second = InstanceLock(tmp_path), InstanceLock(tmp_path)
    first.acquire()
    assert first.held
    with pytest.raises(AlreadyRunningError, match="already using"):
        second.acquire()
    assert not second.held
    first.release()
    assert not first.held
    second.acquire()
    assert second.held
    second.release()


def test_the_lock_is_a_context_manager_that_always_releases(tmp_path: Path) -> None:
    with InstanceLock(tmp_path) as lock:
        assert lock.held
        with pytest.raises(AlreadyRunningError):
            InstanceLock(tmp_path).acquire()
    with InstanceLock(tmp_path):
        pass


def test_acquiring_twice_and_releasing_twice_are_harmless(tmp_path: Path) -> None:
    lock = InstanceLock(tmp_path)
    lock.acquire()
    lock.acquire()
    lock.release()
    lock.release()
    assert not lock.held


def test_the_lock_file_is_private_and_a_symlink_in_its_place_is_not_followed(
    tmp_path: Path,
) -> None:
    with InstanceLock(tmp_path):
        assert stat.S_IMODE((tmp_path / paths.LOCK_FILENAME).stat().st_mode) == 0o600
    other = tmp_path / "elsewhere"
    other.mkdir()
    victim = other / "victim.txt"
    victim.write_text("precious")
    planted = other / "planted"
    planted.mkdir()
    (planted / paths.LOCK_FILENAME).symlink_to(victim)
    with pytest.raises(OSError):
        InstanceLock(planted).acquire()
    assert victim.read_text() == "precious"
