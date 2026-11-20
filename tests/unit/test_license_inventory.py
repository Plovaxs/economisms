from __future__ import annotations

import re
from email.message import Message
from pathlib import Path

import pytest

from prometheus.evidence import license_inventory
from prometheus.evidence.license_inventory import (
    DependencyLicense,
    LicenseExpressionError,
    allows_mit_project,
    collect_license_inventory,
    direct_dependency_names,
)

_PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def test_direct_dependency_names_parses_this_repositorys_real_pyproject_toml() -> None:
    names = direct_dependency_names(_PYPROJECT)
    # The three unconditional core dependencies declared in [project.dependencies].
    assert {"numpy", "scipy", "torch"}.issubset(names)
    # At least one optional-dependency group's packages are included too.
    assert "pytest" in names and "cryptography" in names
    assert len(names) == len(set(names))  # de-duplicated


def test_every_real_installed_direct_dependency_has_a_resolvable_license_signal() -> None:
    names = direct_dependency_names(_PYPROJECT)
    inventory = collect_license_inventory(names)
    assert len(inventory) == len(names)
    unresolved = [
        d.name
        for d in inventory
        if not d.license_expression and not d.license_classifiers and not d.license_field
    ]
    assert unresolved == [], f"no license signal found for: {unresolved}"


def _acceptable(dependency: DependencyLicense) -> bool:
    """Judged from the most precise signal available: the SPDX expression, else the legacy field
    (as an expression if it parses, else by what it says), else the trove classifiers."""
    for candidate in (dependency.license_expression, dependency.license_field):
        if not candidate:
            continue
        try:
            return allows_mit_project(candidate)
        except LicenseExpressionError:
            text = candidate.upper()
            if "GENERAL PUBLIC LICENSE" in text and "LESSER" not in text:
                return False
            if re.search(r"\bA?GPL", text):
                return False
    return not any(
        "General Public License" in c and "Lesser" not in c for c in dependency.license_classifiers
    )


def test_no_direct_dependency_carries_a_copyleft_license_incompatible_with_mit() -> None:
    names = direct_dependency_names(_PYPROJECT)
    offenders = [d.name for d in collect_license_inventory(names) if not _acceptable(d)]
    assert offenders == [], f"copyleft-licensed direct dependency found: {offenders}"


def _fake_metadata(**headers: object) -> Message:
    message = Message()
    message["Version"] = "1.0"
    for name, value in headers.items():
        for item in value if isinstance(value, list) else [value]:
            message[name.replace("_", "-")] = str(item)
    return message


@pytest.mark.parametrize(
    ("headers", "field"),
    [
        ({"License": "LGPL-3.0-only OR GPL-2.0-only"}, "LGPL-3.0-only OR GPL-2.0-only"),
        ({"License": "  MIT  "}, "MIT"),
        ({"License": "UNKNOWN"}, None),
        ({"License": "None"}, None),
        ({"License": ""}, None),
        ({"License": "Permission is hereby granted,\nfree of charge..."}, None),
        ({"License": "x" * 201}, None),
        ({}, None),
    ],
)
def test_the_legacy_license_header_is_reported_only_when_it_is_a_short_single_line(
    monkeypatch: pytest.MonkeyPatch, headers: dict[str, object], field: str | None
) -> None:
    monkeypatch.setattr(
        license_inventory.metadata, "metadata", lambda name: _fake_metadata(**headers)
    )
    [found] = collect_license_inventory(("whatever",))
    assert found.license_field == field and found.license_expression is None


def test_the_spdx_header_is_kept_apart_from_the_legacy_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        license_inventory.metadata,
        "metadata",
        lambda name: _fake_metadata(License_Expression="Apache-2.0", License="Apache Software"),
    )
    [found] = collect_license_inventory(("whatever",))
    assert found.license_expression == "Apache-2.0" and found.license_field == "Apache Software"


def test_pyside6_is_found_licensed_under_a_choice_that_includes_the_lgpl() -> None:
    """The one dependency this project has that is not permissive: judged, not waved through."""
    pytest.importorskip("PySide6")
    [found] = collect_license_inventory(("PySide6-Essentials",))
    shown = found.license_expression or found.license_field or ""
    assert "LGPL-3.0-only" in shown and "GPL-3.0-only" in shown
    assert _acceptable(found)


@pytest.mark.parametrize(
    ("dependency", "acceptable"),
    [
        (DependencyLicense("a", "1", "MIT", ()), True),
        (DependencyLicense("b", "1", "GPL-3.0-only", ()), False),
        (DependencyLicense("c", "1", None, (), "GNU General Public License v3"), False),
        (DependencyLicense("d", "1", None, (), "GNU Lesser General Public License v3"), True),
        (DependencyLicense("e", "1", None, (), "GPLv2 or later"), False),
        (DependencyLicense("f", "1", None, (), "BSD-ish permissive"), True),
        (DependencyLicense("g", "1", None, ("GNU General Public License v3 (GPLv3)",)), False),
        (
            DependencyLicense("h", "1", None, ("GNU Lesser General Public License v3 (LGPLv3)",)),
            True,
        ),
        (DependencyLicense("i", "1", None, ("BSD License",)), True),
    ],
)
def test_the_judgement_uses_the_best_signal_and_does_not_misread_lgpl(
    dependency: DependencyLicense, acceptable: bool
) -> None:
    assert _acceptable(dependency) is acceptable


@pytest.mark.parametrize(
    ("expression", "allowed"),
    [
        ("MIT", True),
        ("BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0", True),
        ("Apache-2.0 OR BSD-3-Clause", True),
        ("Apache-2.0 AND Apache-2.0 WITH LLVM-exception AND BSD-2-Clause", True),
        # the PySide6 case that matters: the licensee may choose the LGPL alternative
        ("LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only", True),
        ("lgpl-2.1-or-later", True),
        ("GPL-3.0-only", False),
        ("GPL-2.0-only OR GPL-3.0-only", False),
        ("AGPL-3.0-or-later", False),
        ("MIT AND GPL-3.0-only", False),
        ("GPL-2.0-only WITH Classpath-exception-2.0", False),
        ("(MIT OR GPL-3.0-only) AND Apache-2.0", True),
        ("(GPL-3.0-only OR AGPL-3.0-only) AND MIT", False),
        ("MIT OR (GPL-3.0-only AND Apache-2.0)", True),
        ("GPL-3.0-only OR MIT AND Apache-2.0", True),  # AND binds tighter than OR
        ("GPL-3.0-or-later", False),
        ("GPL-3.0+", False),
    ],
)
def test_spdx_expressions_are_judged_by_what_the_licensee_may_choose(
    expression: str, allowed: bool
) -> None:
    assert allows_mit_project(expression) is allowed


def test_a_substring_test_for_gpl_cannot_tell_lgpl_apart_which_is_why_it_was_replaced() -> None:
    assert "GPL" in "LGPL-3.0-only"
    assert allows_mit_project("LGPL-3.0-only")


@pytest.mark.parametrize(
    "expression",
    [
        "",
        "   ",
        "MIT OR",
        "OR MIT",
        "(MIT",
        "MIT)",
        "MIT MIT",
        "MIT AND",
        "MIT WITH",
        "MIT !",
        "()",
        "AND",
        "MIT or Apache-2.0",  # operators are upper case in SPDX; this is prose
        "GPLv2 or later",
        "MIT License",
    ],
)
def test_a_malformed_expression_is_an_error_not_a_guess(expression: str) -> None:
    with pytest.raises(LicenseExpressionError):
        allows_mit_project(expression)


def test_a_well_known_mit_dependency_reports_exactly_mit() -> None:
    inventory = collect_license_inventory(("pytest", "jsonschema", "ruff", "mypy"))
    by_name = {d.name: d for d in inventory}
    for name in ("pytest", "jsonschema", "ruff", "mypy"):
        assert by_name[name].license_expression == "MIT"


def test_an_uninstalled_package_name_is_reported_not_silently_dropped() -> None:
    inventory = collect_license_inventory(("this-package-does-not-exist-anywhere",))
    assert len(inventory) == 1
    assert inventory[0].installed_version is None
    assert inventory[0].license_expression is None
