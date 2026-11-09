from dataclasses import FrozenInstanceError
from datetime import date

import numpy as np
import pytest

from prometheus.econosim.pit import FutureDataError, MacroObservation, build_feature_vector
from prometheus.neural_sde.dataset import (
    FittedScaler,
    build_point_in_time_store,
    build_transition_dataset,
    chronological_split,
    fit_scaler,
)
from prometheus.neural_sde.design import NeuralSDEDesignSpec

_SPEC = NeuralSDEDesignSpec(
    state_series_ids=("S1", "S2"),
    state_units=("pct", "pct"),
    regime_series_ids=("R1",),
    regime_units=("pct",),
    time_unit="months",
)


def _months(n: int) -> list[date]:
    return [date(2020, m, 28) for m in range(1, n + 1)]


def _observations(n: int) -> list[MacroObservation]:
    obs: list[MacroObservation] = []
    for i, month in enumerate(_months(n)):
        for series_id, value in (("S1", float(i)), ("S2", float(10 * i)), ("R1", float(i) + 0.5)):
            obs.append(
                MacroObservation(
                    series_id=series_id,
                    observation_at=month,
                    published_at=month,
                    value=value,
                )
            )
    return obs


def test_build_transition_dataset_reads_consecutive_months_correctly() -> None:
    store = build_point_in_time_store(_observations(4))
    examples = build_transition_dataset(store, _SPEC, _months(4))
    assert len(examples) == 3
    first = examples[0]
    assert first.state == (0.0, 0.0)
    assert first.regime == (0.5,)
    assert first.next_state == (1.0, 10.0)
    assert first.decision_time == date(2020, 1, 28)
    assert first.next_time == date(2020, 2, 28)
    assert first.t_scaled == 0.0
    assert examples[-1].t_scaled == 2.0


def test_build_transition_dataset_rejects_too_few_months() -> None:
    store = build_point_in_time_store(_observations(1))
    with pytest.raises(ValueError, match="at least two"):
        build_transition_dataset(store, _SPEC, _months(1))


def test_build_transition_dataset_rejects_unsorted_months() -> None:
    store = build_point_in_time_store(_observations(3))
    months = list(reversed(_months(3)))
    with pytest.raises(ValueError, match="sorted"):
        build_transition_dataset(store, _SPEC, months)


def test_known_at_discipline_rejects_a_direct_future_data_request() -> None:
    """NSD-05's core guarantee, exercised directly and independently of
    `build_transition_dataset`: a feature request for a later month than
    the decision time raises `FutureDataError` -- the same primitive
    `build_transition_dataset` relies on internally."""
    store = build_point_in_time_store(_observations(3))
    decision_time = _months(3)[0]
    future_month = _months(3)[2]
    with pytest.raises(FutureDataError):
        build_feature_vector(store, [("S1", future_month)], decision_time)


def test_fit_scaler_recovers_known_mean_and_std() -> None:
    train = np.array([[0.0, 1.0], [2.0, 3.0], [4.0, 5.0]])
    scaler = fit_scaler(train)
    assert scaler.mean == pytest.approx((2.0, 3.0))
    assert scaler.std == pytest.approx((np.std(train[:, 0]), np.std(train[:, 1])))


def test_fit_scaler_rejects_empty_input() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        fit_scaler(np.empty((0, 2)))


def test_fit_scaler_floors_a_near_zero_std_to_avoid_division_blowup() -> None:
    train = np.array([[5.0], [5.0], [5.0]])
    scaler = fit_scaler(train)
    assert scaler.std == pytest.approx((1.0,))


def test_fitted_scaler_is_frozen_so_validation_data_cannot_mutate_it() -> None:
    """NSD-06: there is no `.fit` method to call on validation/test data
    at all, and attempting to assign to the dataclass's own fields
    (the only other way state could change) raises, structurally
    proving the scaler cannot drift after being fit once."""
    scaler = fit_scaler(np.array([[1.0], [2.0], [3.0]]))
    with pytest.raises(FrozenInstanceError):
        scaler.mean = (0.0,)  # type: ignore[misc]
    assert not hasattr(FittedScaler, "fit")
    assert not hasattr(FittedScaler, "fit_transform")


def test_fitted_scaler_transform_matches_manual_computation() -> None:
    scaler = FittedScaler(mean=(1.0, 2.0), std=(2.0, 4.0))
    result = scaler.transform(np.array([[3.0, 10.0]]))
    assert result == pytest.approx(np.array([[1.0, 2.0]]))


def test_chronological_split_preserves_time_order_and_does_not_shuffle() -> None:
    store = build_point_in_time_store(_observations(10))
    examples = build_transition_dataset(store, _SPEC, _months(10))
    train, validation = chronological_split(examples, train_fraction=0.7)
    assert train + validation == examples
    assert [e.t_scaled for e in train] == sorted(e.t_scaled for e in train)
    assert [e.t_scaled for e in validation] == sorted(e.t_scaled for e in validation)
    assert train[-1].t_scaled < validation[0].t_scaled


def test_chronological_split_rejects_fraction_outside_open_interval() -> None:
    store = build_point_in_time_store(_observations(5))
    examples = build_transition_dataset(store, _SPEC, _months(5))
    with pytest.raises(ValueError, match="train_fraction"):
        chronological_split(examples, train_fraction=0.0)
    with pytest.raises(ValueError, match="train_fraction"):
        chronological_split(examples, train_fraction=1.0)
