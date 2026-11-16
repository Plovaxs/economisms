"""Point-in-time-safe, multi-target, multi-horizon windowed dataset for
MACROCORE's full FP-05 deliverable: "a shared Transformer encoder
forecasting GDP, rates AND unemployment across multiple horizons."

`macrocore.regression_dataset` (Q-MACRO, PR-143) already builds this
exact windowed-feature convention for ONE target series at ONE horizon,
honestly scoped to Mkt-RF only because at the time this repository had
no real GDP/unemployment series at all. That gap has since been closed
by `data_ingestion.kaggle_macro` (FP-06, PR-145): real GDP growth
(`KAGGLE_GDP_YOY`), real unemployment-claims growth (`KAGGLE_CLAIMS_YOY`,
the same honest "unemployment" substitute FP-06's own checklist entry
already establishes), and a real policy rate (`KAGGLE_FEDFUNDS`) have
been sitting in this repository's committed data cache ever since,
just never wired into a shared multi-target encoder. This module does
that wiring: same `build_monthly_series_matrix` shared helper, same
FIXED, data-independent feature scale (imported from
`regression_dataset`, not redefined) to sidestep train-window-fitting
leakage, generalized to several target series and several horizons
scored jointly from ONE shared feature window per decision month.

Still not claimed as DAT-02/03 (FRED-MD/QD, ALFRED vintages): FRED and
ALFRED remain unreachable in this environment (see
`docs/RESULTS_AND_LIMITATIONS.md`'s "Known limitations"); the Kaggle
mirror used here is real data honestly substituted, the same
disclosure FP-06/FP-07 already make for their own sources.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np

from prometheus.data_ingestion.monthly_matrix import build_monthly_series_matrix
from prometheus.econosim.pit import MacroObservation
from prometheus.macrocore.regression_dataset import FIXED_FEATURE_SCALE

__all__ = [
    "FIXED_FEATURE_SCALE",
    "MultihorizonDataset",
    "build_multihorizon_dataset",
    "chronological_split3",
    "in_sample_naive_mae",
]


@dataclass(frozen=True, slots=True)
class MultihorizonDataset:
    decision_months: tuple[date, ...]
    features: np.ndarray
    """Shape (n_samples, window * len(feature_series_ids)): every
    feature series' trailing `window` months, oldest first, series by
    series, divided by `FIXED_FEATURE_SCALE`. ONE shared window per
    decision month feeds every target and every horizon below --
    the literal "shared encoder" premise."""
    targets: np.ndarray
    """Shape (n_samples, len(target_series_ids) * len(horizons)):
    column order is target-major, horizon-minor (target 0 at every
    horizon in `horizons` order, then target 1, ...). Same fixed scale
    as `features`."""
    most_recent_target_values: np.ndarray
    """Shape (n_samples, len(target_series_ids)): each target series'
    OWN value at the decision month (already realized, point-in-time
    safe) -- the persistence baseline, and (since consecutive rows are
    exactly one calendar month apart by construction) the raw material
    for each target's in-sample one-step naive MAE."""
    feature_series_ids: tuple[str, ...]
    target_series_ids: tuple[str, ...]
    horizons: tuple[int, ...]
    window: int

    def __post_init__(self) -> None:
        n = len(self.decision_months)
        if self.features.shape[0] != n or self.targets.shape[0] != n:
            raise ValueError("decision_months, features and targets must align")
        if self.most_recent_target_values.shape[0] != n:
            raise ValueError("most_recent_target_values must align with decision_months")
        if self.features.shape[1] != self.window * len(self.feature_series_ids):
            raise ValueError("features width must equal window * len(feature_series_ids)")
        if self.targets.shape[1] != len(self.target_series_ids) * len(self.horizons):
            raise ValueError("targets width must equal len(target_series_ids) * len(horizons)")
        if self.most_recent_target_values.shape[1] != len(self.target_series_ids):
            raise ValueError("most_recent_target_values width must equal len(target_series_ids)")

    def target_column(self, target_index: int, horizon: int) -> np.ndarray:
        """The single (n_samples,) column for one (target, horizon)
        pair -- the shape every per-series/per-horizon metric needs."""
        horizon_index = self.horizons.index(horizon)
        column = target_index * len(self.horizons) + horizon_index
        result: np.ndarray = self.targets[:, column]
        return result


def build_multihorizon_dataset(
    observations: Sequence[MacroObservation],
    feature_series_ids: Sequence[str],
    target_series_ids: Sequence[str],
    *,
    window: int,
    horizons: Sequence[int],
) -> MultihorizonDataset:
    if window < 1:
        raise ValueError("window must be a positive integer")
    if not horizons or any(h < 1 for h in horizons):
        raise ValueError("horizons must be a non-empty sequence of positive integers")
    if not target_series_ids:
        raise ValueError("target_series_ids must be non-empty")

    all_series_ids = tuple(dict.fromkeys((*feature_series_ids, *target_series_ids)))
    months, matrix = build_monthly_series_matrix(observations, all_series_ids)
    feature_indices = [all_series_ids.index(sid) for sid in feature_series_ids]
    target_indices = [all_series_ids.index(sid) for sid in target_series_ids]

    max_h = max(horizons)
    n_months = len(months)

    decision_months: list[date] = []
    feature_rows: list[np.ndarray] = []
    target_rows: list[np.ndarray] = []
    most_recent_rows: list[np.ndarray] = []

    for i in range(window - 1, n_months - max_h):
        window_slice = matrix[i - window + 1 : i + 1, feature_indices]
        feature_rows.append(window_slice.reshape(-1) / FIXED_FEATURE_SCALE)
        decision_months.append(months[i])

        target_row = np.array(
            [
                matrix[i + h, target_index] / FIXED_FEATURE_SCALE
                for target_index in target_indices
                for h in horizons
            ]
        )
        target_rows.append(target_row)
        most_recent_rows.append(matrix[i, target_indices] / FIXED_FEATURE_SCALE)

    return MultihorizonDataset(
        decision_months=tuple(decision_months),
        features=np.array(feature_rows),
        targets=np.array(target_rows),
        most_recent_target_values=np.array(most_recent_rows),
        feature_series_ids=tuple(feature_series_ids),
        target_series_ids=tuple(target_series_ids),
        horizons=tuple(horizons),
        window=window,
    )


def chronological_split3(
    dataset: MultihorizonDataset, validation_start: date, test_start: date
) -> tuple[MultihorizonDataset, MultihorizonDataset, MultihorizonDataset]:
    """Train = decision_months strictly before `validation_start`;
    validation = [validation_start, test_start); test = decision_months
    at or after `test_start`. Fails loudly if any split would be
    empty -- the same discipline `regression_dataset.chronological_split`
    already applies to the single-target case."""
    if not validation_start < test_start:
        raise ValueError("validation_start must be strictly before test_start")
    train_idx = [i for i, m in enumerate(dataset.decision_months) if m < validation_start]
    val_idx = [
        i for i, m in enumerate(dataset.decision_months) if validation_start <= m < test_start
    ]
    test_idx = [i for i, m in enumerate(dataset.decision_months) if m >= test_start]
    if not train_idx or not val_idx or not test_idx:
        raise ValueError("validation_start/test_start must leave all three splits non-empty")

    def _subset(indices: list[int]) -> MultihorizonDataset:
        return MultihorizonDataset(
            decision_months=tuple(dataset.decision_months[i] for i in indices),
            features=dataset.features[indices],
            targets=dataset.targets[indices],
            most_recent_target_values=dataset.most_recent_target_values[indices],
            feature_series_ids=dataset.feature_series_ids,
            target_series_ids=dataset.target_series_ids,
            horizons=dataset.horizons,
            window=dataset.window,
        )

    return _subset(train_idx), _subset(val_idx), _subset(test_idx)


def in_sample_naive_mae(train: MultihorizonDataset, target_index: int) -> float:
    """The MASE denominator for one target series: the train-only mean
    absolute one-step (consecutive-month) naive change, read off
    `most_recent_target_values` (consecutive rows are exactly one
    calendar month apart by construction, so this is a real one-step
    series difference, not an artifact of the horizon)."""
    column = train.most_recent_target_values[:, target_index]
    if len(column) < 2:
        raise ValueError("train split must have at least 2 rows to compute a naive step error")
    return float(np.mean(np.abs(np.diff(column))))
