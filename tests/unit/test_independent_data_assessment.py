import calendar
import csv
from datetime import date
from pathlib import Path

import pytest

from prometheus.econosim.pit import MacroObservation
from prometheus.evidence.independent_data_assessment import (
    IndependentAssessmentMismatchError,
    independently_reproduce_labels,
    independently_reproduce_split,
    verify_independent_assessment,
)
from prometheus.recessionnet.dataset import build_recession_dataset
from prometheus.recessionnet.labels import NBER_RECESSIONS, RecessionPeriod

_FIXTURE_CSV = Path(__file__).resolve().parents[1] / "fixtures" / "ff3_monthly_real.csv"
_SERIES_IDS = ("FF3_Mkt-RF", "FF3_SMB", "FF3_HML", "FF3_RF")


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _load_real_ff3_observations() -> list[MacroObservation]:
    """The same real Kenneth French monthly factor history used by
    `test_recessionnet_dataset.py` -- reused, not duplicated data,
    only the loading helper is repeated per this test suite's own
    per-file fixture convention."""
    observations: list[MacroObservation] = []
    with _FIXTURE_CSV.open() as f:
        for row in csv.DictReader(f):
            year, month = int(row["date"][:4]), int(row["date"][4:6])
            observation_at = _month_end(year, month)
            for factor in ("Mkt-RF", "SMB", "HML", "RF"):
                observations.append(
                    MacroObservation(
                        series_id=f"FF3_{factor}",
                        observation_at=observation_at,
                        published_at=observation_at,
                        value=float(row[factor]),
                    )
                )
    return observations


_REAL_OBSERVATIONS = _load_real_ff3_observations()


def test_the_independent_assessment_agrees_with_the_real_production_pipeline() -> None:
    """MGR-03's own acceptance wording: "independent assessment
    reproduces eligibility and split." Built against the real
    Kenneth French factor history and the real NBER chronology, not a
    synthetic fixture."""
    dataset = build_recession_dataset(
        _REAL_OBSERVATIONS, _SERIES_IDS, NBER_RECESSIONS, window=6, horizon=6
    )
    verify_independent_assessment(dataset, date(2000, 1, 1))  # must not raise


def test_the_independent_split_matches_on_a_second_real_split_date() -> None:
    dataset = build_recession_dataset(
        _REAL_OBSERVATIONS, _SERIES_IDS, NBER_RECESSIONS, window=6, horizon=6
    )
    verify_independent_assessment(dataset, date(2008, 6, 1))  # must not raise


def test_independently_reproduce_split_matches_a_hand_worked_example() -> None:
    months = (date(1999, 12, 31), date(2000, 1, 31), date(2000, 2, 29))
    train, test = independently_reproduce_split(months, date(2000, 1, 1))
    assert train == (0,)
    assert test == (1, 2)


def test_independently_reproduce_labels_matches_the_peak_exclusive_trough_inclusive_rule() -> (
    None
):
    period = (RecessionPeriod(peak=date(2000, 3, 31), trough=date(2000, 5, 31)),)
    targets = (date(2000, 3, 31), date(2000, 4, 30), date(2000, 5, 31), date(2000, 6, 30))
    assert independently_reproduce_labels(targets, period) == (0.0, 1.0, 1.0, 0.0)


def test_verify_independent_assessment_rejects_a_tampered_label() -> None:
    dataset = build_recession_dataset(
        _REAL_OBSERVATIONS, _SERIES_IDS, NBER_RECESSIONS, window=6, horizon=6
    )
    dataset.labels[0] = 1.0 - dataset.labels[0]  # flip one real label
    with pytest.raises(IndependentAssessmentMismatchError, match="label"):
        verify_independent_assessment(dataset, date(2000, 1, 1))
