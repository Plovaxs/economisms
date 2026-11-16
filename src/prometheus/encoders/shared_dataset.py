"""Real data join for the FP-08 shared-vs-independent encoder ablation.

RECESSIONNET's Kaggle grounding (`data_ingestion.kaggle_macro`) and
INFLATIONCAST (`inflationcast.data`) already draw their macro
predictors from the IDENTICAL five real series
(`KAGGLE_GDP_YOY`/`KAGGLE_CLAIMS_YOY`/`KAGGLE_FEDFUNDS`/
`KAGGLE_M2_YOY`/`KAGGLE_NASDAQ_YOY`). This module builds ONE shared
windowed feature tensor over those five series and attaches BOTH a
real recession label (NBER chronology, `recessionnet.labels`) and a
real CPI_YOY nowcast label (`inflationcast.data.load_cpi_observations`)
to every decision month where both genuinely exist -- it does not
fabricate a label for a month lacking one.

Each task keeps its own natural target definition relative to the
shared decision month: the recession label is for `horizon` months
AFTER the decision month (matching `recessionnet.dataset`'s own
forecast framing), while the inflation label is for the decision month
ITSELF (matching `inflationcast.data`'s own nowcast framing -- the
decision date is that month's own last day). This is a deliberate,
disclosed choice: it would also have been defensible to force both
tasks onto one shared target month, but that would depart from each
task's own already-evidenced, real-world framing for no real benefit.

Real coverage: the committed Kaggle macro snapshot runs 1981-12
through 2023-01; the committed BLS CPI snapshot's YoY column is
populated from roughly 2007-01 (it needs a trailing 12 months of index
levels before a year-over-year rate is even computable) through
2026-10. The usable overlap for this ablation is therefore
2007-01..2023-01, driven entirely by the Kaggle snapshot's own end
date -- a real data-availability ceiling, not a bug in this loader.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np

from prometheus.data_ingestion.monthly_matrix import build_monthly_series_matrix
from prometheus.econosim.pit import MacroObservation
from prometheus.recessionnet.labels import NBER_RECESSIONS, RecessionPeriod, is_recession_month

_FIXED_FEATURE_SCALE = 100.0
"""Identical fixed, data-independent rescaling to `recessionnet.dataset`
(see that module's docstring for why a fixed constant, rather than a
fitted standardization, cannot leak future information)."""


@dataclass(frozen=True, slots=True)
class SharedEncoderExample:
    decision_month: date
    """The month this example's trailing feature window ends at."""
    recession_target_month: date
    """decision_month + horizon months -- the month the recession label
    describes, matching `recessionnet.dataset`'s own forecast framing."""
    features: np.ndarray
    """Shape (window * n_series,): trailing `window` months of the 5
    shared Kaggle series, oldest-first, divided by `_FIXED_FEATURE_SCALE`
    -- byte-for-byte the same scaling `recessionnet.dataset` uses."""
    recession_label: float
    """1.0 if recession_target_month is a real NBER contraction month,
    else 0.0 (the same fully-resolved retrospective label
    `recessionnet.dataset` uses for its own historical backtest)."""
    inflation_target: float
    """The real, eventually-published CPI_YOY for decision_month itself
    (a nowcast target, matching `inflationcast.data`'s own framing)."""

    def __post_init__(self) -> None:
        if self.features.ndim != 1:
            raise ValueError("features must be a 1-D array")


def build_shared_encoder_dataset(
    kaggle_observations: Sequence[MacroObservation],
    cpi_observations: Sequence[MacroObservation],
    *,
    series_ids: Sequence[str],
    cpi_series_id: str,
    window: int,
    horizon: int,
    recessions: tuple[RecessionPeriod, ...] = NBER_RECESSIONS,
) -> tuple[SharedEncoderExample, ...]:
    if window < 1:
        raise ValueError("window must be a positive integer")
    if horizon < 1:
        raise ValueError("horizon must be a positive integer")

    months, matrix = build_monthly_series_matrix(kaggle_observations, series_ids)
    cpi_by_month: dict[date, float] = {
        obs.observation_at: obs.value for obs in cpi_observations if obs.series_id == cpi_series_id
    }

    n_months = len(months)
    examples: list[SharedEncoderExample] = []
    for i in range(window - 1, n_months - horizon):
        decision_month = months[i]
        inflation_target = cpi_by_month.get(decision_month)
        if inflation_target is None:
            continue  # a real CPI gap for this month -- skipped, not fabricated
        recession_target_month = months[i + horizon]
        window_slice = matrix[i - window + 1 : i + 1, :]  # oldest-first
        examples.append(
            SharedEncoderExample(
                decision_month=decision_month,
                recession_target_month=recession_target_month,
                features=window_slice.reshape(-1) / _FIXED_FEATURE_SCALE,
                recession_label=1.0
                if is_recession_month(recession_target_month, recessions)
                else 0.0,
                inflation_target=inflation_target,
            )
        )
    return tuple(examples)


def chronological_split3(
    examples: tuple[SharedEncoderExample, ...],
    validation_split_date: date,
    test_split_date: date,
) -> tuple[
    tuple[SharedEncoderExample, ...],
    tuple[SharedEncoderExample, ...],
    tuple[SharedEncoderExample, ...],
]:
    """Train = decision_month strictly before validation_split_date;
    validation = at or after it but strictly before test_split_date;
    test = at or after test_split_date. Fails loudly if any of the
    three would be empty."""
    if validation_split_date >= test_split_date:
        raise ValueError("validation_split_date must be strictly before test_split_date")
    train = tuple(e for e in examples if e.decision_month < validation_split_date)
    validation = tuple(
        e for e in examples if validation_split_date <= e.decision_month < test_split_date
    )
    test = tuple(e for e in examples if e.decision_month >= test_split_date)
    if not train or not validation or not test:
        raise ValueError("split dates must leave all three of train/validation/test non-empty")
    return train, validation, test


def stack_features(
    examples: tuple[SharedEncoderExample, ...], *, window: int, n_series: int
) -> np.ndarray:
    """Reshapes each example's flat `features` into (window, n_series)
    -- the sequential shape a GRU-based temporal encoder expects -- and
    stacks them into (n_examples, window, n_series)."""
    return np.stack([e.features.reshape(window, n_series) for e in examples])


def recession_labels(examples: tuple[SharedEncoderExample, ...]) -> np.ndarray:
    return np.array([e.recession_label for e in examples], dtype=np.float64)


def inflation_targets(examples: tuple[SharedEncoderExample, ...]) -> np.ndarray:
    return np.array([e.inflation_target for e in examples], dtype=np.float64)
