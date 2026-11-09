"""Point-in-time-safe dataset construction for RECESSIONNET (ECONOSIM-X/
PROMETHEUS-X addendum FP-06), built on the real Kenneth French monthly
factor series (DAT-05) as features and the real NBER recession
chronology (`recessionnet.labels`) as the classification target --
real market data and real historical labels, never synthetic (unlike
`macrocore.synthetic_data`, which exists because no real FRED
connector is available; a genuine real dataset already existed here
via `french_factors.py` and simply had not been pointed at a
classification task yet).

Leakage safeguard used here: a STRICT CHRONOLOGICAL split
(`chronological_split`) -- train only on decision months strictly
before the split date, test only on decision months at or after it.
This prevents the standard "future data used to fit/tune a model that
predicts the past" leakage. It is NOT the same safeguard as
`recessionnet.labels.recession_label_as_of`'s announcement-lag
discipline (whether a label would have been *knowable* at its own
decision time) -- that is demonstrated and tested separately in
`test_recessionnet_labels.py`. This dataset builder deliberately uses
the fully-resolved retrospective label (`labels.is_recession_month`)
for every sample, which is standard practice for a historical
backtest: section 07 of the addendum requires chronological splits and
vintage-aware FEATURES, not that every historical label be re-derived
under its own real-time announcement lag as well. Combining both
safeguards into one dataset is out of scope for this PR.

Feature scaling: each factor is divided by a FIXED constant (100.0,
converting a typical -20%..+20% monthly percentage return into a
roughly -0.2..+0.2 range suited to tanh-based encoders) rather than a
data-fitted standardization. This sidesteps the "fit scaling only on
the training window" leakage question entirely -- a fixed, data-
independent rescaling cannot leak information from future periods,
because it was never computed from this dataset's periods at all.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np

from prometheus.econosim.pit import MacroObservation
from prometheus.recessionnet.labels import RecessionPeriod, is_recession_month

_FIXED_FEATURE_SCALE = 100.0


@dataclass(frozen=True, slots=True)
class RecessionDataset:
    decision_months: tuple[date, ...]
    """The month each sample's feature window ends at -- the decision
    point the resulting prediction is dated to."""
    target_months: tuple[date, ...]
    """decision_months[i] + horizon months: the month the label
    describes."""
    features: np.ndarray
    """Shape (n_samples, window * len(series_ids)): each series'
    trailing `window` months, oldest first, concatenated series by
    series, then divided by `_FIXED_FEATURE_SCALE`."""
    labels: np.ndarray
    """Shape (n_samples,): 1.0 if target_months[i] is a real NBER
    contraction month (retrospective ground truth), else 0.0."""
    series_ids: tuple[str, ...]
    window: int
    horizon: int

    def __post_init__(self) -> None:
        n = len(self.decision_months)
        if len(self.target_months) != n or self.features.shape[0] != n or self.labels.shape[0] != n:
            raise ValueError("decision_months, target_months, features and labels must align")
        if self.features.shape[1] != self.window * len(self.series_ids):
            raise ValueError("features width must equal window * len(series_ids)")


class MissingSeriesError(ValueError):
    """Raised when a requested series is missing a value for a month
    another requested series does have -- building a feature matrix
    with silently-absent columns would be worse than failing loudly."""


def _build_monthly_matrix(
    observations: Sequence[MacroObservation], series_ids: Sequence[str]
) -> tuple[list[date], np.ndarray]:
    by_month: dict[date, dict[str, float]] = {}
    for obs in observations:
        if obs.series_id in series_ids:
            by_month.setdefault(obs.observation_at, {})[obs.series_id] = obs.value

    months = sorted(by_month)
    matrix = np.zeros((len(months), len(series_ids)))
    for i, month in enumerate(months):
        row = by_month[month]
        for j, series_id in enumerate(series_ids):
            if series_id not in row:
                raise MissingSeriesError(f"{series_id!r} has no observation for {month}")
            matrix[i, j] = row[series_id]
    return months, matrix


def build_recession_dataset(
    observations: Sequence[MacroObservation],
    series_ids: Sequence[str],
    recessions: Sequence[RecessionPeriod],
    *,
    window: int,
    horizon: int,
) -> RecessionDataset:
    if window < 1:
        raise ValueError("window must be a positive integer")
    if horizon < 1:
        raise ValueError("horizon must be a positive integer")

    months, matrix = _build_monthly_matrix(observations, series_ids)
    n_months = len(months)
    recessions_tuple = tuple(recessions)

    decision_months: list[date] = []
    target_months: list[date] = []
    feature_rows: list[np.ndarray] = []
    label_values: list[float] = []

    for i in range(window - 1, n_months - horizon):
        window_slice = matrix[i - window + 1 : i + 1, :]  # oldest-first
        feature_rows.append(window_slice.reshape(-1) / _FIXED_FEATURE_SCALE)
        decision_months.append(months[i])
        target_month = months[i + horizon]
        target_months.append(target_month)
        label_values.append(1.0 if is_recession_month(target_month, recessions_tuple) else 0.0)

    empty_features = np.zeros((0, window * len(series_ids)))
    return RecessionDataset(
        decision_months=tuple(decision_months),
        target_months=tuple(target_months),
        features=np.array(feature_rows) if feature_rows else empty_features,
        labels=np.array(label_values),
        series_ids=tuple(series_ids),
        window=window,
        horizon=horizon,
    )


def chronological_split(
    dataset: RecessionDataset, split_date: date
) -> tuple[RecessionDataset, RecessionDataset]:
    """Train = decision_months strictly before split_date; test =
    decision_months at or after it. Fails loudly (ValueError) if
    either side would be empty, rather than silently returning a
    useless split."""
    train_idx = [i for i, m in enumerate(dataset.decision_months) if m < split_date]
    test_idx = [i for i, m in enumerate(dataset.decision_months) if m >= split_date]
    if not train_idx or not test_idx:
        raise ValueError("split_date must leave both a non-empty train and test set")

    def _subset(indices: list[int]) -> RecessionDataset:
        return RecessionDataset(
            decision_months=tuple(dataset.decision_months[i] for i in indices),
            target_months=tuple(dataset.target_months[i] for i in indices),
            features=dataset.features[indices],
            labels=dataset.labels[indices],
            series_ids=dataset.series_ids,
            window=dataset.window,
            horizon=dataset.horizon,
        )

    return _subset(train_idx), _subset(test_idx)
