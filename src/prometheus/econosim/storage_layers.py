"""Raw/normalized/features/artifacts storage layers (DAT-06: "implement
raw/normalized/features/artifacts storage layers"; acceptance
criterion: "layer permissions and immutable boundaries tested").

Two separate boundaries, both enforced by code rather than convention:

1. **Immutability**: once a key is written to a `StorageLayer`, writing
   that same key again raises `ImmutableWriteError` -- a layer can
   never silently overwrite data that something downstream may already
   have derived from it.
2. **Layer permissions**: the four named layers form a strict pipeline
   -- `raw -> normalized -> features -> artifacts` -- and `read_from`
   enforces that a layer may only read directly from the ONE layer
   immediately upstream of it (`_ALLOWED_READ_SOURCE`); `features`
   cannot read directly from `raw`, skipping `normalized`, even though
   nothing stops it from knowing a `raw` key's name. This is the same
   kind of boundary `econosim.pit.PointInTimeStore` already enforces
   for a different reason (no bypassing the point-in-time rule) --
   reused as a design pattern, not literally the same code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

LayerName = Literal["raw", "normalized", "features", "artifacts"]

_ALLOWED_READ_SOURCE: dict[str, frozenset[str]] = {
    "raw": frozenset(),
    "normalized": frozenset({"raw"}),
    "features": frozenset({"normalized"}),
    "artifacts": frozenset({"features"}),
}


class ImmutableWriteError(ValueError):
    """Raised when a key already written to a layer is written again."""


class LayerPermissionError(ValueError):
    """Raised when a layer reads directly from a layer it is not
    permitted to read from."""


@dataclass(slots=True)
class StorageLayer:
    name: LayerName
    _data: dict[str, object] = field(default_factory=dict, init=False)

    def write(self, key: str, value: object) -> None:
        if key in self._data:
            raise ImmutableWriteError(
                f"{self.name}: key {key!r} is already written and cannot be "
                "overwritten -- storage layers are immutable once written"
            )
        self._data[key] = value

    def read(self, key: str) -> object:
        return self._data[key]

    def read_from(self, source: StorageLayer, key: str) -> object:
        """Reads `key` from `source`, only if this layer is permitted
        to read directly from `source`'s layer in the raw -> normalized
        -> features -> artifacts pipeline."""
        if source.name not in _ALLOWED_READ_SOURCE[self.name]:
            raise LayerPermissionError(
                f"{self.name} may not read directly from {source.name} -- "
                f"only from {sorted(_ALLOWED_READ_SOURCE[self.name]) or 'nothing'}"
            )
        return source.read(key)
