"""Today's session from Alpaca 5-minute bars.

Every poll (about 10 seconds after each 5-minute mark, see ``scheduler.intraday_due``):

1. IEX 5-minute bars (real time, free) since the last IEX bar already stored, for the whole universe.
2. SIP 5-minute bars (all exchanges) for every bar that closed at least 15 minutes ago. They overwrite
   the IEX rows with the same timestamp, so the stored history is exact once it is old enough.
3. Today's daily bar is rebuilt from the stored bars and written to ``session_bar`` (the scan overlays it):
   open / high / low / close from all of today's bars (SIP where backfilled, IEX for the last ~15 minutes),
   volume from the SIP bars only. IEX volume is ~2.5% of the market and is never mixed into the volume
   that the 20-day averages compare against; today's volume therefore trails by ~15 minutes.

The table keeps only the current session; older rows are deleted at the first poll of a new day.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Optional

from . import data
from .alpaca import SIP_DELAY, SIP_MARGIN, AlpacaClient, from_alpaca
from .scheduler import ET, OPEN, now_et

log = logging.getLogger(__name__)

BAR = timedelta(minutes=5)
IEX_MARK = "intraday_iex_through"
SIP_MARK = "intraday_sip_through"

def session_open_utc(now: datetime) -> datetime:
    local = now_et(now)
    return datetime.combine(local.date(), OPEN, tzinfo=ET).astimezone(timezone.utc)


def floor_bar(ts: datetime, minutes: int = 5) -> datetime:
    ts = ts.astimezone(timezone.utc)
    return ts.replace(minute=ts.minute - ts.minute % minutes, second=0, microsecond=0)


def sip_cutoff(now: datetime, minutes: int = 5) -> datetime:
    """Bars of ``minutes`` starting before this instant closed at least 15 minutes (plus a margin) ago."""
    return floor_bar(now.astimezone(timezone.utc) - SIP_DELAY - SIP_MARGIN, minutes)


def _iso(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _mark(key: str, today_open: datetime, db_path) -> datetime:
    raw = data.get_meta(key, db_path)
    if raw:
        try:
            ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if ts >= today_open:
                return ts
        except ValueError:
            pass
    return today_open


def upsert(rows: list[tuple], feed: str, db_path: Path | None = None) -> int:
    """Store (symbol, ts, o, h, l, c, v). SIP rows replace anything; IEX rows never replace a SIP row."""
    if not rows:
        return 0
    if feed == "sip":
        sql = (
            "INSERT OR REPLACE INTO intraday_bars(symbol, ts, open, high, low, close, volume, feed) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'sip')"
        )
    else:
        sql = (
            "INSERT INTO intraday_bars(symbol, ts, open, high, low, close, volume, feed) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(symbol, ts) DO UPDATE SET open = excluded.open, high = excluded.high, low = excluded.low, "
            "close = excluded.close, volume = excluded.volume, feed = excluded.feed WHERE intraday_bars.feed != 'sip'"
        )
        rows = [(*r, feed) for r in rows]
    with data._write_lock, data.connect(db_path) as conn:
        conn.executemany(sql, rows)
    return len(rows)


def _rows(bars: dict[str, list[dict]], start: datetime, before: Optional[datetime] = None) -> list[tuple]:
    out = []
    for sym, items in bars.items():
        for b in items:
            ts = datetime.fromisoformat(b["t"].replace("Z", "+00:00"))
            if ts < start or (before is not None and ts >= before):
                continue
            out.append((from_alpaca(sym), _iso(ts), float(b["o"]), float(b["h"]), float(b["l"]), float(b["c"]), float(b.get("v") or 0)))
    return out


def prune(today_open: datetime, db_path: Path | None = None) -> None:
    with data._write_lock, data.connect(db_path) as conn:
        conn.execute("DELETE FROM intraday_bars WHERE ts < ?", (_iso(today_open),))


def session_bars(db_path: Path | None = None) -> dict[str, dict]:
    """Today's daily bar per symbol from the stored 5-minute bars."""
    with data.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT symbol, ts, open, high, low, close, volume, feed FROM intraday_bars ORDER BY symbol, ts"
        ).fetchall()
    out: dict[str, dict] = {}
    for sym, ts, o, h, low, c, v, feed in rows:
        bar = out.get(sym)
        sip_v = v if feed == "sip" else 0.0
        if bar is None:
            out[sym] = {"date": ts, "open": o, "high": h, "low": low, "close": c, "volume": sip_v}
            continue
        bar["high"] = max(bar["high"], h)
        bar["low"] = min(bar["low"], low)
        bar["close"] = c
        bar["volume"] += sip_v
    return out


def poll(
    symbols: list[str],
    now: datetime | None = None,
    client: AlpacaClient | None = None,
    db_path: Path | None = None,
) -> dict:
    """One 5-minute poll. Returns counts for the log line."""
    clock = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    client = client or AlpacaClient()
    before = client.requests
    today_open = session_open_utc(clock)
    if clock < today_open:
        return {"iex": 0, "sip": 0, "symbols": 0, "requests": 0}
    prune(today_open, db_path)

    # 1. IEX, real time. Refetch the last stored bar: it may have been still forming last time.
    iex_from = _mark(IEX_MARK, today_open, db_path)
    iex, _ = client.bars(symbols, "5Min", iex_from, end=clock, feed="iex", adjustment="raw")
    iex_rows = _rows(iex, today_open)
    n_iex = upsert(iex_rows, "iex", db_path)
    if iex_rows:
        data.set_meta(IEX_MARK, max(r[1] for r in iex_rows), db_path)

    # 2. SIP backfill for bars that closed at least 15 minutes ago.
    cutoff = sip_cutoff(clock)
    sip_from = _mark(SIP_MARK, today_open, db_path)
    n_sip = 0
    if cutoff > sip_from:
        sip, _ = client.bars(
            symbols, "5Min", sip_from, end=cutoff - timedelta(seconds=1), feed="sip", adjustment="raw"
        )
        sip_rows = _rows(sip, sip_from, before=cutoff)
        n_sip = upsert(sip_rows, "sip", db_path)
        data.set_meta(SIP_MARK, _iso(cutoff), db_path)

    # 3. Today's daily bar.
    built = session_bars(db_path)
    day = now_et(clock).date().isoformat()
    data.save_session_bars(
        [(sym, day, b["open"], b["high"], b["low"], b["close"], b["volume"]) for sym, b in built.items()], db_path
    )
    data.set_meta("last_refresh", datetime.now(timezone.utc).isoformat(timespec="seconds"), db_path)
    return {"iex": n_iex, "sip": n_sip, "symbols": len(built), "requests": client.requests - before}
