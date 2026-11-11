from datetime import date

import pytest

from prometheus.recessionnet.labels import (
    NBER_RECESSIONS,
    RecessionPeriod,
    is_recession_month,
    recession_label_as_of,
)


def test_recession_period_rejects_a_trough_before_its_peak() -> None:
    with pytest.raises(ValueError, match="trough"):
        RecessionPeriod(peak=date(2001, 3, 1), trough=date(2001, 1, 1))


def test_recession_period_rejects_an_announcement_before_the_peak_month() -> None:
    with pytest.raises(ValueError, match="peak_announced_at"):
        RecessionPeriod(
            peak=date(2001, 3, 1), trough=date(2001, 11, 1), peak_announced_at=date(2001, 1, 1)
        )


def test_recession_period_rejects_an_announcement_before_the_trough_month() -> None:
    with pytest.raises(ValueError, match="trough_announced_at"):
        RecessionPeriod(
            peak=date(2001, 3, 1), trough=date(2001, 11, 1), trough_announced_at=date(2001, 10, 1)
        )


def test_the_real_nber_table_has_sixteen_recessions_from_1926_onward() -> None:
    """Spot-checked against the live NBER chronology page (see
    `labels.py`'s module docstring for the fetch)."""
    assert len(NBER_RECESSIONS) == 16
    assert NBER_RECESSIONS[0].peak == date(1926, 10, 1)
    assert NBER_RECESSIONS[0].trough == date(1927, 11, 1)
    assert NBER_RECESSIONS[-1].peak == date(2020, 2, 1)
    assert NBER_RECESSIONS[-1].trough == date(2020, 4, 1)


def test_the_great_recession_dates_and_announcement_lags_are_the_real_ones() -> None:
    great_recession = next(r for r in NBER_RECESSIONS if r.peak == date(2007, 12, 1))
    assert great_recession.trough == date(2009, 6, 1)
    assert great_recession.peak_announced_at == date(2008, 12, 1)
    assert great_recession.trough_announced_at == date(2010, 9, 20)


def test_recessions_before_1980_have_no_tracked_announcement_dates() -> None:
    depression = next(r for r in NBER_RECESSIONS if r.peak == date(1929, 8, 1))
    assert depression.peak_announced_at is None
    assert depression.trough_announced_at is None


def test_is_recession_month_true_inside_the_great_recession_window() -> None:
    assert is_recession_month(date(2008, 6, 1)) is True
    assert is_recession_month(date(2009, 6, 1)) is True  # trough month itself: contraction


def test_is_recession_month_false_for_the_peak_month_itself() -> None:
    """Convention: (peak, trough] -- the peak month is the LAST month
    of expansion, not the first contraction month."""
    assert is_recession_month(date(2007, 12, 1)) is False


def test_is_recession_month_false_for_a_clear_expansion_month() -> None:
    assert is_recession_month(date(2015, 1, 1)) is False


def test_contains_contraction_month_is_consistent_for_first_and_end_of_month_queries() -> None:
    """Regression test for a real bug found by an independent,
    separately-coded re-derivation of this exact rule
    (`evidence.independent_data_assessment`): `NBER_RECESSIONS` stores
    peak/trough as the first day of their month, but `recessionnet.
    dataset`'s only real caller queries with END-of-month dates. A raw
    date comparison silently included the peak month and excluded the
    trough month whenever queried at end-of-month -- invisible to every
    OTHER test in this file, which happens to query only at
    first-of-month. The Great Depression (1929-08 peak, 1933-03
    trough) is the real, concrete case this bug was found on."""
    depression = next(r for r in NBER_RECESSIONS if r.peak == date(1929, 8, 1))
    # Peak month itself: excluded (last month of expansion), at BOTH
    # first-of-month and end-of-month query granularity.
    assert depression.contains_contraction_month(date(1929, 8, 1)) is False
    assert depression.contains_contraction_month(date(1929, 8, 31)) is False
    # Trough month itself: included (last month of contraction), at
    # BOTH first-of-month and end-of-month query granularity.
    assert depression.contains_contraction_month(date(1933, 3, 1)) is True
    assert depression.contains_contraction_month(date(1933, 3, 31)) is True
    # A genuine mid-contraction month: included either way.
    assert depression.contains_contraction_month(date(1931, 6, 30)) is True
    # A genuine expansion month: excluded either way.
    assert depression.contains_contraction_month(date(1934, 1, 31)) is False


def test_as_of_rejects_a_month_in_the_future_relative_to_as_of() -> None:
    with pytest.raises(ValueError, match="future"):
        recession_label_as_of(date(2026, 1, 1), date(2020, 1, 1))


def test_as_of_is_zero_for_a_genuinely_non_recession_month() -> None:
    assert recession_label_as_of(date(2015, 1, 1), date(2015, 1, 1)) == 0.0


def test_as_of_does_not_leak_the_great_recession_before_it_was_announced() -> None:
    """THE flagship point-in-time leakage test. January 2008 was,
    retrospectively, a real recession month (confirmed by
    `is_recession_month` below) -- but the NBER did not tell anyone
    until December 1, 2008. An honest real-time analyst standing on
    2008-06-01 could not have known this. `recession_label_as_of` must
    say so."""
    assert is_recession_month(date(2008, 1, 1)) is True
    assert recession_label_as_of(date(2008, 1, 1), date(2008, 6, 1)) == 0.0


def test_as_of_knows_the_recession_started_right_after_the_peak_announcement() -> None:
    # Announced 2008-12-01 that December 2007 was a peak; the recession
    # is known to have started, even though its end is not yet known.
    assert recession_label_as_of(date(2008, 1, 1), date(2008, 12, 1)) == 1.0
    assert recession_label_as_of(date(2009, 1, 1), date(2009, 1, 15)) == 1.0


def test_as_of_is_fully_resolved_once_the_trough_is_announced() -> None:
    assert recession_label_as_of(date(2009, 6, 1), date(2010, 10, 1)) == 1.0
    assert recession_label_as_of(date(2008, 3, 1), date(2010, 10, 1)) == 1.0


def test_as_of_right_before_the_peak_announcement_is_still_unknown() -> None:
    day_before = date(2008, 11, 30)
    assert recession_label_as_of(date(2008, 1, 1), day_before) == 0.0


def test_as_of_returns_none_for_a_pre_1980_recession_still_in_progress() -> None:
    """August 1929's peak was never separately "announced" (no Dating
    Committee existed); while the Depression is still technically
    ongoing as of the queried as_of date, this function should admit
    it cannot determine real-time knowability rather than guess."""
    assert recession_label_as_of(date(1930, 1, 1), date(1930, 6, 1)) is None


def test_as_of_resolves_a_pre_1980_recession_once_its_trough_has_passed() -> None:
    """Once the whole recession is safely in the past, treat it as
    resolved common historical knowledge."""
    assert recession_label_as_of(date(1930, 1, 1), date(1934, 1, 1)) == 1.0


def test_as_of_is_zero_before_a_pre_1980_recession_even_begins() -> None:
    assert recession_label_as_of(date(1920, 1, 1), date(1920, 1, 1)) == 0.0
