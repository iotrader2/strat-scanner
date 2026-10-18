"""15-minute bars from a pluggable provider. Prices are raw (unadjusted), like the daily cache.

Yahoo is the default and needs no key. It only serves roughly the last 60 calendar days of
15-minute bars (see ``YAHOO_15M_LOOKBACK_DAYS``; confirmed against the live endpoint).
Older mornings stay in SQLite once they have been stored, and each new session is added
after the close.

Alpaca is optional, for a personal backfill. Set ``STRAT_INTRADAY_PROVIDER=alpaca`` and
``ALPACA_API_KEY_ID`` / ``ALPACA_API_SECRET_KEY`` (the Alpaca dashboard names; ``STRAT_ALPACA_KEY``
and ``STRAT_ALPACA_SECRET`` are accepted too). Nothing is written into the repo. The free Basic
plan serves SIP historical bars when the request ends at least 15 minutes ago, which is the
feed this client asks for (``STRAT_ALPACA_FEED`` overrides it). IEX is a different, partial tape
and is not the default.

A production day is one batched request: the top 10, or about 100 names, for a single session.
That is one Alpaca call (a session of 15-minute bars is a few thousand rows, under the page
limit) or a handful of Yahoo calls. The collector only asks for symbol-days that are not
already stored.
"""

from __future__ import annotations

import os
import time
from datetime import date, datetime, timedelta
from typing import Optional, Protocol
from zoneinfo import ZoneInfo

import pandas as pd

ET = ZoneInfo("America/New_York")

# Checked against Yahoo on 2026-10-18. ``period=60d`` is the widest 15-minute (and 5-minute)
# request that returns data: 60 sessions, 2026-07-24 through 2026-10-16. A start/end range
# older than 60 calendar days is rejected ("must be within the last 60 days"). Hourly bars
# via ``period=730d`` went back to 2023-11-17. The collector uses ``period=60d`` when the
# caller asks for anything older, then keeps whatever came back.
YAHOO_15M_LOOKBACK_DAYS = 59
YAHOO_15M_PERIOD = "60d"
YAHOO_BATCH = 20


class IntradayError(Exception):
    """The provider could not return bars."""


class IntradayAuthError(IntradayError):
    """Credentials are missing or rejected."""


class IntradayProvider(Protocol):
    name: str
    lookback_days: Optional[int]

    def fetch(self, symbols: list[str], start: date, end: date) -> dict[str, pd.DataFrame]:
        """symbol -> raw 15-minute bars indexed by naive US/Eastern bar *end* time."""


def today_et(clock: Optional[datetime] = None) -> date:
    now = clock or datetime.now(ET)
    if now.tzinfo is None:
        now = now.replace(tzinfo=ET)
    return now.astimezone(ET).date()


def clamp_start(start: date, end: date, lookback_days: Optional[int], today: date) -> Optional[date]:
    """Pull ``start`` forward to what this provider will actually serve. None when nothing remains."""
    if lookback_days is not None:
        start = max(start, today - timedelta(days=lookback_days))
    if start > end:
        return None
    return start


def to_session_ends(frame: pd.DataFrame, minutes: int = 15) -> pd.DataFrame:
    """Move a bar-start index to the bar end and keep the regular session (09:45 through 16:00 ET)."""
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    out = frame.copy()
    out.columns = [str(c).lower().replace(" ", "_") for c in out.columns]
    keep = [c for c in ("open", "high", "low", "close", "volume") if c in out.columns]
    out = out[keep].dropna(subset=["open", "high", "low", "close"])
    if out.empty:
        return out
    idx = pd.DatetimeIndex(pd.to_datetime(out.index, utc=False))
    if idx.tz is None:
        idx = idx.tz_localize(ET)
    else:
        idx = idx.tz_convert(ET)
    idx = (idx + pd.Timedelta(minutes=minutes)).tz_localize(None)
    out.index = idx
    clock = out.index.strftime("%H:%M")
    out = out.loc[(clock >= "09:45") & (clock <= "16:00")]
    out = out[~out.index.duplicated(keep="last")].sort_index()
    if "volume" not in out.columns:
        out["volume"] = 0.0
    return out


def _symbol_frame(df: pd.DataFrame, symbol: str, many: bool) -> Optional[pd.DataFrame]:
    if df is None or df.empty:
        return None
    if not many:
        return df
    level0 = df.columns.get_level_values(0)
    if symbol in level0:
        return df[symbol]
    if isinstance(df.columns, pd.MultiIndex) and symbol in df.columns.get_level_values(1):
        return df.xs(symbol, axis=1, level=1)
    return None


class YahooIntraday:
    name = "yahoo"
    lookback_days = YAHOO_15M_LOOKBACK_DAYS

    def fetch(self, symbols: list[str], start: date, end: date) -> dict[str, pd.DataFrame]:
        import yfinance as yf

        today = today_et()
        if start > end or not symbols:
            return {}
        # A start/end pair older than 60 calendar days errors. ``period=60d`` is wider
        # (60 sessions, about 85 calendar days) and is how a backfill gets the whole window.
        use_period = start <= today - timedelta(days=self.lookback_days or YAHOO_15M_LOOKBACK_DAYS)
        end_excl = (end + timedelta(days=1)).isoformat()
        out: dict[str, pd.DataFrame] = {}
        for offset in range(0, len(symbols), YAHOO_BATCH):
            batch = symbols[offset : offset + YAHOO_BATCH]
            kwargs = {"period": YAHOO_15M_PERIOD} if use_period else {"start": start.isoformat(), "end": end_excl}
            df = yf.download(
                batch,
                interval="15m",
                group_by="ticker",
                auto_adjust=False,
                prepost=False,
                progress=False,
                threads=False,
                **kwargs,
            )
            many = isinstance(df.columns, pd.MultiIndex) if df is not None and not df.empty else False
            for symbol in batch:
                sub = _symbol_frame(df, symbol, many and len(batch) > 1)
                if sub is None:
                    continue
                bars = to_session_ends(sub)
                if bars.empty:
                    continue
                lo = pd.Timestamp(start)
                hi = pd.Timestamp(end) + pd.Timedelta(days=1)
                bars = bars.loc[(bars.index >= lo) & (bars.index < hi)]
                if not bars.empty:
                    out[symbol] = bars
        return out


class AlpacaIntraday:
    """SIP 15-minute bars from Alpaca's free Basic plan (history since 2016, 15-minute delay)."""

    name = "alpaca"
    lookback_days = None
    url = "https://data.alpaca.markets/v2/stocks/bars"

    def __init__(self, feed: Optional[str] = None):
        self.feed = (feed or os.environ.get("STRAT_ALPACA_FEED") or "sip").strip().lower()

    def _keys(self) -> tuple[str, str]:
        key = os.environ.get("ALPACA_API_KEY_ID") or os.environ.get("STRAT_ALPACA_KEY")
        secret = os.environ.get("ALPACA_API_SECRET_KEY") or os.environ.get("STRAT_ALPACA_SECRET")
        if not key or not secret:
            raise IntradayAuthError(
                "Alpaca backfill needs ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY. "
                "The free Basic plan is enough; do not commit the keys."
            )
        return key, secret

    def fetch(self, symbols: list[str], start: date, end: date) -> dict[str, pd.DataFrame]:
        import httpx

        if not symbols:
            return {}
        key, secret = self._keys()
        headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
        # One symbol per page once a year of 15-minute bars is in play (~6,500 rows, page limit 10,000).
        # A single session of ~100 names fits in one page, which is the daily job.
        span = (end - start).days
        chunk = 1 if span > 40 else 80
        collected: dict[str, list[dict]] = {s: [] for s in symbols}
        with httpx.Client(timeout=60) as client:
            for offset in range(0, len(symbols), chunk):
                batch = symbols[offset : offset + chunk]
                token = None
                while True:
                    params = {
                        "symbols": ",".join(batch),
                        "timeframe": "15Min",
                        # Midnight UTC on start is the previous evening in New York, so the session is included.
                        # Midnight UTC the day after end is after that session's close.
                        "start": f"{start.isoformat()}T00:00:00Z",
                        "end": f"{(end + timedelta(days=1)).isoformat()}T00:00:00Z",
                        "adjustment": "raw",
                        "feed": self.feed,
                        "limit": 10000,
                        "sort": "asc",
                    }
                    if token:
                        params["page_token"] = token
                    payload = _alpaca_get(client, self.url, headers, params)
                    bars = payload.get("bars") or {}
                    for symbol, rows in bars.items():
                        collected.setdefault(symbol, []).extend(rows)
                    token = payload.get("next_page_token")
                    if not token:
                        break
        out = {}
        for symbol, rows in collected.items():
            if not rows:
                continue
            frame = pd.DataFrame(
                {
                    "open": [r["o"] for r in rows],
                    "high": [r["h"] for r in rows],
                    "low": [r["l"] for r in rows],
                    "close": [r["c"] for r in rows],
                    "volume": [r.get("v") or 0 for r in rows],
                },
                index=pd.to_datetime([r["t"] for r in rows], utc=True),
            )
            bars = to_session_ends(frame)
            if not bars.empty:
                out[symbol] = bars
        return out


def _alpaca_get(client, url: str, headers: dict, params: dict) -> dict:
    for attempt in range(4):
        response = client.get(url, headers=headers, params=params)
        if response.status_code == 429:
            time.sleep(float(response.headers.get("Retry-After", 1 + attempt)))
            continue
        if response.status_code in (401, 403):
            raise IntradayAuthError(f"Alpaca returned {response.status_code}: {response.text[:300]}")
        if response.status_code >= 400:
            raise IntradayError(f"Alpaca returned {response.status_code}: {response.text[:300]}")
        return response.json()
    raise IntradayError("Alpaca rate limit did not clear")


def get_intraday_provider(name: Optional[str] = None) -> IntradayProvider:
    picked = (name or os.environ.get("STRAT_INTRADAY_PROVIDER") or "yahoo").strip().lower()
    if picked == "yahoo":
        return YahooIntraday()
    if picked == "alpaca":
        return AlpacaIntraday()
    raise ValueError(f"Unknown STRAT_INTRADAY_PROVIDER {picked!r} (expected 'yahoo' or 'alpaca')")
