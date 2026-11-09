import calendar
import csv
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from prometheus.data_ingestion.monthly_matrix import MissingSeriesError
from prometheus.econosim.pit import MacroObservation
from prometheus.macrocore.regression_dataset import (
    MacroRegressionDataset,
    build_macro_regression_dataset,
    chronological_split,
    extract_target_history,
)

_FIXTURE_CSV = Path(__file__).resolve().parents[1] / "fixtures" / "ff3_monthly_real.csv"
_FEATURE_SERIES_IDS = ("FF3_Mkt-RF", "FF3_SMB", "FF3_HML", "FF3_RF")
_TARGET_SERIES_ID = "FF3_Mkt-RF"


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _load_real_ff3_observations() -> list[MacroObservation]:
    """Duplicated (not cross-imported) from the `recessionnet` test
    modules -- this project's established convention."""
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


def test_build_macro_regression_dataset_produces_correctly_shaped_windows() -> None:
    dataset = build_macro_regression_dataset(
        _REAL_OBSERVATIONS, _FEATURE_SERIES_IDS, _TARGET_SERIES_ID, window=6, horizon=6
    )
    assert dataset.features.shape[1] == 6 * len(_FEATURE_SERIES_IDS)
    n = dataset.features.shape[0]
    assert len(dataset.targets) == len(dataset.most_recent_target_values) == n
    assert len(dataset.decision_months) == len(dataset.target_months) == n
    assert all(dataset.target_months[i] > dataset.decision_months[i] for i in range(n))


def test_most_recent_target_value_matches_the_real_mkt_rf_at_the_decision_month() -> None:
    """The persistence baseline's whole premise: `most_recent_target_values[i]`
    must be the REAL Mkt-RF value realized at decision_months[i], not a
    placeholder -- cross-checked directly against the real fixture."""
    dataset = build_macro_regression_dataset(
        _REAL_OBSERVATIONS, _FEATURE_SERIES_IDS, _TARGET_SERIES_ID, window=3, horizon=3
    )
    real_by_month = {
        obs.observation_at: obs.value
        for obs in _REAL_OBSERVATIONS
        if obs.series_id == _TARGET_SERIES_ID
    }
    for i in range(0, len(dataset.decision_months), 83):
        expected = real_by_month[dataset.decision_months[i]] / 100.0
        assert dataset.most_recent_target_values[i] == pytest.approx(expected)


def test_target_value_matches_the_real_mkt_rf_at_the_target_month() -> None:
    dataset = build_macro_regression_dataset(
        _REAL_OBSERVATIONS, _FEATURE_SERIES_IDS, _TARGET_SERIES_ID, window=3, horizon=6
    )
    real_by_month = {
        obs.observation_at: obs.value
        for obs in _REAL_OBSERVATIONS
        if obs.series_id == _TARGET_SERIES_ID
    }
    for i in range(0, len(dataset.target_months), 83):
        expected = real_by_month[dataset.target_months[i]] / 100.0
        assert dataset.targets[i] == pytest.approx(expected)


def test_window_must_be_positive() -> None:
    with pytest.raises(ValueError, match="window"):
        build_macro_regression_dataset(
            _REAL_OBSERVATIONS, _FEATURE_SERIES_IDS, _TARGET_SERIES_ID, window=0, horizon=3
        )


def test_horizon_must_be_positive() -> None:
    with pytest.raises(ValueError, match="horizon"):
        build_macro_regression_dataset(
            _REAL_OBSERVATIONS, _FEATURE_SERIES_IDS, _TARGET_SERIES_ID, window=3, horizon=0
        )


def test_missing_series_raises_rather_than_silently_zero_filling() -> None:
    partial_observations = [o for o in _REAL_OBSERVATIONS if o.series_id != "FF3_RF"]
    with pytest.raises(MissingSeriesError, match="FF3_RF"):
        build_macro_regression_dataset(
            partial_observations, _FEATURE_SERIES_IDS, _TARGET_SERIES_ID, window=3, horizon=3
        )


def test_target_series_not_among_feature_series_is_supported() -> None:
    """The target does not have to be one of the predictors."""
    dataset = build_macro_regression_dataset(
        _REAL_OBSERVATIONS, ("FF3_SMB", "FF3_HML"), "FF3_Mkt-RF", window=3, horizon=3
    )
    assert dataset.features.shape[1] == 3 * 2
    assert len(dataset.targets) > 0


def test_dataset_post_init_rejects_misaligned_arrays() -> None:
    with pytest.raises(ValueError, match="align"):
        MacroRegressionDataset(
            decision_months=(date(2000, 1, 1),),
            target_months=(date(2000, 2, 1), date(2000, 3, 1)),
            features=np.zeros((1, 4)),
            targets=np.zeros(1),
            most_recent_target_values=np.zeros(1),
            series_ids=("FF3_Mkt-RF",),
            target_series_id="FF3_Mkt-RF",
            window=4,
            horizon=1,
        )


def test_dataset_post_init_rejects_a_feature_width_mismatch() -> None:
    with pytest.raises(ValueError, match="width"):
        MacroRegressionDataset(
            decision_months=(date(2000, 1, 1),),
            target_months=(date(2000, 2, 1),),
            features=np.zeros((1, 3)),
            targets=np.zeros(1),
            most_recent_target_values=np.zeros(1),
            series_ids=("FF3_Mkt-RF",),
            target_series_id="FF3_Mkt-RF",
            window=4,
            horizon=1,
        )


def test_chronological_split_separates_train_and_test_by_decision_month() -> None:
    dataset = build_macro_regression_dataset(
        _REAL_OBSERVATIONS, _FEATURE_SERIES_IDS, _TARGET_SERIES_ID, window=6, horizon=6
    )
    split_date = date(2000, 1, 1)
    train, test = chronological_split(dataset, split_date)
    assert all(m < split_date for m in train.decision_months)
    assert all(m >= split_date for m in test.decision_months)
    assert len(train.targets) + len(test.targets) == len(dataset.targets)


def test_chronological_split_rejects_a_split_emptying_either_side() -> None:
    dataset = build_macro_regression_dataset(
        _REAL_OBSERVATIONS, _FEATURE_SERIES_IDS, _TARGET_SERIES_ID, window=6, horizon=6
    )
    with pytest.raises(ValueError, match="non-empty"):
        chronological_split(dataset, date(2100, 1, 1))
    with pytest.raises(ValueError, match="non-empty"):
        chronological_split(dataset, date(1900, 1, 1))


def test_extract_target_history_matches_the_real_mkt_rf_series() -> None:
    months, values = extract_target_history(_REAL_OBSERVATIONS, "FF3_Mkt-RF")
    assert len(months) == len(values)
    real_by_month = {
        obs.observation_at: obs.value
        for obs in _REAL_OBSERVATIONS
        if obs.series_id == "FF3_Mkt-RF"
    }
    assert values[0] == pytest.approx(real_by_month[months[0]])
    assert values[-1] == pytest.approx(real_by_month[months[-1]])
    assert months == sorted(months)
