"""When a weekly, monthly, quarterly, or half-year candle is finished.

Strat triggers, setup type, continuity, and the M/W chips read the last
*completed* period. The week (or month) still in progress is not a candle yet.
A period finishes at the close of its last NYSE session: Friday for a normal
week, Thursday when Friday is a holiday, and the last weekday of a month when
the calendar month ends on a weekend. Daily bars are sessions and are not
trimmed here.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from .scheduler import CLOSE, ET

_HOLIDAYS: dict[int, frozenset[date]] = {}


def clock() -> datetime:
    """Current time in New York. Tests replace this."""
    return datetime.now(ET)


def _as_et(now: datetime | None) -> datetime:
    if now is None:
        now = clock()
    if now.tzinfo is None:
        return now.replace(tzinfo=ET)
    return now.astimezone(ET)


def _observed(day: date) -> date:
    """NYSE observes a Saturday holiday on Friday and a Sunday holiday on Monday."""
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    delta = (weekday - first.weekday()) % 7
    return first + timedelta(days=delta + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        last = date(year, 12, 31)
    else:
        last = date(year, month + 1, 1) - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _easter(year: int) -> date:
    """Gregorian computus. Good Friday is two days earlier."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    g = (b - (b + 8) // 25 + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def nyse_holidays(year: int) -> frozenset[date]:
    """Full-day NYSE closes for ``year`` (Juneteenth from 2022)."""
    cached = _HOLIDAYS.get(year)
    if cached is not None:
        return cached
    days = {
        _observed(date(year, 1, 1)),
        _nth_weekday(year, 1, 0, 3),  # MLK
        _nth_weekday(year, 2, 0, 3),  # Presidents Day
        _easter(year) - timedelta(days=2),  # Good Friday
        _last_weekday(year, 5, 0),  # Memorial Day
        _observed(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),  # Labor Day
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving
        _observed(date(year, 12, 25)),
    }
    if year >= 2022:
        days.add(_observed(date(year, 6, 19)))
    new_year = _observed(date(year + 1, 1, 1))
    if new_year.year == year:
        days.add(new_year)
    cached = frozenset(days)
    _HOLIDAYS[year] = cached
    return cached


def is_trading_day(day: date) -> bool:
    return day.weekday() < 5 and day not in nyse_holidays(day.year)


def _month_end(year: int, month: int) -> date:
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def period_bounds(tf: str, day: date) -> tuple[date, date]:
    """First and last calendar day of the W/M/3M/6M period that contains ``day``."""
    if tf == "W":
        monday = _monday(day)
        return monday, monday + timedelta(days=4)
    if tf == "M":
        return date(day.year, day.month, 1), _month_end(day.year, day.month)
    if tf == "3M":
        start_month = ((day.month - 1) // 3) * 3 + 1
        return date(day.year, start_month, 1), _month_end(day.year, start_month + 2)
    if tf == "6M":
        start_month = 1 if day.month <= 6 else 7
        return date(day.year, start_month, 1), _month_end(day.year, start_month + 5)
    raise ValueError(f"unknown timeframe {tf}")


def final_session(tf: str, day: date) -> date:
    """Last NYSE session of the period that contains ``day``."""
    start, end = period_bounds(tf, day)
    cursor = end
    while cursor >= start and not is_trading_day(cursor):
        cursor -= timedelta(days=1)
    return cursor


def period_complete(tf: str, last_bar: date, now: datetime | None = None) -> bool:
    """True when ``last_bar`` is the period's final session and that session has closed.

    A Friday bar on Friday morning is still the open week. A Thursday bar is the
    whole week when Friday is a holiday and Thursday's close has passed. A bar
    that merely falls before the final session (Monday through Thursday of a
    normal week, or mid-month) is never complete, whatever the clock says.
    """
    if tf == "D":
        return True
    final = final_session(tf, last_bar)
    if last_bar < final:
        return False
    local = _as_et(now)
    if local.date() == final and local.time() < CLOSE:
        return False
    return True


def completed_week_high_labels(last_bar: date, now: datetime | None = None) -> tuple[str, str]:
    """Labels for the most recent completed week's high and the week before it.

    While a new week has started, or the week of ``last_bar`` has not closed,
    the newest completed candle is "last week's high". After Friday's close
    (and over the weekend) it is "this week's high".
    """
    moment = _as_et(now)
    spoken = last_bar
    gap = (moment.date() - last_bar).days
    if 0 <= gap <= 7:
        spoken = moment.date()
    later_week = _monday(spoken) > _monday(last_bar)
    if later_week or not period_complete("W", last_bar, moment):
        return "last week's high", "prior week's high"
    return "this week's high", "last week's high"


def daily_bar_complete(last_bar: date, now: datetime | None = None) -> bool:
    """False while ``last_bar`` is today's session and the regular close has not passed (the bar is still forming)."""
    local = _as_et(now)
    return not (last_bar >= local.date() and local.time() < CLOSE)
