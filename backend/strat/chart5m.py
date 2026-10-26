"""On-demand 5-minute chart for one symbol: regular-session bars and EMAs.

The chart page asks for a single ticker. This module fetches that ticker from Alpaca
(the same 5-minute client the live poll uses), keeps a small bounded cache, and
returns only the last few sessions. It does not touch the other names in the universe.

Premarket and after-hours bars are dropped. The watchlist's 5-minute EMAs already use
regular-session bars only (09:30-16:00 ET, :func:`watch5m.is_regular`), and the live
poll stores the session from the open. The chart follows that same cut so the 5, 20,
50, and 360 EMAs are not mixed with the thin premarket prints.

The 360-period EMA is the stand-in for a 30-period hourly average (360 five-minute
bars = 30 hours). An EMA seeded with the SMA of its first period is still mostly that
seed until many more bars have passed, so history covers ``SEED_SESSIONS`` completed
sessions (several weeks) even though the response only includes ``DISPLAY_SESSIONS``.

Prices are the SIP bar once it is 15 minutes old and the IEX bar after that, matching
:mod:`strat.intraday`. Volume rides along with whichever feed supplied the bar, so the
last quarter-hour is IEX volume (a small share of the market) until SIP replaces it.

Cache: at most ``CACHE_LIMIT`` symbols. Each entry is the completed-session tuples
(about 30 x 78 bars) plus today's handful of bars. That is a few megabytes for a full
cache, allocated only for tickers someone actually opened. The raw Alpaca payload is
discarded after the regular-session filter.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from datetime import date, datetime, time as clock_time, timedelta, timezone
from typing import Optional

from .alpaca import AlpacaClient
from .intraday import sip_cutoff
from .scheduler import CLOSE, ET, OPEN, last_completed_session, now_et
from .watch5m import ema_series, is_regular

EMA_PERIODS = (5, 20, 50, 360)
DISPLAY_SESSIONS = 5
SEED_SESSIONS = 30  # ~6 weeks; the 360 EMA's seed has faded by the displayed window
LOOKBACK_DAYS = 56  # calendar days that cover SEED_SESSIONS plus weekends and holidays
CACHE_LIMIT = 8
TODAY_TTL = 45.0  # seconds; today's bars change on the 5-minute poll, history does not

Bar = tuple[int, float, float, float, float, float]  # unix seconds, o, h, l, c, v

_lock = threading.Lock()
# symbol -> completed sessions through a date, plus a short-lived copy of today
_cache: OrderedDict[str, dict] = OrderedDict()


def clear() -> None:
    with _lock:
        _cache.clear()


def _at(day: date, t: clock_time) -> datetime:
    return datetime.combine(day, t, tzinfo=ET).astimezone(timezone.utc)


def _parse(raw: str) -> datetime:
    return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(timezone.utc)


def _day(ts: int) -> date:
    return datetime.fromtimestamp(ts, ET).date()


def regular_bars(rows: list[dict]) -> list[Bar]:
    """Regular-session OHLCV, oldest first. Premarket, after-hours, and weekend bars are omitted."""
    by: dict[int, Bar] = {}
    for b in rows:
        try:
            ts = _parse(b["t"])
            o, h, low, c = (float(b["o"]), float(b["h"]), float(b["l"]), float(b["c"]))
        except (KeyError, TypeError, ValueError):
            continue
        if not is_regular(ts) or min(o, h, low, c) <= 0:
            continue
        stamp = int(ts.timestamp())
        by[stamp] = (stamp, o, h, low, c, float(b.get("v") or 0))
    return [by[k] for k in sorted(by)]


def merge_feeds(sip: list[Bar], iex: list[Bar], cutoff: int) -> list[Bar]:
    """SIP for bars that started before ``cutoff`` (unix seconds), IEX from ``cutoff`` on."""
    by = {row[0]: row for row in iex if row[0] >= cutoff}
    for row in sip:
        if row[0] < cutoff:
            by[row[0]] = row
    return [by[k] for k in sorted(by)]


def keep_sessions(rows: list[Bar], sessions: int, through: Optional[date] = None) -> list[Bar]:
    """The last ``sessions`` distinct regular-session dates, optionally cut off at ``through``."""
    if through is not None:
        rows = [r for r in rows if _day(r[0]) <= through]
    days = sorted({_day(r[0]) for r in rows})
    if sessions > 0:
        days = days[-sessions:]
    keep = set(days)
    return [r for r in rows if _day(r[0]) in keep]


def _fetch(client: AlpacaClient, symbol: str, start: datetime, end: datetime, feed: str) -> list[Bar]:
    if end <= start:
        return []
    # One symbol. The live poll uses this same bars() path for the whole universe; a chart must not.
    payload, _invalid = client.bars([symbol], "5Min", start, end=end, feed=feed, adjustment="raw")
    rows = payload.get(symbol, [])
    parsed = regular_bars(rows)
    del payload, rows
    return parsed


def _want_today(clock: datetime, through: date) -> bool:
    """Today's session is still forming (or not yet confirmed into history). Never premarket."""
    local = now_et(clock)
    if local.weekday() >= 5 or local.time() < OPEN:
        return False
    return through != local.date()


def _load_history(client: AlpacaClient, symbol: str, through: date, clock: datetime) -> list[Bar]:
    start = _at(through - timedelta(days=LOOKBACK_DAYS), OPEN)
    end = min(_at(through, CLOSE), sip_cutoff(clock))
    rows = _fetch(client, symbol, start, end, "sip")
    return keep_sessions(rows, SEED_SESSIONS, through)


def _load_today(client: AlpacaClient, symbol: str, clock: datetime) -> list[Bar]:
    day = now_et(clock).date()
    open_, close_ = _at(day, OPEN), _at(day, CLOSE)
    cutoff = sip_cutoff(clock)
    end = min(clock, close_)
    sip = _fetch(client, symbol, open_, min(cutoff, close_) - timedelta(seconds=1), "sip")
    iex = _fetch(client, symbol, max(open_, cutoff), end, "iex")
    merged = merge_feeds(sip, iex, int(cutoff.timestamp()))
    return [r for r in merged if _day(r[0]) == day]


def _history(symbol: str, through: date, clock: datetime, client: AlpacaClient) -> list[Bar]:
    key = through.isoformat()
    with _lock:
        hit = _cache.get(symbol)
        if hit and hit["through"] == key:
            _cache.move_to_end(symbol)
            return list(hit["history"])
    bars = _load_history(client, symbol, through, clock)
    with _lock:
        _cache[symbol] = {"through": key, "history": tuple(bars), "today_day": None, "today_at": 0.0, "today": ()}
        _cache.move_to_end(symbol)
        while len(_cache) > CACHE_LIMIT:
            _cache.popitem(last=False)
    return bars


def _today(symbol: str, clock: datetime, client: AlpacaClient) -> list[Bar]:
    day = now_et(clock).date().isoformat()
    now_m = time.monotonic()
    with _lock:
        hit = _cache.get(symbol)
        if hit and hit["today_day"] == day and now_m - hit["today_at"] < TODAY_TTL:
            _cache.move_to_end(symbol)
            return list(hit["today"])
    bars = _load_today(client, symbol, clock)
    with _lock:
        entry = _cache.get(symbol)
        if entry is None:
            entry = {"through": None, "history": (), "today_day": None, "today_at": 0.0, "today": ()}
            _cache[symbol] = entry
        entry["today_day"] = day
        entry["today_at"] = now_m
        entry["today"] = tuple(bars)
        _cache.move_to_end(symbol)
        while len(_cache) > CACHE_LIMIT:
            _cache.popitem(last=False)
    return bars


def _payload(symbol: str, rows: list[Bar]) -> dict:
    closes = [r[4] for r in rows]
    series = {p: ema_series(closes, p) for p in EMA_PERIODS}
    shown = keep_sessions(rows, DISPLAY_SESSIONS)
    offset = len(rows) - len(shown)
    bars = []
    for i, row in enumerate(shown):
        idx = offset + i
        bars.append(
            {
                "time": row[0],
                "open": round(row[1], 4),
                "high": round(row[2], 4),
                "low": round(row[3], 4),
                "close": round(row[4], 4),
                "volume": row[5],
                "ema": {str(p): (None if series[p][idx] is None else round(series[p][idx], 4)) for p in EMA_PERIODS},
            }
        )
    sessions = len({_day(r[0]) for r in shown})
    return {
        "symbol": symbol,
        "session": "regular",
        "bar_minutes": 5,
        "time_zone": "America/New_York",
        "display_sessions": DISPLAY_SESSIONS,
        "seed_sessions": SEED_SESSIONS,
        "sessions": sessions,
        "bars": bars,
    }


def chart(symbol: str, now: Optional[datetime] = None, client: Optional[AlpacaClient] = None) -> dict:
    """5-minute regular-session bars and EMAs for ``symbol``.

    ``client`` is injectable so tests never touch the network. The default client is the
    shared Alpaca client (SIP clamped to the 15-minute delay, IEX real time).
    """
    symbol = symbol.strip().upper()
    clock = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    client = client or AlpacaClient()
    through = last_completed_session(clock)
    history = _history(symbol, through, clock, client)
    today: list[Bar] = []
    if _want_today(clock, through):
        today = _today(symbol, clock, client)
        today_date = now_et(clock).date()
        history = [r for r in history if _day(r[0]) < today_date]
    merged = keep_sessions(history + today, SEED_SESSIONS)
    return _payload(symbol, merged)
