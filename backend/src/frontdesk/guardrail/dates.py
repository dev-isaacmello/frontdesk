"""Resolves a weekday, a day of the month or a day and month to a calendar date near today."""

import datetime

_MONTHS_AHEAD = 12
# Enough years to reach the next 29 February from any date.
_YEARS_AHEAD = 8


def valid_date(year: int, month: int, day: int) -> datetime.date | None:
    """The date with these parts, or nothing when the calendar has no such day."""
    try:
        return datetime.date(year, month, day)
    except (ValueError, OverflowError):
        return None


def next_weekday(today: datetime.date, weekday: int) -> datetime.date:
    """The nearest date strictly after `today` that falls on `weekday` (Monday is 0)."""
    days_ahead = (weekday - today.weekday() - 1) % 7 + 1
    return today + datetime.timedelta(days=days_ahead)


def next_day_of_month(today: datetime.date, day: int) -> datetime.date | None:
    """The nearest date on or after `today` whose day of the month is `day`."""
    first_month = today.year * 12 + today.month - 1
    for month_index in range(first_month, first_month + _MONTHS_AHEAD + 1):
        candidate = valid_date(month_index // 12, month_index % 12 + 1, day)
        if candidate is not None and candidate >= today:
            return candidate
    return None


def next_day_and_month(today: datetime.date, month: int, day: int) -> datetime.date | None:
    """The nearest date on or after `today` with this day and month."""
    for year in range(today.year, today.year + _YEARS_AHEAD + 1):
        candidate = valid_date(year, month, day)
        if candidate is not None and candidate >= today:
            return candidate
    return None
