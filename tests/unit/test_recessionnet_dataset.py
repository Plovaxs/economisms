import calendar
import csv
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from prometheus.econosim.pit import MacroObservation
from prometheus.recessionnet.dataset import (
    MissingSeriesError,
    RecessionDataset,
    build_recession_dataset,
    chronological_split,
)
from prometheus.recessionnet.labels import NBER_RECESSIONS

_FIXTURE_CSV = Path(__file__).resolve().parents[1] / "fixtures" / "ff3_monthly_real.csv"
_SERIES_IDS = ("FF3_Mkt-RF", "FF3_SMB", "FF3_HML", "FF3_RF")


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _load_real_ff3_observations() -> list[MacroObservation]:
    """The REAL Kenneth French monthly factor history (captured live
    from mba.tuck.dartmouth.edu on 2026-11-09; see
    tests/fixtures/ff3_monthly_real.meta.json for provenance/hash),
    not a synthetic or hand-constructed fixture."""
    observations: list[MacroObservation] = []
    with _FIXTURE_CSV.open() as f:
        for row in csv.DictReader(f):
            year, month = int(row["date"][:4]), int(row["date"][4:6])
            observation_at = _month_end(year, month)
            for factor in ("Mkt-RF", "SMB", "HML", "RF"):
                observations.append(
                    MacroObservation(
                        series_id=f"FF3_{factor}",
                        observation_at=observation_at,
                        published_at=observation_at,
                        value=float(row[factor]),
                    )
                )
    return observations


_REAL_OBSERVATIONS = _load_real_ff3_observations()


def test_build_recession_dataset_produces_correctly_shaped_windows() -> None:
    dataset = build_recession_dataset(
        _REAL_OBSERVATIONS, _SERIES_IDS, NBER_RECESSIONS, window=6, horizon=6
    )
    assert dataset.features.shape[1] == 6 * len(_SERIES_IDS)
    assert dataset.features.shape[0] == len(dataset.labels) == len(dataset.decision_months)
    assert all(
        dataset.target_months[i] > dataset.decision_months[i] for i in range(len(dataset.labels))
    )


def _expected_month_end_offset(start: date, months_ahead: int) -> date:
    month_index = start.month - 1 + months_ahead
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    return _month_end(year, month)


def test_target_month_is_exactly_horizon_months_after_the_decision_month() -> None:
    dataset = build_recession_dataset(
        _REAL_OBSERVATIONS, _SERIES_IDS, NBER_RECESSIONS, window=3, horizon=6
    )
    for i in range(0, len(dataset.labels), 97):  # sample a spread, not every row
        assert dataset.target_months[i] == _expected_month_end_offset(
            dataset.decision_months[i], 6
        )


def test_decision_months_are_strictly_chronological() -> None:
    dataset = build_recession_dataset(
        _REAL_OBSERVATIONS, _SERIES_IDS, NBER_RECESSIONS, window=3, horizon=3
    )
    months = dataset.decision_months
    assert all(months[i] < months[i + 1] for i in range(len(months) - 1))


def test_a_great_recession_target_month_is_labeled_positive() -> None:
    dataset = build_recession_dataset(
        _REAL_OBSERVATIONS, _SERIES_IDS, NBER_RECESSIONS, window=6, horizon=6
    )
    positive_targets_2008 = [
        i for i, m in enumerate(dataset.target_months) if m.year == 2008 and m.month in (6, 7, 8)
    ]
    assert positive_targets_2008
    assert all(dataset.labels[i] == 1.0 for i in positive_targets_2008)


def test_a_mid_expansion_target_month_is_labeled_negative() -> None:
    dataset = build_recession_dataset(
        _REAL_OBSERVATIONS, _SERIES_IDS, NBER_RECESSIONS, window=6, horizon=6
    )
    negative_targets_2015 = [i for i, m in enumerate(dataset.target_months) if m.year == 2015]
    assert negative_targets_2015
    assert all(dataset.labels[i] == 0.0 for i in negative_targets_2015)


def test_features_are_scaled_down_from_raw_percentage_returns() -> None:
    dataset = build_recession_dataset(
        _REAL_OBSERVATIONS, _SERIES_IDS, NBER_RECESSIONS, window=1, horizon=1
    )
    # Real monthly factor returns are typically within +/- 25%; scaled
    # by 100 they must sit comfortably inside a tanh-friendly range.
    assert np.max(np.abs(dataset.features)) < 1.0


def test_window_must_be_positive() -> None:
    with pytest.raises(ValueError, match="window"):
        build_recession_dataset(
            _REAL_OBSERVATIONS, _SERIES_IDS, NBER_RECESSIONS, window=0, horizon=3
        )


def test_horizon_must_be_positive() -> None:
    with pytest.raises(ValueError, match="horizon"):
        build_recession_dataset(
            _REAL_OBSERVATIONS, _SERIES_IDS, NBER_RECESSIONS, window=3, horizon=0
        )


def test_missing_series_raises_rather_than_silently_zero_filling() -> None:
    partial_observations = [o for o in _REAL_OBSERVATIONS if o.series_id != "FF3_RF"]
    with pytest.raises(MissingSeriesError, match="FF3_RF"):
        build_recession_dataset(
            partial_observations, _SERIES_IDS, NBER_RECESSIONS, window=3, horizon=3
        )


def test_dataset_post_init_rejects_misaligned_arrays() -> None:
    with pytest.raises(ValueError, match="align"):
        RecessionDataset(
            decision_months=(date(2000, 1, 1),),
            target_months=(date(2000, 2, 1), date(2000, 3, 1)),
            features=np.zeros((1, 4)),
            labels=np.zeros(1),
            series_ids=("FF3_Mkt-RF",),
            window=4,
            horizon=1,
        )


def test_dataset_post_init_rejects_a_feature_width_mismatch() -> None:
    with pytest.raises(ValueError, match="width"):
        RecessionDataset(
            decision_months=(date(2000, 1, 1),),
            target_months=(date(2000, 2, 1),),
            features=np.zeros((1, 3)),
            labels=np.zeros(1),
            series_ids=("FF3_Mkt-RF",),
            window=4,
            horizon=1,
        )


def test_chronological_split_separates_train_and_test_by_decision_month() -> None:
    dataset = build_recession_dataset(
        _REAL_OBSERVATIONS, _SERIES_IDS, NBER_RECESSIONS, window=6, horizon=6
    )
    split_date = date(2000, 1, 1)
    train, test = chronological_split(dataset, split_date)
    assert all(m < split_date for m in train.decision_months)
    assert all(m >= split_date for m in test.decision_months)
    assert len(train.labels) + len(test.labels) == len(dataset.labels)


def test_chronological_split_rejects_a_split_emptying_the_test_set() -> None:
    dataset = build_recession_dataset(
        _REAL_OBSERVATIONS, _SERIES_IDS, NBER_RECESSIONS, window=6, horizon=6
    )
    far_future = date(2100, 1, 1)
    with pytest.raises(ValueError, match="non-empty"):
        chronological_split(dataset, far_future)


def test_chronological_split_rejects_a_split_emptying_the_train_set() -> None:
    dataset = build_recession_dataset(
        _REAL_OBSERVATIONS, _SERIES_IDS, NBER_RECESSIONS, window=6, horizon=6
    )
    far_past = date(1900, 1, 1)
    with pytest.raises(ValueError, match="non-empty"):
        chronological_split(dataset, far_past)


def test_a_realistic_2000_split_has_positive_examples_on_both_sides() -> None:
    """Sanity check for the actual split the benchmark will use: both
    the pre-2000 training era (1970s stagflation, early-1980s double-
    dip, 1990-91) and the post-2000 test era (dot-com, GFC, COVID)
    contain real recessions, so this is not an all-one-class split."""
    dataset = build_recession_dataset(
        _REAL_OBSERVATIONS, _SERIES_IDS, NBER_RECESSIONS, window=6, horizon=6
    )
    train, test = chronological_split(dataset, date(2000, 1, 1))
    assert train.labels.sum() > 0
    assert test.labels.sum() > 0
    assert train.labels.sum() < len(train.labels)
    assert test.labels.sum() < len(test.labels)
