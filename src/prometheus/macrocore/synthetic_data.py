"""A clearly-labeled SYNTHETIC macro data generator (ECONOSIM-X/
PROMETHEUS-X addendum: "Synthetic generators ... Always label synthetic,
preserve source config and seed"; AUD-08's synthetic-vs-empirical
disclosure discipline).

No real FRED-MD/FRED-QD/ALFRED/Treasury/French-factor data is ingested
anywhere in this repository (DAT-02..DAT-05 remain unimplemented and
unlicensed). This module exists so the point-in-time machinery
(`econosim.pit`) and the classical forecasting baselines
(`macrocore.baselines`) have *something* realistic-shaped to run against
while that real ingestion work remains open -- every observation this
module produces carries `source_license="synthetic-generated-for-testing-
only"` and `quality_flags=("synthetic",)`, and `generate_synthetic_macro_
var_series` additionally returns the raw ground-truth array directly (not
only through the point-in-time store) specifically so a caller can never
be left wondering whether a value came from a real source -- there is no
real source in this module at all.

Simulates a VAR(p) process (reusing the same model family
`macrocore.baselines.fit_vector_autoregression` would later estimate) at
monthly periods, with an explicit publication lag between when a period
ends (`observation_at`) and when its value becomes public
(`published_at`) -- a deliberately simplified but genuine point-in-time
structure, not an instantaneous reveal.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from prometheus.core.calendar import add_months
from prometheus.econosim.pit import MacroObservation, PointInTimeStore

SYNTHETIC_SOURCE_LICENSE = "synthetic-generated-for-testing-only"
SYNTHETIC_QUALITY_FLAG = "synthetic"


@dataclass(frozen=True, slots=True)
class SyntheticMacroPanel:
    store: PointInTimeStore
    series_ids: list[str]
    observation_dates: list[date]
    known_at_dates: list[date]
    """known_at_dates[i] is the as-of date at which observation_dates[i]'s
    value for every series becomes eligible (= observation_at +
    publication_lag_days here, since every series in this generator
    shares one lag)."""
    levels: np.ndarray
    """Shape (n_periods, n_series), the ground-truth values -- provided
    directly for test/backtest convenience; production backtests must
    still read through `store` (see `macrocore.evaluation`), not this
    array, so that leakage would be physically impossible even if a
    backtest's own indexing were buggy."""


def generate_synthetic_macro_var_series(
    series_ids: list[str],
    phi_matrices: list[np.ndarray],
    sigma: np.ndarray,
    n_periods: int,
    start_date: date,
    publication_lag_days: int,
    rng: np.random.Generator,
    intercept: np.ndarray | None = None,
) -> SyntheticMacroPanel:
    k = len(series_ids)
    if k < 1:
        raise ValueError("series_ids must be non-empty")
    if any(phi.shape != (k, k) for phi in phi_matrices):
        raise ValueError("every phi matrix must have shape (n_series, n_series)")
    if sigma.shape != (k, k):
        raise ValueError("sigma must have shape (n_series, n_series)")
    if n_periods < 1:
        raise ValueError("n_periods must be a positive integer")
    if publication_lag_days < 0:
        raise ValueError("publication_lag_days must be non-negative")

    order = len(phi_matrices)
    drift = intercept if intercept is not None else np.zeros(k)
    cholesky = np.linalg.cholesky(sigma)

    levels = np.zeros((n_periods, k))
    for t in range(n_periods):
        value = drift.copy()
        for lag in range(1, order + 1):
            if t - lag >= 0:
                value = value + phi_matrices[lag - 1] @ levels[t - lag]
        value = value + cholesky @ rng.standard_normal(k)
        levels[t] = value

    observation_dates = [add_months(start_date, i + 1) for i in range(n_periods)]
    known_at_dates = [d + timedelta(days=publication_lag_days) for d in observation_dates]

    store = PointInTimeStore()
    for t in range(n_periods):
        for series_index, series_id in enumerate(series_ids):
            store.record(
                MacroObservation(
                    series_id=series_id,
                    observation_at=observation_dates[t],
                    published_at=known_at_dates[t],
                    value=float(levels[t, series_index]),
                    source_license=SYNTHETIC_SOURCE_LICENSE,
                    quality_flags=(SYNTHETIC_QUALITY_FLAG,),
                )
            )

    return SyntheticMacroPanel(
        store=store,
        series_ids=list(series_ids),
        observation_dates=observation_dates,
        known_at_dates=known_at_dates,
        levels=levels,
    )
