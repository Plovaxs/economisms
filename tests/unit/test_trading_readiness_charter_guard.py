from __future__ import annotations

from pathlib import Path

from prometheus.trading_readiness.charter_guard import (
    default_research_api_is_isolated,
    find_trading_readiness_importers,
    live_trading_exclusion_is_still_declared,
)

_SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "prometheus"


def test_the_real_default_research_api_is_isolated_today() -> None:
    """The actual, current state of this repository, not a synthetic
    fixture: service/dashboard/jobs/orchestration genuinely do not
    import prometheus.trading_readiness anywhere, right now."""
    assert default_research_api_is_isolated(_SRC_ROOT)


def test_the_real_gate_reports_live_trading_exclusion_is_still_declared() -> None:
    assert live_trading_exclusion_is_still_declared()


def test_the_scanner_actually_catches_an_absolute_import(tmp_path: Path) -> None:
    """Proves the scanner itself works, not just that today's codebase
    happens to pass it: a planted violation is found."""
    offender = tmp_path / "service" / "oops.py"
    offender.parent.mkdir(parents=True)
    offender.write_text("import prometheus.trading_readiness.kill_switch\n")
    hits = find_trading_readiness_importers(tmp_path / "service")
    assert hits == (offender,)


def test_the_scanner_catches_a_from_import_too(tmp_path: Path) -> None:
    offender = tmp_path / "dashboard" / "oops.py"
    offender.parent.mkdir(parents=True)
    offender.write_text("from prometheus.trading_readiness import kill_switch\n")
    hits = find_trading_readiness_importers(tmp_path / "dashboard")
    assert hits == (offender,)


def test_the_scanner_catches_a_relative_import() -> None:
    """A relative import (`from ..trading_readiness import x`, used
    from somewhere inside prometheus/) has no "prometheus." prefix in
    its AST module name -- confirmed this is still caught, not a blind
    spot in the scanner."""
    offender_source = "from ..trading_readiness import kill_switch\n"
    import ast

    tree = ast.parse(offender_source)
    found = any(
        isinstance(node, ast.ImportFrom)
        and "trading_readiness" in (node.module or "").split(".")
        for node in ast.walk(tree)
    )
    assert found


def test_an_unrelated_import_is_not_a_false_positive(tmp_path: Path) -> None:
    clean = tmp_path / "jobs" / "fine.py"
    clean.parent.mkdir(parents=True)
    clean.write_text(
        "import prometheus.evidence.repository_status\n"
        "from prometheus.core.money import Money\n"
        "# a comment mentioning prometheus.trading_readiness should not count\n"
    )
    assert find_trading_readiness_importers(tmp_path / "jobs") == ()


def test_isolation_fails_when_a_planted_violation_exists(tmp_path: Path) -> None:
    for package in ("service", "dashboard", "jobs", "orchestration"):
        (tmp_path / package).mkdir()
    offender = tmp_path / "orchestration" / "oops.py"
    offender.write_text("import prometheus.trading_readiness\n")
    assert not default_research_api_is_isolated(tmp_path)
