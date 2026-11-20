"""Real dispatch, not mocked: `econosim <subsystem> ...` really calls that
subsystem's own `main`, exercised here through `recovery keygen` and
`dashboard init-auth` -- both local-filesystem-only and safe to run for
real, the same convention `test_dashboard_main.py` already uses for
`init-auth` (`serve`/network-binding actions are started manually once
and documented there, never unit-tested).
"""

from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path

import pytest

from prometheus.cli import main


def test_no_args_prints_usage_and_fails(capsys) -> None:
    exit_code = main([])
    assert exit_code == 1
    out = capsys.readouterr().out
    assert "usage: econosim" in out
    assert "dashboard" in out
    assert "webgateway" in out


@pytest.mark.parametrize("flag", ["-V", "--version"])
def test_version_flag_prints_the_real_installed_package_version(flag, capsys) -> None:
    import importlib.metadata

    exit_code = main([flag])
    assert exit_code == 0
    out = capsys.readouterr().out.strip()
    assert out == f"econosim {importlib.metadata.version('prometheus-econ')}"


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_help_flag_prints_usage_and_succeeds(flag, capsys) -> None:
    exit_code = main([flag])
    assert exit_code == 0
    assert "usage: econosim" in capsys.readouterr().out


def test_unknown_subsystem_reports_the_bad_name_and_fails(capsys) -> None:
    exit_code = main(["not-a-real-subsystem"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "not-a-real-subsystem" in captured.err


def test_dispatches_to_the_real_recovery_keygen(tmp_path) -> None:
    key_file = tmp_path / "recovery.key"
    exit_code = main(["recovery", "keygen", "--output", str(key_file)])
    assert exit_code == 0
    assert key_file.exists()


def test_dispatches_to_the_real_dashboard_init_auth(tmp_path, capsys) -> None:
    credentials = tmp_path / "auth.json"
    token_file = tmp_path / "token"
    exit_code = main(
        [
            "dashboard",
            "init-auth",
            "--credentials",
            str(credentials),
            "--token-file",
            str(token_file),
            "--owner",
            "cli-dispatch-test",
        ]
    )
    assert exit_code == 0
    assert credentials.exists()
    config = json.loads(credentials.read_text())
    assert config["credentials"][0]["owner"] == "cli-dispatch-test"
    capsys.readouterr()


def test_every_subcommand_summary_is_a_non_empty_one_liner() -> None:
    from prometheus.cli import _SUBCOMMANDS

    for name, (summary, run) in _SUBCOMMANDS.items():
        assert summary, f"{name} has no summary"
        assert "\n" not in summary
        assert callable(run)


def test_recovery_and_service_are_never_imported_at_module_level() -> None:
    """`recovery.__main__` needs the 'recovery' extra's cryptography, and
    `service.__main__` needs the 'service' extra's jsonschema, at their
    own module level. If either were imported at this module's level
    instead of lazily inside its own dispatch function, a base install
    (no extras) would crash on `import prometheus.cli` alone -- before
    any subcommand is even chosen. Checks only top-level statements, so
    the intentional imports inside each `_xxx_main` function below are
    not mistaken for the bug this guards against.
    """
    spec = importlib.util.find_spec("prometheus.cli")
    assert spec is not None and spec.origin is not None
    tree = ast.parse(Path(spec.origin).read_text(encoding="utf-8"), filename=spec.origin)

    def imported_module_names(node: ast.stmt) -> list[str]:
        if isinstance(node, ast.Import):
            return [alias.name for alias in node.names]
        if isinstance(node, ast.ImportFrom):
            return [node.module or ""]
        return []

    top_level_imports = {name for node in tree.body for name in imported_module_names(node)}
    forbidden = {"prometheus.recovery", "prometheus.recovery.__main__"}
    forbidden |= {"prometheus.service", "prometheus.service.__main__"}
    assert not (forbidden & top_level_imports)


def test_data_check_runs_the_real_snapshot_integrity_check(capsys) -> None:
    """`econosim data check` is the committed manifest's own verifier, not a copy of it."""
    from prometheus.cli import main

    assert main(["data", "check"]) == 0
    assert "files match MANIFEST.sha256.json" in capsys.readouterr().out
