"""NSD-05/NSD-06: point-in-time transition dataset and train-only
normalization.

NSD-05 ("regime-conditioned model with known-at time -- feature
timestamps checked at every training/test event") is satisfied
structurally, not by convention: every single feature value used to
build a `TransitionExample` is read through
`econosim.pit.build_feature_vector`, which raises `FutureDataError`
(`econosim.pit`) if the requested (series_id, observation_at) is not
yet eligible as of the given decision time. There is no code path in
this module that reads a `MacroObservation.value` directly.

NSD-06 ("train-only preprocessing and imputation -- validation/test
never changes fitted normalization state") is satisfied structurally
too: `FittedScaler` is a frozen dataclass with no `fit` method at all,
only `transform`. There is no way to call it in a way that mutates its
stored mean/std, which is the real-FRED-grade reason this is safer than
a mutable scaler object with a documented-but-unenforced "don't call
fit twice" convention.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

from prometheus.econosim.pit import MacroObservation, PointInTimeStore, build_feature_vector
from prometheus.neural_sde.design import NeuralSDEDesignSpec


def build_point_in_time_store(observations: list[MacroObservation]) -> PointInTimeStore:
    store = PointInTimeStore()
    for observation in observations:
        store.record(observation)
    return store


@dataclass(frozen=True, slots=True)
class TransitionExample:
    t_scaled: float
    state: tuple[float, ...]
    regime: tuple[float, ...]
    next_state: tuple[float, ...]
    decision_time: date
    next_time: date


def build_transition_dataset(
    store: PointInTimeStore, spec: NeuralSDEDesignSpec, months: list[date]
) -> list[TransitionExample]:
    """`months` must be the sorted, deduplicated list of observation
    months to build consecutive (month[i], month[i+1]) transitions from.
    Every feature read goes through `build_feature_vector`, so a bug
    that accidentally tried to read month[i+1]'s data while building
    month[i]'s features would raise `FutureDataError`, not silently
    succeed -- see `test_neural_sde_dataset.py`'s direct leakage-attempt
    test for the same guarantee exercised in isolation."""
    if len(months) < 2:
        raise ValueError("months must contain at least two observation months")
    if months != sorted(months):
        raise ValueError("months must be sorted ascending")

    examples: list[TransitionExample] = []
    for i in range(len(months) - 1):
        t = months[i]
        t_next = months[i + 1]
        state_requests = [(sid, t) for sid in spec.state_series_ids]
        regime_requests = [(sid, t) for sid in spec.regime_series_ids]
        features = build_feature_vector(store, state_requests + regime_requests, t)
        next_features = build_feature_vector(
            store, [(sid, t_next) for sid in spec.state_series_ids], t_next
        )
        examples.append(
            TransitionExample(
                t_scaled=float(i),
                state=tuple(features[sid] for sid in spec.state_series_ids),
                regime=tuple(features[sid] for sid in spec.regime_series_ids),
                next_state=tuple(next_features[sid] for sid in spec.state_series_ids),
                decision_time=t,
                next_time=t_next,
            )
        )
    return examples


@dataclass(frozen=True, slots=True)
class FittedScaler:
    """Immutable: has no `fit`/`fit_transform` method, only `transform`,
    so there is no call that could re-fit it on validation or test
    data (NSD-06)."""

    mean: tuple[float, ...]
    std: tuple[float, ...]

    def transform(self, values: np.ndarray) -> np.ndarray:
        values = np.asarray(values, dtype=float)
        if values.shape[-1] != len(self.mean):
            raise ValueError(
                f"last dimension {values.shape[-1]} does not match fitted dimension "
                f"{len(self.mean)}"
            )
        result: np.ndarray = (values - np.array(self.mean)) / np.array(self.std)
        return result


def fit_scaler(train_values: np.ndarray) -> FittedScaler:
    """The ONLY place a mean/std is ever computed in this package --
    callers must pass the TRAINING split alone; nothing downstream can
    refit it."""
    train_values = np.asarray(train_values, dtype=float)
    if train_values.shape[0] == 0:
        raise ValueError("train_values must be non-empty")
    mean = train_values.mean(axis=0)
    std = train_values.std(axis=0)
    std = np.where(std < 1e-8, 1.0, std)
    return FittedScaler(mean=tuple(mean.tolist()), std=tuple(std.tolist()))


def chronological_split(
    examples: list[TransitionExample], train_fraction: float
) -> tuple[list[TransitionExample], list[TransitionExample]]:
    """Splits by TIME ORDER, not randomly -- shuffling a time series
    before a train/validation split would let validation-period dynamics
    leak into which epoch gets selected, exactly the mistake
    `econosim.pit` exists to prevent elsewhere in this repository."""
    if not 0.0 < train_fraction < 1.0:
        raise ValueError("train_fraction must be in (0, 1)")
    cut = int(len(examples) * train_fraction)
    cut = max(1, min(cut, len(examples) - 1))
    return examples[:cut], examples[cut:]
