from __future__ import annotations

from pathlib import Path

from prometheus.evidence.license_inventory import collect_license_inventory, direct_dependency_names

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
        d.name for d in inventory if not d.license_expression and not d.license_classifiers
    ]
    assert unresolved == [], f"no license signal found for: {unresolved}"


def test_no_direct_dependency_carries_a_copyleft_license_incompatible_with_mit() -> None:
    names = direct_dependency_names(_PYPROJECT)
    inventory = collect_license_inventory(names)
    _COPYLEFT_MARKERS = ("GPL", "AGPL")  # LGPL deliberately excluded: dynamic linking is permitted
    offenders = [
        d.name
        for d in inventory
        if any(marker in (d.license_expression or "") for marker in _COPYLEFT_MARKERS)
    ]
    assert offenders == [], f"copyleft-licensed direct dependency found: {offenders}"


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
