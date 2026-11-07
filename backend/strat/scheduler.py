"""When the single fetcher should run.

Regular session is 09:30–16:00 America/New_York, weekdays. The intraday poll is at most every
``STRAT_POLL_SECONDS`` (default 15 minutes). Premarket (04:00–09:30) and after hours
(16:00–20:00) poll the index ETFs on that same cadence; the rest of the universe stays on
daily bars. After the close, one history job confirms the session. Holidays are not
special-cased: a closed day returns the same bars and the next weekday catches up.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from . import config

ET = ZoneInfo("America/New_York")
PREMARKET_AT = time(4, 0)
OPEN = time(9, 30)
CLOSE = time(16, 0)
AFTER_HOURS_END = time(20, 0)
EOD_AT = time(16, 20)
CLOSING_POLL_END = time(16, 1)  # the 16:00:10 poll picks up the 15:55 bar
# A few minutes after the 16:00 bell, once the closing poll (through 16:01) has finished.
ARCHIVE_AT = time(16, 5)


def now_et(clock: datetime | None = None) -> datetime:
    now = clock or datetime.now(ET)
    return now.astimezone(ET) if now.tzinfo else now.replace(tzinfo=ET)


def regular_session(now: datetime) -> bool:
    local = now_et(now)
    return local.weekday() < 5 and OPEN <= local.time() < CLOSE


def session_phase(now: datetime) -> str:
    """``premarket``, ``regular``, ``after_hours``, or ``closed``.

    Bounds are America/New_York wall-clock times, so the same UTC instant is premarket
    in summer and still closed in winter. Weekends are always closed.
    """
    local = now_et(now)
    if local.weekday() >= 5:
        return "closed"
    t = local.time()
    if PREMARKET_AT <= t < OPEN:
        return "premarket"
    if OPEN <= t < CLOSE:
        return "regular"
    if CLOSE <= t < AFTER_HOURS_END:
        return "after_hours"
    return "closed"


def archive_through(now: datetime) -> date:
    """Last session date, inclusive, that belongs in alerts history.

    On a weekday at or after 16:05 America/New_York that date is today. Before then, and on
    weekends, it is yesterday, so a process that starts after the close still archives the
    session it missed. Weekends have no session rows; ISO dates compare in calendar order.
    """
    local = now_et(now)
    if local.weekday() < 5 and local.time() >= ARCHIVE_AT:
        return local.date()
    return local.date() - timedelta(days=1)


def previous_weekday(now: datetime) -> date:
    """The weekday before ``now``'s Eastern date. Monday goes back to Friday."""
    day = now_et(now).date() - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def last_completed_session(now: datetime) -> date:
    """The most recent weekday session that should already have a confirmed daily bar."""
    local = now_et(now)
    day = local.date()
    if local.weekday() < 5 and local.time() >= EOD_AT:
        return day
    day = day - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def history_due(now: datetime, newest_bar: date | None) -> bool:
    if newest_bar is None:
        return True
    return newest_bar < last_completed_session(now)


def last_mark(now: datetime) -> datetime:
    """Most recent ``LIVE_POLL_MINUTES`` mark plus ``LIVE_POLL_OFFSET_SECONDS`` at or before ``now``."""
    local = now_et(now)
    step = config.LIVE_POLL_MINUTES
    mark = local.replace(minute=local.minute - local.minute % step, second=0, microsecond=0) + timedelta(
        seconds=config.LIVE_POLL_OFFSET_SECONDS
    )
    if mark > local:
        mark -= timedelta(minutes=step)
    return mark


def intraday_due(
    now: datetime, last_poll: datetime | None, interval: int | None = None, *, aligned: bool = False
) -> bool:
    """Regular-session poll.

    ``aligned`` (Alpaca 5-minute bars): once per mark, about 10 seconds after each 5-minute boundary,
    including the 16:00 mark that closes the last bar. Otherwise every ``STRAT_POLL_SECONDS``.
    """
    if aligned:
        local = now_et(now)
        closing = local.weekday() < 5 and CLOSE <= local.time() < CLOSING_POLL_END
        if not (regular_session(now) or closing):
            return False
        return last_poll is None or now_et(last_poll) < last_mark(now)
    if not regular_session(now):
        return False
    if last_poll is None:
        return True
    gap = (now_et(now) - now_et(last_poll)).total_seconds()
    return gap >= (config.POLL_SECONDS if interval is None else interval)


def scheduler_sleep(now: datetime, aligned: bool, default: float = 20.0) -> float:
    """Seconds until the scheduler should look again: 20, or less so an aligned poll lands near its mark."""
    if not aligned:
        return default
    nxt = last_mark(now) + timedelta(minutes=config.LIVE_POLL_MINUTES)
    return max(1.0, min(default, (nxt - now_et(now)).total_seconds() + 0.5))


def extended_due(now: datetime, last_poll: datetime | None, interval: int | None = None) -> bool:
    """Index-quote poll. Same cadence as the regular-session poll, and only outside it."""
    if session_phase(now) not in ("premarket", "after_hours"):
        return False
    if last_poll is None:
        return True
    gap = (now_et(now) - now_et(last_poll)).total_seconds()
    return gap >= (config.POLL_SECONDS if interval is None else interval)


def lists_due(now: datetime, last_poll: datetime | None, *, aligned: bool = False) -> bool:
    """Watchlist / positions premarket poll: once per 5-minute mark, premarket only, Alpaca only.

    In the regular session the same data rides on the intraday poll.
    """
    if not aligned or session_phase(now) != "premarket":
        return False
    return last_poll is None or now_et(last_poll) < last_mark(now)


def fetch_period(now: datetime, newest_bar: date | None, *, full: bool = False) -> str:
    """Short window during the session; the incremental window when the cache is behind."""
    if full or newest_bar is None:
        return config.HISTORY_PERIOD
    if regular_session(now) and (last_completed_session(now) - newest_bar).days <= 4:
        return "5d"
    return config.INCREMENTAL_PERIOD


def decide(
    now: datetime,
    newest_bar: date | None,
    last_poll: datetime | None,
    last_extended: datetime | None = None,
    *,
    aligned: bool = False,
    last_lists: datetime | None = None,
) -> str | None:
    """``intraday`` updates today's bar. ``history`` confirms completed sessions.

    ``lists`` polls the watchlist / positions premarket prints (Alpaca, every 5 minutes).
    ``extended`` refreshes the index quotes during premarket and after hours. ``None`` waits.
    A history catch-up wins over every poll.
    """
    if history_due(now, newest_bar):
        return "history"
    if intraday_due(now, last_poll, aligned=aligned):
        return "intraday"
    if lists_due(now, last_lists, aligned=aligned):
        return "lists"
    if extended_due(now, last_extended):
        return "extended"
    return None
