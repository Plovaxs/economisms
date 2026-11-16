import calendar
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from prometheus.data_ingestion.kaggle_macro import (
    KAGGLE_SERIES_IDS,
    load_kaggle_us_macro_observations,
)
from prometheus.macrocore.multihorizon_dataset import (
    build_multihorizon_dataset,
    chronological_split3,
    in_sample_naive_mae,
)

_CSV_PATH = Path(__file__).resolve().parents[2] / "data_cache" / "kaggle_us_macro_monthly.csv"
_TARGET_SERIES_IDS = ("KAGGLE_GDP_YOY", "KAGGLE_CLAIMS_YOY", "KAGGLE_FEDFUNDS")
_HORIZONS = (1, 3, 6)
_WINDOW = 6

_OBSERVATIONS = load_kaggle_us_macro_observations(_CSV_PATH)


def test_build_multihorizon_dataset_produces_correctly_shaped_windows() -> None:
    dataset = build_multihorizon_dataset(
        _OBSERVATIONS, KAGGLE_SERIES_IDS, _TARGET_SERIES_IDS, window=_WINDOW, horizons=_HORIZONS
    )
    n = dataset.features.shape[0]
    assert n > 100
    assert dataset.features.shape[1] == _WINDOW * len(KAGGLE_SERIES_IDS)
    assert dataset.targets.shape == (n, len(_TARGET_SERIES_IDS) * len(_HORIZONS))
    assert dataset.most_recent_target_values.shape == (n, len(_TARGET_SERIES_IDS))
    assert len(dataset.decision_months) == n


def test_target_column_matches_the_real_series_at_decision_month_plus_horizon() -> None:
    dataset = build_multihorizon_dataset(
        _OBSERVATIONS, KAGGLE_SERIES_IDS, _TARGET_SERIES_IDS, window=_WINDOW, horizons=_HORIZONS
    )
    real_gdp_by_month = {
        o.observation_at: o.value for o in _OBSERVATIONS if o.series_id == "KAGGLE_GDP_YOY"
    }
    gdp_index = _TARGET_SERIES_IDS.index("KAGGLE_GDP_YOY")
    column = dataset.target_column(gdp_index, 3)
    # Spot-check a handful of rows against the real, undisguised source value.
    for i in range(0, len(dataset.decision_months), 37):
        decision_month = dataset.decision_months[i]
        year = decision_month.year + (decision_month.month + 3 - 1) // 12
        month = (decision_month.month + 3 - 1) % 12 + 1
        target_month = date(year, month, calendar.monthrange(year, month)[1])
        assert column[i] == pytest.approx(real_gdp_by_month[target_month] / 100.0)


def test_most_recent_target_value_is_the_real_series_at_the_decision_month() -> None:
    dataset = build_multihorizon_dataset(
        _OBSERVATIONS, KAGGLE_SERIES_IDS, _TARGET_SERIES_IDS, window=_WINDOW, horizons=_HORIZONS
    )
    real_fedfunds_by_month = {
        o.observation_at: o.value for o in _OBSERVATIONS if o.series_id == "KAGGLE_FEDFUNDS"
    }
    rate_index = _TARGET_SERIES_IDS.index("KAGGLE_FEDFUNDS")
    for i in range(0, len(dataset.decision_months), 41):
        decision_month = dataset.decision_months[i]
        assert dataset.most_recent_target_values[i, rate_index] == pytest.approx(
            real_fedfunds_by_month[decision_month] / 100.0
        )


def test_rejects_misaligned_construction() -> None:
    dataset = build_multihorizon_dataset(
        _OBSERVATIONS, KAGGLE_SERIES_IDS, _TARGET_SERIES_IDS, window=_WINDOW, horizons=_HORIZONS
    )
    with pytest.raises(ValueError, match="features width"):
        type(dataset)(
            decision_months=dataset.decision_months,
            features=dataset.features[:, :-1],
            targets=dataset.targets,
            most_recent_target_values=dataset.most_recent_target_values,
            feature_series_ids=dataset.feature_series_ids,
            target_series_ids=dataset.target_series_ids,
            horizons=dataset.horizons,
            window=dataset.window,
        )


def test_chronological_split3_covers_every_row_exactly_once_and_respects_dates() -> None:
    dataset = build_multihorizon_dataset(
        _OBSERVATIONS, KAGGLE_SERIES_IDS, _TARGET_SERIES_IDS, window=_WINDOW, horizons=_HORIZONS
    )
    train, validation, test = chronological_split3(
        dataset, date(2001, 1, 1), date(2008, 1, 1)
    )
    assert len(train.decision_months) + len(validation.decision_months) + len(
        test.decision_months
    ) == len(dataset.decision_months)
    assert all(m < date(2001, 1, 1) for m in train.decision_months)
    assert all(date(2001, 1, 1) <= m < date(2008, 1, 1) for m in validation.decision_months)
    assert all(m >= date(2008, 1, 1) for m in test.decision_months)
    assert len(train.decision_months) > 0
    assert len(validation.decision_months) > 0
    assert len(test.decision_months) > 0


def test_chronological_split3_rejects_a_split_leaving_a_side_empty() -> None:
    dataset = build_multihorizon_dataset(
        _OBSERVATIONS, KAGGLE_SERIES_IDS, _TARGET_SERIES_IDS, window=_WINDOW, horizons=_HORIZONS
    )
    with pytest.raises(ValueError):
        chronological_split3(dataset, date(1900, 1, 1), date(1900, 2, 1))


def test_in_sample_naive_mae_matches_a_hand_computed_one_step_difference() -> None:
    dataset = build_multihorizon_dataset(
        _OBSERVATIONS, KAGGLE_SERIES_IDS, _TARGET_SERIES_IDS, window=_WINDOW, horizons=_HORIZONS
    )
    train, _validation, _test = chronological_split3(dataset, date(2001, 1, 1), date(2008, 1, 1))
    gdp_index = _TARGET_SERIES_IDS.index("KAGGLE_GDP_YOY")
    expected = float(np.mean(np.abs(np.diff(train.most_recent_target_values[:, gdp_index]))))
    assert in_sample_naive_mae(train, gdp_index) == pytest.approx(expected)
