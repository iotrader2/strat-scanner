"""Alpaca Market Data API client (free Basic plan).

Credentials come from ``ALPACA_API_KEY_ID`` / ``ALPACA_API_SECRET_KEY`` and are sent as the
``APCA-API-KEY-ID`` / ``APCA-API-SECRET-KEY`` headers. They are never logged.

Free-plan rules this client follows:

* SIP (all US exchanges) is only served at least 15 minutes after the fact. A request whose ``end``
  is newer than that gets ``403 subscription does not permit querying recent SIP data``, so
  :func:`pick_feed` clamps ``end`` (or switches to ``ALPACA_RECENT_FEED`` when that is set).
* IEX is real time but only ~2.5% of US volume. It is used for today's prices, never for volume
  compared against full-market averages.
* 200 requests per minute. :class:`RateLimiter` keeps a sliding window under ``ALPACA_MAX_RPM``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Iterable, Iterator, Optional
from zoneinfo import ZoneInfo

import pandas as pd

log = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
DATA_URL = os.environ.get("ALPACA_DATA_URL", "https://data.alpaca.markets").rstrip("/")
KEY_ENV = "ALPACA_API_KEY_ID"
SECRET_ENV = "ALPACA_API_SECRET_KEY"
SIP_DELAY = timedelta(minutes=int(os.environ.get("ALPACA_SIP_DELAY_MINUTES", "15")))
# One extra minute so a request built a few seconds before it is sent is still old enough.
SIP_MARGIN = timedelta(minutes=1)
PAGE_LIMIT = 10000
SYMBOLS_PER_REQUEST = int(os.environ.get("ALPACA_SYMBOLS_PER_REQUEST", "200"))
MAX_RPM = int(os.environ.get("ALPACA_MAX_RPM", "180"))
# "clamp": keep feed=sip and move ``end`` back to 15 minutes ago (works on the free plan).
# "delayed_sip": ask for the delayed feed instead (only on plans that accept it).
RECENT_FEED = os.environ.get("ALPACA_RECENT_FEED", "clamp").strip().lower()
ADJUSTMENT = os.environ.get("ALPACA_ADJUSTMENT", "raw").strip().lower()
TIMEOUT = 30


class AlpacaError(Exception):
    """A request failed after retries."""


def has_credentials() -> bool:
    return bool(os.environ.get(KEY_ENV, "").strip() and os.environ.get(SECRET_ENV, "").strip())


def to_alpaca(symbol: str) -> str:
    """Universe / Yahoo form to Alpaca form: class shares use a dot (``BRK-B`` -> ``BRK.B``)."""
    return symbol.strip().upper().replace("-", ".")


def from_alpaca(symbol: str) -> str:
    """Alpaca form back to the universe form (``BRK.B`` -> ``BRK-B``)."""
    return symbol.strip().upper().replace(".", "-")


def pick_feed(end: Optional[datetime], now: Optional[datetime] = None) -> tuple[str, datetime]:
    """Feed and ``end`` for a historical (SIP) request.

    ``end`` at least 15 minutes old stays on ``sip``. A newer ``end`` (or none, meaning "now") is
    either clamped to 15 minutes ago on ``sip`` (default) or sent unchanged on ``delayed_sip``
    when ``ALPACA_RECENT_FEED=delayed_sip``.
    """
    clock = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    latest = clock - SIP_DELAY - SIP_MARGIN
    if end is not None:
        end = end.astimezone(timezone.utc) if end.tzinfo else end.replace(tzinfo=timezone.utc)
        if end <= latest:
            return "sip", end
    if RECENT_FEED == "delayed_sip":
        return "delayed_sip", end or clock
    return "sip", latest


def period_start(period: str, today: Optional[date] = None) -> date:
    """Start date for a yfinance-style period (``5d``, ``3mo``, ``3y``, ``max``)."""
    today = today or datetime.now(ET).date()
    p = period.strip().lower()
    m = re.fullmatch(r"(\d+)(d|wk|mo|y)", p)
    if p == "max" or not m:
        return date(2016, 1, 1)
    n, unit = int(m.group(1)), m.group(2)
    if unit == "d":
        # Trading days: weekends and a holiday fit comfortably in twice the calendar span.
        return today - timedelta(days=max(2 * n, n + 4))
    if unit == "wk":
        return today - timedelta(weeks=n)
    if unit == "mo":
        return (pd.Timestamp(today) - pd.DateOffset(months=n)).date()
    return (pd.Timestamp(today) - pd.DateOffset(years=n)).date()


def _iso(ts: datetime | date) -> str:
    if isinstance(ts, datetime):
        ts = ts.astimezone(timezone.utc) if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        return ts.strftime("%Y-%m-%dT%H:%M:%SZ")
    return ts.isoformat()


class RateLimiter:
    """Sliding one-minute window shared by every request in the process."""

    def __init__(self, per_minute: int = MAX_RPM, clock: Callable[[], float] = time.monotonic, sleep=time.sleep):
        self.per_minute = max(1, per_minute)
        self.clock = clock
        self.sleep = sleep
        self.sent: deque[float] = deque()
        self.lock = threading.Lock()
        self.count = 0

    def wait(self) -> None:
        with self.lock:
            while True:
                now = self.clock()
                while self.sent and now - self.sent[0] >= 60:
                    self.sent.popleft()
                if len(self.sent) < self.per_minute:
                    self.sent.append(now)
                    self.count += 1
                    return
                self.sleep(max(0.05, 60 - (now - self.sent[0])))


_LIMITER = RateLimiter()


def _default_transport(url: str, headers: dict) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, dict(resp.headers.items()), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers.items()) if exc.headers else {}, exc.read()


Transport = Callable[[str, dict], tuple[int, dict, bytes]]


class AlpacaClient:
    """Thin JSON client. ``transport`` is injectable so tests never touch the network."""

    def __init__(self, transport: Transport | None = None, limiter: RateLimiter | None = None, sleep=time.sleep):
        self.transport = transport or _default_transport
        self.limiter = limiter or _LIMITER
        self.sleep = sleep
        self.requests = 0

    def _headers(self) -> dict:
        key = os.environ.get(KEY_ENV, "").strip()
        secret = os.environ.get(SECRET_ENV, "").strip()
        if not key or not secret:
            raise AlpacaError(f"{KEY_ENV} / {SECRET_ENV} are not set")
        return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret, "Accept": "application/json"}

    def get(self, path: str, params: dict) -> dict:
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        url = f"{DATA_URL}{path}?{query}"
        last = ""
        for attempt in range(4):
            self.limiter.wait()
            self.requests += 1
            try:
                status, headers, body = self.transport(url, self._headers())
            except Exception as exc:  # network error: back off and retry
                last = f"{type(exc).__name__}: {exc}"
                self.sleep(2 * (attempt + 1))
                continue
            if status == 200:
                return json.loads(body or b"{}")
            message = _message(body)
            if status == 429:
                reset = _header(headers, "x-ratelimit-reset")
                wait = max(1.0, float(reset) - time.time()) if reset and reset.isdigit() else 5.0
                self.sleep(min(wait, 60.0))
                last = f"429 {message}"
                continue
            if status >= 500:
                last = f"{status} {message}"
                self.sleep(2 * (attempt + 1))
                continue
            raise HTTPStatus(status, message)
        raise AlpacaError(f"GET {path} failed: {last}")

    def bars(
        self,
        symbols: Iterable[str],
        timeframe: str,
        start: datetime | date,
        end: Optional[datetime] = None,
        feed: Optional[str] = None,
        adjustment: str = ADJUSTMENT,
        now: Optional[datetime] = None,
    ) -> tuple[dict[str, list[dict]], list[str]]:
        """Bars keyed by universe symbol, plus symbols Alpaca rejected as invalid.

        ``symbols`` are universe symbols (``BRK-B``). Batched ``SYMBOLS_PER_REQUEST`` at a time and
        paginated with ``next_page_token``. ``feed=None`` means SIP with :func:`pick_feed` applied.
        """
        if feed is None or feed == "sip":
            feed, end = pick_feed(end, now)
        out: dict[str, list[dict]] = {}
        invalid: list[str] = []
        syms = list(dict.fromkeys(symbols))
        for i in range(0, len(syms), SYMBOLS_PER_REQUEST):
            batch = [to_alpaca(s) for s in syms[i : i + SYMBOLS_PER_REQUEST]]
            while batch:
                try:
                    for sym, rows in self._paged_bars(batch, timeframe, start, end, feed, adjustment):
                        out.setdefault(from_alpaca(sym), []).extend(rows)
                    break
                except HTTPStatus as exc:
                    bad = _invalid_symbol(exc.message)
                    if exc.status == 400 and bad and bad in batch:
                        # One malformed ticker fails the whole request; drop it and resend the rest.
                        invalid.append(from_alpaca(bad))
                        batch = [s for s in batch if s != bad]
                        continue
                    raise
        return out, invalid

    def _paged_bars(self, batch, timeframe, start, end, feed, adjustment) -> Iterator[tuple[str, list[dict]]]:
        token = None
        while True:
            payload = self.get(
                "/v2/stocks/bars",
                {
                    "symbols": ",".join(batch),
                    "timeframe": timeframe,
                    "start": _iso(start),
                    "end": _iso(end) if end is not None else None,
                    "feed": feed,
                    "adjustment": adjustment,
                    "limit": PAGE_LIMIT,
                    "sort": "asc",
                    "page_token": token,
                },
            )
            for sym, rows in (payload.get("bars") or {}).items():
                yield sym, rows
            token = payload.get("next_page_token")
            if not token:
                return

    def corporate_actions(self, symbols: Iterable[str], start: date, end: date) -> dict[str, dict[str, list]]:
        """Splits and spin-offs, keyed by universe symbol.

        ``{"AAA": {"splits": [(ex_date, ratio)], "spinoffs": [ex_date]}}``. A split ratio of 4.0 is 4-for-1
        and 0.1 is 1-for-10. Spin-offs carry no usable price ratio; :func:`validate_actions` derives one
        from the bars around the ex-date.
        """
        out: dict[str, dict[str, list]] = {}
        syms = [to_alpaca(s) for s in dict.fromkeys(symbols)]
        for i in range(0, len(syms), SYMBOLS_PER_REQUEST):
            token = None
            while True:
                payload = self.get(
                    "/v1/corporate-actions",
                    {
                        "symbols": ",".join(syms[i : i + SYMBOLS_PER_REQUEST]),
                        "types": "forward_split,reverse_split,spin_off",
                        "start": _iso(start),
                        "end": _iso(end),
                        "limit": 1000,
                        "page_token": token,
                    },
                )
                actions = payload.get("corporate_actions") or {}
                for kind in ("forward_splits", "reverse_splits"):
                    for row in actions.get(kind) or []:
                        try:
                            ratio = float(row["new_rate"]) / float(row["old_rate"])
                        except (KeyError, TypeError, ValueError, ZeroDivisionError):
                            continue
                        if ratio and ratio != 1.0 and row.get("ex_date") and row.get("symbol"):
                            entry = out.setdefault(from_alpaca(row["symbol"]), {"splits": [], "spinoffs": []})
                            entry["splits"].append((row["ex_date"], ratio))
                for row in actions.get("spin_offs") or []:
                    if row.get("source_symbol") and row.get("ex_date"):
                        entry = out.setdefault(from_alpaca(row["source_symbol"]), {"splits": [], "spinoffs": []})
                        entry["spinoffs"].append(row["ex_date"])
                token = payload.get("next_page_token")
                if not token:
                    break
        for entry in out.values():
            entry["splits"] = sorted(set(entry["splits"]))
            entry["spinoffs"] = sorted(set(entry["spinoffs"]))
        return out


# A reported split is kept when the raw gap across its ex-date is within this factor of the ratio
# (prior close / ex-date open). Alpaca has listed a CUSIP change as a 1-for-2 reverse split (HON,
# 2026-06-29) with no price jump; applying it would halve that history.
SPLIT_CHECK = 1.4
# A spin-off adjusts earlier prices by the ex-date gap (prior close / ex-date open) when the parent
# drops at least this much; smaller gaps are ordinary overnight moves and are left alone.
SPINOFF_MIN_FACTOR = float(os.environ.get("ALPACA_SPINOFF_MIN_FACTOR", "1.05"))


def _gap(frame: pd.DataFrame, ex_date: str) -> Optional[float]:
    """Prior close / ex-date open from raw bars, or None when the bars do not straddle the ex-date."""
    if frame is None or frame.empty:
        return None
    ex = pd.Timestamp(ex_date)
    before = frame[frame.index < ex]
    after = frame[frame.index >= ex]
    if before.empty or after.empty:
        return None
    prev, first = float(before["Close"].iloc[-1]), float(after["Open"].iloc[0])
    if prev <= 0 or first <= 0:
        return None
    return prev / first


def validate_actions(
    frame: pd.DataFrame, actions: dict[str, list]
) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    """(splits, spin-off price factors) checked against the raw bars around each ex-date."""
    splits: list[tuple[str, float]] = []
    for ex, ratio in actions.get("splits", []):
        gap = _gap(frame, ex)
        if gap is None or 1 / SPLIT_CHECK <= gap / ratio <= SPLIT_CHECK:
            splits.append((ex, ratio))
        else:
            log.warning("ignoring reported split %s %s: price gap %.3f does not match", ex, ratio, gap)
    split_dates = {ex for ex, _ in splits}
    spins: list[tuple[str, float]] = []
    for ex in actions.get("spinoffs", []):
        gap = _gap(frame, ex)
        if ex in split_dates or gap is None or gap < SPINOFF_MIN_FACTOR:
            continue
        spins.append((ex, round(gap, 6)))
    return splits, spins


class HTTPStatus(AlpacaError):
    def __init__(self, status: int, message: str):
        super().__init__(f"{status} {message}")
        self.status = status
        self.message = message


def _message(body: bytes) -> str:
    try:
        return str(json.loads(body).get("message") or "")[:200]
    except Exception:
        return (body or b"")[:200].decode("utf-8", "replace")


def _header(headers: dict, name: str) -> Optional[str]:
    for k, v in (headers or {}).items():
        if k.lower() == name:
            return v
    return None


def _invalid_symbol(message: str) -> Optional[str]:
    m = re.search(r"invalid symbol:?\s*(\S+)", message or "")
    return m.group(1).upper() if m else None


def daily_frame(rows: list[dict]) -> pd.DataFrame:
    """Alpaca 1Day bars as the yfinance-shaped frame the cache writer expects (ET session dates)."""
    if not rows:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    ts = pd.to_datetime([r["t"] for r in rows], utc=True).tz_convert(ET).tz_localize(None).normalize()
    df = pd.DataFrame(
        {
            "Open": [float(r["o"]) for r in rows],
            "High": [float(r["h"]) for r in rows],
            "Low": [float(r["l"]) for r in rows],
            "Close": [float(r["c"]) for r in rows],
            "Volume": [float(r.get("v") or 0) for r in rows],
        },
        index=pd.DatetimeIndex(ts, name="Date"),
    )
    return df[~df.index.duplicated(keep="last")].sort_index()
