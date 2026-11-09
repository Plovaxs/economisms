"""Point-in-time-safe regression dataset for Q-MACRO (ECONOSIM-X/
PROMETHEUS-X addendum FP-05 "MACROCORE," and the user-supplied quantum
blueprint's other P0 engine, Q-MACRO).

This repository has no real GDP/CPI/unemployment series: DAT-02..04
(FRED-MD/QD, ALFRED) remain unimplemented -- no usable API key or live
connector exists in this environment, the same limitation
`recessionnet.labels` and `macrocore.synthetic_data` already disclose.
FP-05's full scope (a shared Transformer encoder forecasting GDP,
rates AND unemployment across multiple horizons) is NOT attempted
here. Q-MACRO's own minimal deliverable -- "a matched regression
benchmark" -- is: this module regresses h-months-ahead Mkt-RF (market
excess return) from trailing REAL Kenneth French factor history
(DAT-05), the classic equity-premium-predictability regression
studied extensively in empirical asset pricing (e.g. Welch & Goyal
2008; Campbell & Thompson 2008). "Rates" (the risk-free factor, RF, is
one of the predictors here) is the one FP-05 keyword this module can
honestly claim partial contact with; GDP and unemployment are not
touched at all.

Structurally mirrors `recessionnet.dataset.RecessionDataset` (same
windowed-feature convention, same FIXED, data-independent feature
scaling to sidestep train-window-fitting leakage, same
`build_monthly_series_matrix` shared helper) with one addition:
`most_recent_target_values`, the target series' OWN value at the
DECISION month (already realized, point-in-time safe), needed for a
persistence/naive baseline and for MASE's naive-error normalization --
RECESSIONNET had no equivalent concept since its target was a binary
label, not a continuous series with its own natural "last known value."
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np

from prometheus.data_ingestion.monthly_matrix import build_monthly_series_matrix
from prometheus.econosim.pit import MacroObservation

FIXED_FEATURE_SCALE = 100.0


@dataclass(frozen=True, slots=True)
class MacroRegressionDataset:
    decision_months: tuple[date, ...]
    target_months: tuple[date, ...]
    """decision_months[i] + horizon months: the month `targets[i]`
    describes."""
    features: np.ndarray
    """Shape (n_samples, window * len(series_ids)): each feature
    series' trailing `window` months, oldest first, concatenated
    series by series, divided by `FIXED_FEATURE_SCALE`."""
    targets: np.ndarray
    """Shape (n_samples,): the real target series' value at
    target_months[i], divided by the SAME fixed scale as `features`."""
    most_recent_target_values: np.ndarray
    """Shape (n_samples,): the target series' own value at
    decision_months[i] (already realized, point-in-time safe) --
    the naive/persistence forecast for `targets[i]`. Same scale as
    `targets`."""
    series_ids: tuple[str, ...]
    target_series_id: str
    window: int
    horizon: int

    def __post_init__(self) -> None:
        n = len(self.decision_months)
        if (
            len(self.target_months) != n
            or self.features.shape[0] != n
            or self.targets.shape[0] != n
            or self.most_recent_target_values.shape[0] != n
        ):
            raise ValueError(
                "decision_months, target_months, features, targets and "
                "most_recent_target_values must align"
            )
        if self.features.shape[1] != self.window * len(self.series_ids):
            raise ValueError("features width must equal window * len(series_ids)")


def build_macro_regression_dataset(
    observations: Sequence[MacroObservation],
    feature_series_ids: Sequence[str],
    target_series_id: str,
    *,
    window: int,
    horizon: int,
) -> MacroRegressionDataset:
    if window < 1:
        raise ValueError("window must be a positive integer")
    if horizon < 1:
        raise ValueError("horizon must be a positive integer")

    all_series_ids = tuple(dict.fromkeys((*feature_series_ids, target_series_id)))
    months, matrix = build_monthly_series_matrix(observations, all_series_ids)
    target_index = all_series_ids.index(target_series_id)
    feature_indices = [all_series_ids.index(sid) for sid in feature_series_ids]

    n_months = len(months)
    decision_months: list[date] = []
    target_months: list[date] = []
    feature_rows: list[np.ndarray] = []
    target_values: list[float] = []
    most_recent_values: list[float] = []

    for i in range(window - 1, n_months - horizon):
        window_slice = matrix[i - window + 1 : i + 1, feature_indices]
        feature_rows.append(window_slice.reshape(-1) / FIXED_FEATURE_SCALE)
        decision_months.append(months[i])
        target_month_index = i + horizon
        target_months.append(months[target_month_index])
        target_values.append(matrix[target_month_index, target_index] / FIXED_FEATURE_SCALE)
        most_recent_values.append(matrix[i, target_index] / FIXED_FEATURE_SCALE)

    empty_features = np.zeros((0, window * len(feature_series_ids)))
    return MacroRegressionDataset(
        decision_months=tuple(decision_months),
        target_months=tuple(target_months),
        features=np.array(feature_rows) if feature_rows else empty_features,
        targets=np.array(target_values),
        most_recent_target_values=np.array(most_recent_values),
        series_ids=tuple(feature_series_ids),
        target_series_id=target_series_id,
        window=window,
        horizon=horizon,
    )


def chronological_split(
    dataset: MacroRegressionDataset, split_date: date
) -> tuple[MacroRegressionDataset, MacroRegressionDataset]:
    """Train = decision_months strictly before split_date; test =
    decision_months at or after it. Fails loudly if either side would
    be empty."""
    train_idx = [i for i, m in enumerate(dataset.decision_months) if m < split_date]
    test_idx = [i for i, m in enumerate(dataset.decision_months) if m >= split_date]
    if not train_idx or not test_idx:
        raise ValueError("split_date must leave both a non-empty train and test set")

    def _subset(indices: list[int]) -> MacroRegressionDataset:
        return MacroRegressionDataset(
            decision_months=tuple(dataset.decision_months[i] for i in indices),
            target_months=tuple(dataset.target_months[i] for i in indices),
            features=dataset.features[indices],
            targets=dataset.targets[indices],
            most_recent_target_values=dataset.most_recent_target_values[indices],
            series_ids=dataset.series_ids,
            target_series_id=dataset.target_series_id,
            window=dataset.window,
            horizon=dataset.horizon,
        )

    return _subset(train_idx), _subset(test_idx)


def extract_target_history(
    observations: Sequence[MacroObservation], target_series_id: str
) -> tuple[list[date], np.ndarray]:
    """The target series' own full chronological (unscaled) history --
    used by `quantum_benchmark.run_qmacro_benchmark` to refit the
    classical AR(p) baseline at each real calendar month, which needs
    the raw per-month series, not the windowed feature matrix above."""
    months, matrix = build_monthly_series_matrix(observations, (target_series_id,))
    return months, matrix[:, 0]
