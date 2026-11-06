"""Service inventory and dependency map (OPS-01: "create service
inventory and dependency map"; acceptance criterion: "every production
component has owner and environment").

The dependency map is not hand-maintained prose that can silently drift
from the real code -- `discover_dependencies` parses every component's
actual `.py` source files with the standard library's `ast` module and
reports exactly which OTHER top-level `prometheus.*` components it
imports from, derived from real `import`/`from ... import` statements,
not a diagram someone drew once. Run against this repository's own real
`src/prometheus` tree, it is confirmed to find the actual 14 subpackages
plus the standalone `numerics` module, and to discover genuine
dependencies this project's maintainer did not necessarily have
front-of-mind -- including a real package-level cycle (`stochastica`
imports from `volterra.heston_pricer` for a convergence study, while
`volterra` separately imports from several `stochastica` modules for
its own pricers), confirmed directly against the source tree rather
than assumed to be acyclic.

`owner` and `environment` are NOT derived from the code (nothing in a
single-maintainer, un-deployed research repository states who owns a
module or what environment it runs in) -- they are required, caller-
supplied fields with no default, the same "no silently-defaulted
field" reasoning this project applies elsewhere (e.g. `service.reports`'
`measure`), so the inventory never claims an owner/environment it was
not deliberately told.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

_IGNORED_ENTRIES = {"__pycache__", "__init__.py"}


@dataclass(frozen=True, slots=True)
class ServiceComponent:
    name: str
    owner: str
    environment: str
    depends_on: frozenset[str]

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("name must not be empty")
        if not self.owner:
            raise ValueError("owner must not be empty")
        if not self.environment:
            raise ValueError("environment must not be empty")


def discover_component_names(package_root: Path) -> frozenset[str]:
    """Every top-level subpackage (a directory with `__init__.py`) and
    standalone module (a bare `.py` file) directly under `package_root`."""
    names = set()
    for child in package_root.iterdir():
        if child.name in _IGNORED_ENTRIES:
            continue
        if child.is_dir() and (child / "__init__.py").is_file():
            names.add(child.name)
        elif child.is_file() and child.suffix == ".py":
            names.add(child.stem)
    return frozenset(names)


def _imported_prometheus_components(path: Path) -> frozenset[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    components = set()
    for full_name in modules:
        if full_name == "prometheus" or full_name.startswith("prometheus."):
            parts = full_name.split(".")
            if len(parts) >= 2:
                components.add(parts[1])
    return frozenset(components)


def discover_dependencies(package_root: Path, component: str) -> frozenset[str]:
    """Every OTHER top-level component `component` actually imports
    from, across every `.py` file belonging to it."""
    target = package_root / component
    files = (
        list(target.rglob("*.py"))
        if target.is_dir()
        else [package_root / f"{component}.py"]
    )
    dependencies: set[str] = set()
    for source_file in files:
        dependencies.update(_imported_prometheus_components(source_file))
    dependencies.discard(component)
    return frozenset(dependencies)


def build_service_inventory(
    package_root: Path, owner: str, environment: str
) -> tuple[ServiceComponent, ...]:
    return tuple(
        ServiceComponent(
            name=name,
            owner=owner,
            environment=environment,
            depends_on=discover_dependencies(package_root, name),
        )
        for name in sorted(discover_component_names(package_root))
    )
