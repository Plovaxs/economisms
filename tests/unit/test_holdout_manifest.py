import dataclasses
from datetime import date

import pytest

from prometheus.experiments.holdout_manifest import (
    DataSplit,
    HoldoutManifest,
    build_holdout_manifest,
    regime_for_date,
    split_for_date,
)


def _three_regimes() -> list[DataSplit]:
    return [
        DataSplit("train-2024", "train", date(2024, 1, 1), date(2024, 6, 30)),
        DataSplit("val-2024h2", "validation", date(2024, 7, 1), date(2024, 9, 30)),
        DataSplit("test-2024q4", "test", date(2024, 10, 1), date(2024, 12, 31)),
    ]


def test_data_split_rejects_an_inverted_date_range() -> None:
    with pytest.raises(ValueError, match="start"):
        DataSplit("bad", "train", date(2024, 6, 1), date(2024, 1, 1))


def test_data_split_rejects_an_unknown_regime() -> None:
    with pytest.raises(ValueError, match="regime"):
        DataSplit("bad", "holdout", date(2024, 1, 1), date(2024, 2, 1))  # type: ignore[arg-type]


def test_data_split_rejects_an_empty_id() -> None:
    with pytest.raises(ValueError, match="split_id"):
        DataSplit("", "train", date(2024, 1, 1), date(2024, 2, 1))


def test_data_split_is_immutable() -> None:
    split = DataSplit("train-2024", "train", date(2024, 1, 1), date(2024, 6, 30))
    with pytest.raises(dataclasses.FrozenInstanceError):
        split.end = date(2024, 7, 31)  # type: ignore[misc]


def test_data_split_contains_checks_inclusive_boundaries() -> None:
    split = DataSplit("train-2024", "train", date(2024, 1, 1), date(2024, 6, 30))
    assert split.contains(date(2024, 1, 1))
    assert split.contains(date(2024, 6, 30))
    assert split.contains(date(2024, 3, 15))
    assert not split.contains(date(2023, 12, 31))
    assert not split.contains(date(2024, 7, 1))


def test_build_holdout_manifest_rejects_an_empty_sequence() -> None:
    with pytest.raises(ValueError, match="at least one split"):
        build_holdout_manifest([])


def test_build_holdout_manifest_rejects_duplicate_split_ids() -> None:
    dup = DataSplit("train-2024", "validation", date(2025, 1, 1), date(2025, 2, 1))
    with pytest.raises(ValueError, match="unique"):
        build_holdout_manifest([*_three_regimes(), dup])


def test_build_holdout_manifest_rejects_overlapping_date_ranges() -> None:
    """The discriminating half of "lock the cutoffs": a date must belong
    to at most one regime, or a boundary date would ambiguously count as
    both train and validation -- exactly the leakage this item exists to
    prevent."""
    overlapping = DataSplit("bad", "validation", date(2024, 6, 15), date(2024, 8, 1))
    with pytest.raises(ValueError, match="overlap"):
        build_holdout_manifest([*_three_regimes(), overlapping])


def test_build_holdout_manifest_allows_a_gap_between_regimes() -> None:
    """Splits are NOT required to cover every date -- a deliberate
    quarantine buffer around a cutoff is legitimate and must not be
    rejected as an "overlap"."""
    train = DataSplit("train", "train", date(2024, 1, 1), date(2024, 5, 31))
    test = DataSplit("test", "test", date(2024, 7, 1), date(2024, 12, 31))
    manifest = build_holdout_manifest([train, test])
    assert regime_for_date(manifest, date(2024, 6, 15)) is None


def test_manifest_id_is_deterministic_regardless_of_input_order() -> None:
    """Immutable split IDs means the id identifies the PARTITION, not
    the order splits happened to be passed in."""
    splits = _three_regimes()
    m1 = build_holdout_manifest(splits)
    m2 = build_holdout_manifest(list(reversed(splits)))
    assert m1.manifest_id == m2.manifest_id


def test_manifest_id_changes_when_any_cutoff_changes() -> None:
    """The discriminating half: moving even one date cutoff by a single
    day must change the id -- otherwise "locking the cutoffs" would be
    an unverifiable claim, not a checkable one."""
    original = build_holdout_manifest(_three_regimes())
    shifted = [
        DataSplit("train-2024", "train", date(2024, 1, 1), date(2024, 6, 30)),
        DataSplit("val-2024h2", "validation", date(2024, 7, 1), date(2024, 9, 30)),
        DataSplit("test-2024q4", "test", date(2024, 10, 1), date(2024, 12, 30)),  # one day earlier
    ]
    moved = build_holdout_manifest(shifted)
    assert original.manifest_id != moved.manifest_id


def test_manifest_splits_are_stored_sorted_by_start_date() -> None:
    manifest = build_holdout_manifest(list(reversed(_three_regimes())))
    assert [s.split_id for s in manifest.splits] == ["train-2024", "val-2024h2", "test-2024q4"]


def test_manifest_is_immutable() -> None:
    manifest = build_holdout_manifest(_three_regimes())
    with pytest.raises(dataclasses.FrozenInstanceError):
        manifest.manifest_id = "tampered"  # type: ignore[misc]


def test_split_for_date_finds_the_correct_regime() -> None:
    manifest = build_holdout_manifest(_three_regimes())
    assert split_for_date(manifest, date(2024, 3, 1)).split_id == "train-2024"  # type: ignore[union-attr]
    assert split_for_date(manifest, date(2024, 8, 1)).split_id == "val-2024h2"  # type: ignore[union-attr]
    assert split_for_date(manifest, date(2024, 11, 1)).split_id == "test-2024q4"  # type: ignore[union-attr]
    assert split_for_date(manifest, date(2023, 1, 1)) is None


def test_regime_for_date_matches_split_for_date() -> None:
    manifest = build_holdout_manifest(_three_regimes())
    assert regime_for_date(manifest, date(2024, 3, 1)) == "train"
    assert regime_for_date(manifest, date(2024, 8, 1)) == "validation"
    assert regime_for_date(manifest, date(2024, 11, 1)) == "test"
    assert regime_for_date(manifest, date(2023, 1, 1)) is None


def test_holdout_manifest_type_is_exported_and_constructible_fields_match() -> None:
    manifest = build_holdout_manifest(_three_regimes())
    assert isinstance(manifest, HoldoutManifest)
    assert len(manifest.splits) == 3
