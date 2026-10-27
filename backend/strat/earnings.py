"""Upcoming earnings dates from Yahoo Finance, cached in SQLite.

Only dates the source actually reports are used; nothing is inferred. Timing is BMO/AMC only when Yahoo's
scheduled time is clearly before the open or after the close, otherwise it is left unknown ("time TBD").
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional
from zoneinfo import ZoneInfo

import pandas as pd

from . import data

log = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
# Warning window, in calendar days including today. A report this many days away still warns; the next day does not.
# The saved user setting (earnings_window_days) overrides this default. Not trading days: weekends count.
DEFAULT_WARNING_WINDOW_DAYS = 3
# How far ahead fetch_earnings looks up BMO/AMC. This is the old warning window (10) plus its 5-day buffer,
# and it stays fixed so a shorter warning does not change what gets fetched.
TIMING_LOOKAHEAD_DAYS = 15
MAX_AGE_HOURS = 12
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)


def timing_from_time(ts: datetime) -> Optional[str]:
    """BMO / AMC from a scheduled report time, or None when it is unknown or during market hours."""
    if ts.tzinfo is not None:
        ts = ts.astimezone(ET)
    t = ts.time()
    if t == time(0, 0):
        return None  # date-only placeholder
    if t < MARKET_OPEN:
        return "BMO"
    if t >= MARKET_CLOSE:
        return "AMC"
    return None


def parse_calendar(cal) -> tuple[Optional[date], Optional[date]]:
    """(first, last) earnings date from Ticker.calendar; last differs only when Yahoo gives an estimated range."""
    raw = cal.get("Earnings Date") if isinstance(cal, dict) else None
    if not raw:
        return None, None
    days = sorted(d.date() if isinstance(d, datetime) else d for d in raw if isinstance(d, (date, datetime)))
    if not days:
        return None, None
    return days[0], days[-1]


def timing_for(earnings_dates: Optional[pd.DataFrame], day: date) -> Optional[str]:
    """Timing of the scheduled report on ``day`` from Ticker.get_earnings_dates, if Yahoo lists it."""
    if earnings_dates is None or earnings_dates.empty:
        return None
    for ts in earnings_dates.index:
        ts = pd.Timestamp(ts)
        local = ts.tz_convert(ET) if ts.tzinfo is not None else ts
        if local.date() == day:
            return timing_from_time(local.to_pydatetime())
    return None


def today_et() -> date:
    return datetime.now(ET).date()


def upcoming(entry: Optional[dict], today: date, window: int = DEFAULT_WARNING_WINDOW_DAYS) -> Optional[dict]:
    """The cached earnings entry if its first date is within the next ``window`` calendar days (today included).

    Calendar days, not trading days. ``window`` of 3 means today through three days out. An estimated range
    that has already started stays visible until its last date is before today.
    """
    if not entry or not entry.get("date"):
        return None
    first = date.fromisoformat(entry["date"])
    last = date.fromisoformat(entry["date_end"]) if entry.get("date_end") else first
    if last < today or (first - today).days > window:
        return None
    return {
        "date": entry["date"],
        "date_end": entry["date_end"] if last != first else None,
        "timing": entry.get("timing"),
        "days_until": max(0, (first - today).days),
    }


def fetch_earnings(symbol: str) -> dict:
    """Next earnings date (and timing when it is soon) for one symbol; date is None when Yahoo has none."""
    import yfinance as yf

    ticker = yf.Ticker(symbol)
    try:
        first, last = parse_calendar(ticker.calendar)
    except Exception as exc:  # no fundamentals (ETFs, some ADRs) or a network error
        log.debug("calendar failed for %s: %s", symbol, exc)
        first, last = None, None
    timing = None
    if first is not None and (first - date.today()).days <= TIMING_LOOKAHEAD_DAYS:
        try:
            timing = timing_for(ticker.get_earnings_dates(limit=8), first) if first == last else None
        except Exception as exc:
            log.debug("earnings dates failed for %s: %s", symbol, exc)
    return {
        "symbol": symbol,
        "date": first.isoformat() if first else None,
        "date_end": last.isoformat() if last and last != first else None,
        "timing": timing,
    }


def refresh_earnings(
    symbols: Iterable[str],
    max_age_hours: float = MAX_AGE_HOURS,
    progress: Callable[[int, int, str], None] | None = None,
    fetch: Callable[[str], dict] | None = None,
    db_path: Path | None = None,
) -> int:
    """Re-fetch earnings for symbols whose cached entry is missing or older than ``max_age_hours``."""
    fetch = fetch or fetch_earnings
    cached = data.load_earnings(db_path)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    stale = [
        s for s in dict.fromkeys(symbols)
        if s not in cached or datetime.fromisoformat(cached[s]["fetched_at"]) < cutoff
    ]
    if not stale:
        return 0
    results = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for i, result in enumerate(pool.map(_safe(fetch), stale)):
            results.append(result)
            _drop_yfinance_responses()
            if progress and i % 10 == 0:
                progress(i, len(stale), f"Earnings dates {i}/{len(stale)}")
    data.save_earnings([r for r in results if r is not None], db_path)
    return len(stale)


def _drop_yfinance_responses() -> None:
    """yfinance keeps its last 64 raw responses in an lru_cache; earnings pages are a few MB each.

    Nothing here re-reads them, so clearing keeps a 600-symbol earnings pass from holding ~200 MB.
    """
    try:
        from yfinance.data import YfData

        YfData.cache_get.cache_clear()
    except Exception:  # different yfinance internals: just skip
        pass


def _safe(fetch: Callable[[str], dict]) -> Callable[[str], Optional[dict]]:
    def run(symbol: str) -> Optional[dict]:
        try:
            return fetch(symbol)
        except Exception as exc:
            log.warning("earnings lookup failed for %s: %s", symbol, exc)
            return None

    return run
