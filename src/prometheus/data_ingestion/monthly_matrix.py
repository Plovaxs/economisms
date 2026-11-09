"""Build a chronological (months x series) matrix from a flat
collection of `MacroObservation`s -- shared by any windowed-feature
dataset builder that needs several series aligned to the same set of
months (originally written for `recessionnet.dataset`; promoted here
once `macrocore.regression_dataset` needed the identical logic, rather
than duplicating or privately cross-importing it).

Deliberately takes a plain `Sequence[MacroObservation]` the caller
already holds, never a `PointInTimeStore` accessor -- matching
`econosim.pit`'s own stance that there is no "give me everything"
query on the store itself.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import numpy as np

from prometheus.econosim.pit import MacroObservation


class MissingSeriesError(ValueError):
    """Raised when a requested series is missing a value for a month
    another requested series does have -- building a feature matrix
    with silently-absent columns would be worse than failing loudly."""


def build_monthly_series_matrix(
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
