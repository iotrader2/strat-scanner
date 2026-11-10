"""Consolidated 15-minute bars from Yahoo Finance, for the minutes Alpaca SIP has not published yet.

Free Alpaca SIP is 15 minutes delayed, and IEX misses trades, so a trigger set from the IEX high sits
below the real candle. ``query1.finance.yahoo.com/v8/finance/chart`` is consolidated and near real time.
One chart request per symbol, a few at a time. A symbol that fails is omitted; the caller uses IEX for it.
"""

from __future__ import annotations

import logging
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Optional

import httpx

from .scheduler import CLOSE, ET, OPEN
from .universe import to_yahoo

log = logging.getLogger(__name__)

CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{}"
_WORKERS = 8
_UA = "Mozilla/5.0 (compatible; TiltKiller/1.0)"
GetChart = Callable[[str, dict], tuple[Optional[dict], Optional[str]]]


def _regular(ts: datetime) -> bool:
    local = ts.astimezone(ET)
    if local.time() >= CLOSE:
        return False
    minutes = (local.hour * 60 + local.minute) - (OPEN.hour * 60 + OPEN.minute)
    return minutes >= 0 and minutes % 15 == 0


def parse_chart(payload: dict, day: date) -> list[dict]:
    """Regular-session 15-minute bars on ``day`` from one chart response, oldest first."""
    result = (payload.get("chart") or {}).get("result") or []
    if not result or not isinstance(result[0], dict):
        return []
    block = result[0]
    stamps = block.get("timestamp") or []
    quote = ((block.get("indicators") or {}).get("quote") or [{}])[0]
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []
    out = []
    for i, raw in enumerate(stamps):
        try:
            t = datetime.fromtimestamp(int(raw), timezone.utc).replace(second=0, microsecond=0)
            o, h, l, c = float(opens[i]), float(highs[i]), float(lows[i]), float(closes[i])
        except (TypeError, ValueError, IndexError, OSError):
            continue
        if t.astimezone(ET).date() != day or not _regular(t) or h < l:
            continue
        try:
            v = float(volumes[i] or 0)
        except (TypeError, ValueError, IndexError):
            v = 0.0
        out.append({"t": t, "o": o, "h": h, "l": l, "c": c, "v": v, "src": "yahoo"})
    out.sort(key=lambda b: b["t"])
    return out


def _download(client: httpx.Client, symbol: str, params: dict) -> tuple[Optional[dict], Optional[str]]:
    ysym = to_yahoo(symbol)
    url = CHART.format(urllib.parse.quote(ysym, safe="-"))
    try:
        response = client.get(url, params=params)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return None, str(exc)
    err = (payload.get("chart") or {}).get("error") if isinstance(payload, dict) else "not a chart response"
    if err:
        return None, str(err)
    return payload, None


def fetch_yahoo_15m(
    symbols: list[str], day: date, now: datetime | None = None, get: GetChart | None = None
) -> tuple[dict[str, list[dict]], set[str]]:
    """``(symbol -> bars, symbols Yahoo did not return)``.

    The dict is the whole poll: callers must not fetch again for the same pass. Failures are logged
    and listed so the caller can price those names from IEX.
    """
    symbols = list(dict.fromkeys(s for s in symbols if s))
    if not symbols:
        return {}, set()
    start = datetime.combine(day, OPEN, tzinfo=ET)
    end = datetime.combine(day, CLOSE, tzinfo=ET)
    if now is not None:
        end = min(end, now.astimezone(timezone.utc))
    # period2 has to sit past the bar still forming or Yahoo omits it.
    params = {
        "interval": "15m",
        "period1": str(int(start.timestamp())),
        "period2": str(int((end + timedelta(minutes=20)).timestamp())),
        "includePrePost": "false",
    }
    own_client = None
    getter = get
    if getter is None:
        own_client = httpx.Client(timeout=httpx.Timeout(6.0, connect=3.0), headers={"User-Agent": _UA})
        getter = lambda sym, query, _client=own_client: _download(_client, sym, query)
    bars: dict[str, list[dict]] = {}
    failed: set[str] = set()
    try:
        with ThreadPoolExecutor(max_workers=min(_WORKERS, len(symbols))) as pool:
            futures = {pool.submit(getter, sym, params): sym for sym in symbols}
            for fut in as_completed(futures):
                sym = futures[fut]
                try:
                    payload, err = fut.result()
                except Exception as exc:
                    payload, err = None, str(exc)
                if err or not payload:
                    failed.add(sym)
                    log.warning("Yahoo 15m failed for %s (%s); recent alert bars will use IEX", sym, err or "empty")
                    continue
                parsed = parse_chart(payload, day)
                if parsed:
                    bars[sym] = parsed
                else:
                    failed.add(sym)
                    log.warning("Yahoo 15m failed for %s (no regular-session bars); recent alert bars will use IEX", sym)
    finally:
        if own_client is not None:
            own_client.close()
    return bars, failed
