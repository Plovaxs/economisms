import calendar
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from prometheus.econosim.pit import (
    FutureDataError,
    MacroObservation,
    PointInTimeStore,
    require_eligible,
)
from prometheus.inflationcast.data import (
    ALL_SERIES_IDS,
    CPI_PUBLICATION_LAG_DAYS,
    CPI_SERIES_ID,
    PREDICTOR_SERIES_IDS,
    InflationNowcastExample,
    build_inflationcast_dataset,
    chronological_split,
    load_cpi_observations,
)

_REAL_CSV = Path(__file__).resolve().parents[2] / "data_cache" / "us_cpi_monthly.csv"


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _synthetic_store_and_months(n_months: int = 24) -> tuple[PointInTimeStore, list[date]]:
    """A small, clearly SYNTHETIC store spanning `n_months` consecutive
    calendar months, with every series present every month -- used only
    to exercise the dataset builder's mechanics in isolation from any
    real data gap."""
    store = PointInTimeStore()
    months: list[date] = []
    year, month = 2010, 1
    for i in range(n_months):
        m = _month_end(year, month)
        months.append(m)
        store.record(
            MacroObservation(
                series_id=CPI_SERIES_ID,
                observation_at=m,
                published_at=m + timedelta(days=CPI_PUBLICATION_LAG_DAYS),
                value=2.0 + 0.1 * i,
            )
        )
        for j, series_id in enumerate(PREDICTOR_SERIES_IDS):
            store.record(
                MacroObservation(
                    series_id=series_id,
                    observation_at=m,
                    published_at=m,
                    value=float(i + j),
                )
            )
        month += 1
        if month > 12:
            month = 1
            year += 1
    return store, months


def test_load_cpi_observations_reads_the_real_committed_csv() -> None:
    observations = load_cpi_observations(_REAL_CSV)
    assert len(observations) > 200
    assert all(o.series_id == CPI_SERIES_ID for o in observations)
    assert all(
        o.published_at == o.observation_at + timedelta(days=CPI_PUBLICATION_LAG_DAYS)
        for o in observations
    )
    # The real 2025-10 BLS lapse-in-appropriations gap is simply absent.
    assert date(2025, 10, 31) not in {o.observation_at for o in observations}
    # The real 2022-06 inflation-surge peak the meta.json discloses.
    peak = next(o for o in observations if o.observation_at == date(2022, 6, 30))
    assert peak.value == pytest.approx(9.06, abs=0.01)


def test_build_inflationcast_dataset_masks_the_target_months_own_cpi() -> None:
    """The literal FP-07 acceptance criterion: for every example, the
    final (most recent) window slot's CPI value/mask pair must be
    zero-filled/masked, since that slot is the target month itself --
    never genuinely available at decision time."""
    store, months = _synthetic_store_and_months(24)
    examples = build_inflationcast_dataset(store, months, window=6)
    assert len(examples) == 24 - 6 + 1

    n_series = len(ALL_SERIES_IDS)
    for example in examples:
        last_block = example.features[-2 * n_series :]
        cpi_value, cpi_mask = last_block[0], last_block[1]
        assert cpi_value == 0.0
        assert cpi_mask == 0.0


def test_build_inflationcast_dataset_does_not_mask_prior_months_cpi() -> None:
    """The month immediately before the target is always genuinely
    published by decision time (15-day lag vs. ~30-day gap) -- masking
    it too would silently throw away real, legitimately available
    information, not just protect against leakage."""
    store, months = _synthetic_store_and_months(24)
    examples = build_inflationcast_dataset(store, months, window=6)
    n_series = len(ALL_SERIES_IDS)
    for example in examples:
        prior_block = example.features[-4 * n_series : -2 * n_series]
        cpi_value, cpi_mask = prior_block[0], prior_block[1]
        assert cpi_mask == 1.0
        assert cpi_value != 0.0


def test_require_eligible_rejects_the_target_months_cpi_at_decision_time() -> None:
    """The active-rejection counterpart to the soft-mask test above: a
    caller that tries to bypass the dataset builder and ask the store
    directly for the target month's own CPI, at the same decision date
    the builder uses, must fail closed."""
    store, months = _synthetic_store_and_months(24)
    target_month = months[-1]
    with pytest.raises(FutureDataError):
        require_eligible(store, CPI_SERIES_ID, target_month, target_month)


def test_require_eligible_accepts_the_target_months_cpi_after_its_real_lag() -> None:
    store, months = _synthetic_store_and_months(24)
    target_month = months[-1]
    decision_date = target_month + timedelta(days=CPI_PUBLICATION_LAG_DAYS)
    observation = require_eligible(store, CPI_SERIES_ID, target_month, decision_date)
    assert observation.observation_at == target_month


def test_build_inflationcast_dataset_rejects_non_positive_window() -> None:
    store, months = _synthetic_store_and_months(6)
    with pytest.raises(ValueError, match="window"):
        build_inflationcast_dataset(store, months, window=0)


def test_build_inflationcast_dataset_skips_a_data_gap_rather_than_fabricating_a_label() -> None:
    """A month with no eligible label (e.g. the real 2025-10 BLS gap)
    must be skipped entirely, never filled with a fabricated target."""
    store, months = _synthetic_store_and_months(8)
    gap_month = months[-1]
    # Remove every CPI observation for the final month by rebuilding a
    # store that never recorded one for it.
    store2 = PointInTimeStore()
    for series_id in (CPI_SERIES_ID, *PREDICTOR_SERIES_IDS):
        for m in months:
            if series_id == CPI_SERIES_ID and m == gap_month:
                continue
            store2.record(
                MacroObservation(
                    series_id=series_id,
                    observation_at=m,
                    published_at=m if series_id != CPI_SERIES_ID else m + timedelta(days=15),
                    value=1.0,
                )
            )
    examples = build_inflationcast_dataset(store2, months, window=4)
    assert gap_month not in {e.target_month for e in examples}


def test_chronological_split_partitions_by_target_month() -> None:
    store, months = _synthetic_store_and_months(24)
    examples = build_inflationcast_dataset(store, months, window=6)
    split_date = examples[10].target_month
    train, test = chronological_split(examples, split_date)
    assert all(e.target_month < split_date for e in train)
    assert all(e.target_month >= split_date for e in test)
    assert len(train) + len(test) == len(examples)


def test_chronological_split_rejects_a_split_leaving_an_empty_side() -> None:
    store, months = _synthetic_store_and_months(24)
    examples = build_inflationcast_dataset(store, months, window=6)
    with pytest.raises(ValueError):
        chronological_split(examples, date(1900, 1, 1))


def test_inflation_nowcast_example_rejects_non_1d_features() -> None:
    with pytest.raises(ValueError, match="1-D"):
        InflationNowcastExample(
            target_month=date(2020, 1, 31),
            decision_date=date(2020, 1, 31),
            features=np.zeros((2, 2)),
            target=0.0,
        )
