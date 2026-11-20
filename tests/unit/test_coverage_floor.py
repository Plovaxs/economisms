"""PR-204: a coverage floor exists and CI is configured to enforce it.

The measured total on the first CI run to report it was 96% (PR-201). A floor that nothing
enforces is decoration, so this checks both halves: the threshold is configured in
`pyproject.toml`, and the CI step that runs the suite measures coverage of the package (which is
what makes pytest-cov apply the threshold).
"""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _coverage_report_config() -> dict[str, object]:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return dict(pyproject["tool"]["coverage"]["report"])


def test_a_coverage_floor_is_configured_below_the_measured_total() -> None:
    floor = _coverage_report_config()["fail_under"]
    assert isinstance(floor, int | float) and not isinstance(floor, bool)
    assert 90 <= floor <= 96, "a real floor, but under the 96% measured on the first CI run"


def test_ci_runs_the_suite_with_coverage_of_the_package_so_the_floor_applies() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    test_lines = [line for line in workflow.splitlines() if "pytest" in line and "--cov" in line]
    assert test_lines, "no CI step runs pytest with --cov"
    assert all("--cov=prometheus" in line for line in test_lines)
    assert not any("--cov-fail-under=0" in line or "--no-cov" in line for line in test_lines), (
        "the floor must not be switched off on the command line"
    )
