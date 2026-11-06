"""Immutable train/validation/test regime splits (EXP-04: "lock
train/validation/test regimes and date cutoffs"; acceptance criterion:
"immutable split IDs and holdout manifest").

Each `DataSplit` is a frozen dataclass naming one contiguous date range
and the regime ("train"/"validation"/"test") it belongs to -- "locked"
in two senses: Python-frozen against in-process mutation, AND content-
addressed once assembled into a `HoldoutManifest`, whose `manifest_id`
is a `compute_result_hash` (the same canonical-JSON SHA256 hash
`evidence.integrity`'s artifact seals and `service.reports`'
`market_snapshot_id` already use, reused rather than reinvented) over
every split's own fields. Two manifests built from bit-identical splits
always carry the identical id; changing even one date cutoff changes
it -- so a manifest's id is itself tamper-evident evidence of exactly
which cutoffs were locked in, not merely a caller-chosen label.

`build_holdout_manifest` is the only intended constructor: it rejects
duplicate split ids and any pair of splits whose date ranges overlap
(a date must belong to at most one regime, or the whole point of
locking the cutoffs -- no train/test leakage through an ambiguous
boundary date -- would not hold), THEN computes the id, so a caller can
never end up with a manifest whose id does not actually correspond to
a self-consistent partition. Splits are deliberately not required to
cover every date (a gap between regimes, e.g. for a quarantine buffer
around a cutoff, is legitimate); only overlap is rejected.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

from prometheus.experiments.manifest import compute_result_hash

Regime = Literal["train", "validation", "test"]
_REGIMES: frozenset[str] = frozenset({"train", "validation", "test"})


@dataclass(frozen=True, slots=True)
class DataSplit:
    split_id: str
    regime: Regime
    start: date
    end: date

    def __post_init__(self) -> None:
        if not self.split_id:
            raise ValueError("split_id must not be empty")
        if self.regime not in _REGIMES:
            raise ValueError(f"regime must be one of {sorted(_REGIMES)}, got {self.regime!r}")
        if self.start > self.end:
            raise ValueError(f"start ({self.start}) must not be after end ({self.end})")

    def contains(self, t: date) -> bool:
        return self.start <= t <= self.end


@dataclass(frozen=True, slots=True)
class HoldoutManifest:
    manifest_id: str
    splits: tuple[DataSplit, ...]


def build_holdout_manifest(splits: Sequence[DataSplit]) -> HoldoutManifest:
    if not splits:
        raise ValueError("a holdout manifest needs at least one split")

    ids = [s.split_id for s in splits]
    if len(ids) != len(set(ids)):
        duplicates = sorted({sid for sid in ids if ids.count(sid) > 1})
        raise ValueError(
            f"split_id values must be unique within a manifest, duplicates: {duplicates}"
        )

    ordered = tuple(sorted(splits, key=lambda s: s.start))
    for earlier, later in zip(ordered, ordered[1:], strict=False):
        if earlier.end >= later.start:
            raise ValueError(
                f"splits {earlier.split_id!r} ({earlier.start}..{earlier.end}) and "
                f"{later.split_id!r} ({later.start}..{later.end}) overlap -- regime date "
                "ranges must partition disjointly, with no date in more than one split"
            )

    manifest_id = compute_result_hash(
        {
            "splits": [
                {"split_id": s.split_id, "regime": s.regime, "start": s.start, "end": s.end}
                for s in ordered
            ]
        }
    )
    return HoldoutManifest(manifest_id=manifest_id, splits=ordered)


def split_for_date(manifest: HoldoutManifest, t: date) -> DataSplit | None:
    """The split whose date range contains `t`, or None if `t` falls in
    a deliberate gap between regimes (see this module's docstring)."""
    for split in manifest.splits:
        if split.contains(t):
            return split
    return None


def regime_for_date(manifest: HoldoutManifest, t: date) -> Regime | None:
    split = split_for_date(manifest, t)
    return split.regime if split is not None else None
