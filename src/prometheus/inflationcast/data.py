"""Real, point-in-time-safe mixed-frequency CPI nowcasting dataset.

`load_cpi_observations` loads the committed real BLS CPI-U series
(`data_cache/us_cpi_monthly.csv`) with its own REAL, undisguised ~15-day
publication lag (`published_at = observation_at + 15 days`) -- unlike
every Kaggle-derived series in this repository, which was already
re-keyed to its own effective availability date before being committed
(see `data_ingestion.kaggle_macro`'s own docstring). This is
deliberate: CPI is both a predictor (prior months) and the nowcast
target (the current month), so it is the one series whose masking
behavior actually needs to vary within this dataset, and the one
series genuinely demonstrating "information-release masks" in action.

`build_inflationcast_dataset` builds one example per nowcastable target
month: decision date = that month's own last day (the real-world
moment a nowcaster would be standing at, two weeks before the
official release). For every requested series and every month in the
trailing window, `PointInTimeStore.as_of` is queried AT that decision
date -- never the wall-clock "true" value -- so the current month's own
CPI slot is masked (zero-filled, mask=0) by construction every single
time, the same way it would be for a real forecaster. The true,
eventually-published value is fetched separately, from a date safely
past the real publication lag, and used only as the training label,
never as a model input.
"""

from __future__ import annotations

import calendar
import csv
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from prometheus.econosim.pit import MacroObservation, PointInTimeStore

CPI_SOURCE_LICENSE = "U.S. government work -- public domain"
CPI_SOURCE_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/CUUR0000SA0"
CPI_SERIES_ID = "CPI_YOY"
CPI_PUBLICATION_LAG_DAYS = 15
"""A FIXED, documented assumption (BLS's own well-publicized release
schedule), not fetched real per-release vintage data -- the identical
honest disclosure `data_cache/kaggle_us_macro_monthly.meta.json`
already makes for its own five series. See
`data_cache/us_cpi_monthly.meta.json` for the full provenance."""

PREDICTOR_SERIES_IDS: tuple[str, ...] = (
    "KAGGLE_GDP_YOY",
    "KAGGLE_CLAIMS_YOY",
    "KAGGLE_FEDFUNDS",
    "KAGGLE_M2_YOY",
    "KAGGLE_NASDAQ_YOY",
)
ALL_SERIES_IDS: tuple[str, ...] = (CPI_SERIES_ID, *PREDICTOR_SERIES_IDS)


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def load_cpi_observations(path: Path) -> list[MacroObservation]:
    """`data_cache/us_cpi_monthly.csv` has one row per real calendar
    month with a non-empty `CPI_YOY` value (the real 2025-10 BLS gap --
    "lapse in appropriations" -- is simply absent from the file, not
    interpolated); this loader records exactly those months, each
    with a real, undisguised 15-day publication lag."""
    observations: list[MacroObservation] = []
    with path.open() as f:
        for row in csv.DictReader(f):
            if not row["CPI_YOY"]:
                continue
            year, month = int(row["date"][:4]), int(row["date"][5:7])
            observation_at = _month_end(year, month)
            observations.append(
                MacroObservation(
                    series_id=CPI_SERIES_ID,
                    observation_at=observation_at,
                    published_at=observation_at + timedelta(days=CPI_PUBLICATION_LAG_DAYS),
                    value=float(row["CPI_YOY"]),
                    source_url=CPI_SOURCE_URL,
                    source_license=CPI_SOURCE_LICENSE,
                    frequency="M",
                )
            )
    return observations


@dataclass(frozen=True, slots=True)
class InflationNowcastExample:
    target_month: date
    """The real calendar month this example nowcasts CPI_YOY for."""
    decision_date: date
    """The real-world moment the nowcast is made at -- `target_month`'s
    own last day, strictly before CPI's real publication date for that
    month."""
    features: np.ndarray
    """Shape (window * len(series_ids) * 2,): for every (month, series)
    slot in the trailing window, oldest-first, the point-in-time value
    (0.0 if masked) immediately followed by its own mask bit -- so a
    flattened-input model sees both the value and whether it was
    genuinely available, not just a silently zero-filled number
    indistinguishable from a real zero."""
    target: float
    """The true, eventually-published CPI_YOY for `target_month` --
    the training label. Never included in `features`."""

    def __post_init__(self) -> None:
        if self.features.ndim != 1:
            raise ValueError("features must be a 1-D array")


def build_inflationcast_dataset(
    store: PointInTimeStore,
    months: list[date],
    *,
    series_ids: tuple[str, ...] = ALL_SERIES_IDS,
    window: int = 6,
    label_lookahead_days: int = 60,
) -> tuple[InflationNowcastExample, ...]:
    """`months` must be the real, sorted, consecutive calendar months
    this dataset could possibly nowcast (typically every month for
    which BOTH a feature window and an eventual CPI label exist).
    `label_lookahead_days` (default 60, well past CPI's real 15-day
    lag) is how far past the target month's end to look for the TRUE
    published value used as the training label -- never used as a
    model input."""
    if window < 1:
        raise ValueError("window must be a positive integer")
    examples: list[InflationNowcastExample] = []
    for i in range(window - 1, len(months)):
        target_month = months[i]
        decision_date = target_month
        label_obs = store.as_of(
            CPI_SERIES_ID, target_month, target_month + timedelta(days=label_lookahead_days)
        )
        if label_obs is None:
            continue  # a real data gap (e.g. the 2025-10 BLS lapse) -- skipped, not fabricated
        window_months = months[i - window + 1 : i + 1]
        values: list[float] = []
        for m in window_months:
            for series_id in series_ids:
                obs = store.as_of(series_id, m, decision_date)
                values.append(obs.value if obs is not None else 0.0)
                values.append(1.0 if obs is not None else 0.0)
        examples.append(
            InflationNowcastExample(
                target_month=target_month,
                decision_date=decision_date,
                features=np.array(values, dtype=np.float64),
                target=label_obs.value,
            )
        )
    return tuple(examples)


def chronological_split(
    examples: tuple[InflationNowcastExample, ...], split_date: date
) -> tuple[tuple[InflationNowcastExample, ...], tuple[InflationNowcastExample, ...]]:
    """Train = target_month strictly before split_date; test = at or
    after it. Fails loudly if either side would be empty."""
    train = tuple(e for e in examples if e.target_month < split_date)
    test = tuple(e for e in examples if e.target_month >= split_date)
    if not train or not test:
        raise ValueError("split_date must leave both a non-empty train and test set")
    return train, test
