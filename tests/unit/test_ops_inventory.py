from pathlib import Path

import pytest

from prometheus.evidence.ops_inventory import (
    ServiceComponent,
    build_service_inventory,
    discover_component_names,
    discover_dependencies,
)


def _repo_package_root() -> Path:
    return Path(__file__).resolve().parents[2] / "src" / "prometheus"


def test_service_component_rejects_an_empty_name() -> None:
    with pytest.raises(ValueError, match="name"):
        ServiceComponent(name="", owner="alice", environment="local", depends_on=frozenset())


def test_service_component_rejects_an_empty_owner() -> None:
    with pytest.raises(ValueError, match="owner"):
        ServiceComponent(name="core", owner="", environment="local", depends_on=frozenset())


def test_service_component_rejects_an_empty_environment() -> None:
    with pytest.raises(ValueError, match="environment"):
        ServiceComponent(name="core", owner="alice", environment="", depends_on=frozenset())


def test_discover_component_names_finds_this_repositorys_real_subpackages() -> None:
    """Grounded in the real src/prometheus tree, not a synthetic
    fixture directory."""
    names = discover_component_names(_repo_package_root())
    assert {"core", "econosim", "stochastica", "volterra", "titan", "hedging"} <= names
    assert "numerics" in names  # a bare module, not a subpackage, must also be found
    assert "__pycache__" not in names


def test_discover_dependencies_finds_a_real_known_edge() -> None:
    """econosim genuinely imports from core (the ledger) -- confirmed
    against the real source, not assumed."""
    deps = discover_dependencies(_repo_package_root(), "econosim")
    assert "core" in deps


def test_discover_dependencies_excludes_self_imports() -> None:
    deps = discover_dependencies(_repo_package_root(), "core")
    assert "core" not in deps


def test_discover_dependencies_finds_a_genuine_package_level_cycle() -> None:
    """A real, non-obvious finding from parsing the actual import
    statements: stochastica imports from volterra (a convergence study
    prices via volterra.heston_pricer) WHILE volterra separately
    imports from several stochastica modules for its own pricers --
    a genuine cycle at the package level, confirmed here rather than
    assumed to be acyclic."""
    root = _repo_package_root()
    assert "volterra" in discover_dependencies(root, "stochastica")
    assert "stochastica" in discover_dependencies(root, "volterra")


def test_build_service_inventory_requires_owner_and_environment() -> None:
    """OPS-01's own acceptance criterion: "every production component
    has owner and environment" -- both are required, caller-supplied
    fields with no default, since nothing in this single-maintainer,
    un-deployed repository can honestly derive either from the code."""
    inventory = build_service_inventory(_repo_package_root(), owner="alice", environment="local")
    assert len(inventory) > 10
    for component in inventory:
        assert component.owner == "alice"
        assert component.environment == "local"


def test_build_service_inventory_is_alphabetically_sorted_and_includes_core() -> None:
    inventory = build_service_inventory(_repo_package_root(), owner="alice", environment="local")
    names = [c.name for c in inventory]
    assert names == sorted(names)
    core = next(c for c in inventory if c.name == "core")
    assert core.depends_on == frozenset()  # core is the foundation; it depends on nothing else
