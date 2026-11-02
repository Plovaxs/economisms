from datetime import date

import pytest

from prometheus.core.calendar import BusinessDayCalendar, CalendarError, add_months


def test_add_months_within_year() -> None:
    assert add_months(date(2026, 1, 15), 2) == date(2026, 3, 15)


def test_add_months_year_rollover() -> None:
    assert add_months(date(2026, 11, 15), 3) == date(2027, 2, 15)


def test_add_months_clips_day_to_shorter_month() -> None:
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)


def test_add_months_clips_day_in_leap_year() -> None:
    assert add_months(date(2028, 1, 31), 1) == date(2028, 2, 29)  # 2028 is a leap year


def test_add_months_zero_is_identity() -> None:
    d = date(2026, 6, 10)
    assert add_months(d, 0) == d


def test_weekend_is_not_a_business_day() -> None:
    cal = BusinessDayCalendar()
    saturday = date(2026, 11, 7)
    assert saturday.weekday() == 5
    assert not cal.is_business_day(saturday)


def test_holiday_is_not_a_business_day() -> None:
    thanksgiving = date(2026, 11, 26)
    cal = BusinessDayCalendar(holidays=frozenset({thanksgiving}))
    assert not cal.is_business_day(thanksgiving)


def test_next_business_day_skips_weekend() -> None:
    cal = BusinessDayCalendar()
    friday = date(2026, 11, 6)
    saturday = date(2026, 11, 7)
    monday = date(2026, 11, 9)
    assert cal.next_business_day(friday) == friday
    assert cal.next_business_day(saturday) == monday


def test_next_business_day_skips_holiday_and_weekend() -> None:
    # Thursday 26 Nov 2026 is a holiday, Fri 27 is a business day in this calendar
    thanksgiving = date(2026, 11, 26)
    cal = BusinessDayCalendar(holidays=frozenset({thanksgiving}))
    assert cal.next_business_day(thanksgiving) == date(2026, 11, 27)


def test_add_business_days_counts_only_business_days() -> None:
    cal = BusinessDayCalendar()
    friday = date(2026, 11, 6)
    # +1 business day from Friday should land on Monday, skipping the weekend
    assert cal.add_business_days(friday, 1) == date(2026, 11, 9)


def test_add_business_days_rejects_negative() -> None:
    cal = BusinessDayCalendar()
    with pytest.raises(CalendarError):
        cal.add_business_days(date(2026, 1, 1), -1)


def test_business_days_between_excludes_weekend() -> None:
    cal = BusinessDayCalendar()
    start = date(2026, 11, 2)  # Monday
    end = date(2026, 11, 8)  # Sunday
    days = cal.business_days_between(start, end)
    assert days == [
        date(2026, 11, 2),
        date(2026, 11, 3),
        date(2026, 11, 4),
        date(2026, 11, 5),
        date(2026, 11, 6),
    ]


def test_business_days_between_rejects_inverted_range() -> None:
    cal = BusinessDayCalendar()
    with pytest.raises(CalendarError):
        cal.business_days_between(date(2026, 1, 2), date(2026, 1, 1))
