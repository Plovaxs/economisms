"""A minimal business-day calendar (LED-11: time-zone/holiday/business-day
calendars -- the time-zone part is explicitly deferred; dates here are naive
and treated as UTC).

Shared by the macro time engine (one macro step snapped to a business day)
and, later, by market-calendar stepping and day-count conventions in the
pricing subsystem.
"""

from __future__ import annotations

import calendar as _calendar_module
from dataclasses import dataclass, field
from datetime import date, timedelta


class CalendarError(ValueError):
    """Base class for calendar-arithmetic errors."""


def add_months(d: date, months: int) -> date:
    """Add whole calendar months to a date, clipping the day-of-month to
    the target month's last day when it would otherwise overflow (e.g.
    31 Jan + 1 month -> 28 Feb, or 29 Feb in a leap year)."""
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    last_day_of_month = _calendar_module.monthrange(year, month)[1]
    day = min(d.day, last_day_of_month)
    return date(year, month, day)


@dataclass(frozen=True, slots=True)
class BusinessDayCalendar:
    holidays: frozenset[date] = field(default_factory=frozenset)
    weekend: frozenset[int] = field(default_factory=lambda: frozenset({5, 6}))

    def is_business_day(self, d: date) -> bool:
        return d.weekday() not in self.weekend and d not in self.holidays

    def next_business_day(self, d: date) -> date:
        """Return d itself if it is already a business day, else the next one."""
        current = d
        while not self.is_business_day(current):
            current += timedelta(days=1)
        return current

    def previous_business_day(self, d: date) -> date:
        current = d
        while not self.is_business_day(current):
            current -= timedelta(days=1)
        return current

    def add_business_days(self, d: date, n: int) -> date:
        if n < 0:
            raise CalendarError(
                "add_business_days requires n >= 0 (no negative-day stepping implemented)"
            )
        current = d
        remaining = n
        while remaining > 0:
            current += timedelta(days=1)
            if self.is_business_day(current):
                remaining -= 1
        return current

    def business_days_between(self, start: date, end: date) -> list[date]:
        if end < start:
            raise CalendarError("end must not be before start")
        days: list[date] = []
        current = start
        while current <= end:
            if self.is_business_day(current):
                days.append(current)
            current += timedelta(days=1)
        return days

    def count_business_days(self, start: date, end: date) -> int:
        return len(self.business_days_between(start, end))
