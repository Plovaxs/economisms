"""External data source inventory and license catalog (DAT-01: "Create
inventory of each external data source and license"; acceptance
criterion: "Approved source catalog with allowed use and redistribution").

Like `evidence.ops_inventory`'s own service inventory, this catalog is
not hand-maintained prose that can silently drift from the real
connectors -- `discover_data_sources`/`build_source_catalog` parse every
module in `data_ingestion` with the standard library's `ast` module and
read each connector's OWN already-declared `*_URL` / `*LICENSE`
constants directly, rather than a second, separately-typed copy of the
same facts that could disagree with the code that actually makes the
request. Run against this repository's own real `data_ingestion`
package, it is confirmed to find exactly the two real connectors
(`worldbank`, `french_factors`) with their real URL and license
strings, and to correctly exclude `transport` (the shared transport
abstraction, not a data source itself) and `__init__`.

"Approved" is NOT derived from the code (nothing in a single-maintainer
research repository records who approved a source for use) --
`approved_by` and `allowed_use` are required, caller-supplied fields
with no default, the same "no silently-defaulted field" reasoning
`ops_inventory.ServiceComponent`'s `owner`/`environment` already use,
so the catalog never claims an approval it was not deliberately told.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

_EXCLUDED_MODULES = {"__init__", "transport"}


class SourceInventoryError(ValueError):
    """Raised when a `data_ingestion` module declares exactly one of a
    source URL / source license constant but not both -- an
    incompletely-declared external data source, rather than silently
    cataloging it with a missing field."""


@dataclass(frozen=True, slots=True)
class DataSourceCatalogEntry:
    module: str
    source_url: str
    source_license: str
    approved_by: str
    allowed_use: str

    def __post_init__(self) -> None:
        for field_name, value in (
            ("module", self.module),
            ("source_url", self.source_url),
            ("source_license", self.source_license),
            ("approved_by", self.approved_by),
            ("allowed_use", self.allowed_use),
        ):
            if not value:
                raise ValueError(f"{field_name} must not be empty")


def _discover_url_and_license(path: Path) -> tuple[str | None, str | None]:
    tree = ast.parse(path.read_text(), filename=str(path))
    url_value: str | None = None
    license_value: str | None = None
    for node in tree.body:
        if not (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            continue
        name = node.targets[0].id
        if "LICENSE" in name:
            license_value = node.value.value
        elif "URL" in name:
            url_value = node.value.value
    return url_value, license_value


def discover_data_sources(package_root: Path) -> tuple[str, ...]:
    """Every module directly under `package_root` (a `data_ingestion`
    directory) that declares at least one of a `*_URL` / `*LICENSE`
    module-level string constant, sorted by module name."""
    names = []
    for child in sorted(package_root.glob("*.py")):
        if child.stem in _EXCLUDED_MODULES:
            continue
        url_value, license_value = _discover_url_and_license(child)
        if url_value is not None or license_value is not None:
            names.append(child.stem)
    return tuple(names)


def build_source_catalog(
    package_root: Path, *, approved_by: str, allowed_use: str
) -> tuple[DataSourceCatalogEntry, ...]:
    entries = []
    for module in discover_data_sources(package_root):
        url_value, license_value = _discover_url_and_license(package_root / f"{module}.py")
        if url_value is None or license_value is None:
            raise SourceInventoryError(
                f"{module!r} declares only one of a source URL / source license "
                "constant -- an incompletely-declared external data source"
            )
        entries.append(
            DataSourceCatalogEntry(
                module=module,
                source_url=url_value,
                source_license=license_value,
                approved_by=approved_by,
                allowed_use=allowed_use,
            )
        )
    return tuple(entries)
