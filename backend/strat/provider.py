"""Upstream market-data providers.

One process holds the only connection. ``alpaca`` (Alpaca Market Data, free plan) is the default
when its keys are set; ``yahoo`` stays selectable with ``STRAT_DATA_PROVIDER=yahoo`` so a rollback
is a config change. Name/sector/industry lookups, earnings dates and the premarket / after-hours
index prints stay on Yahoo with either provider (Alpaca has no equivalent on the free plan).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Protocol

import pandas as pd

log = logging.getLogger(__name__)


class LookupError(Exception):
    """The provider has no price history for this ticker."""


@dataclass
class FetchResult:
    frames: dict[str, pd.DataFrame] = field(default_factory=dict)
    splits: dict[str, list[tuple[str, float]]] = field(default_factory=dict)
    # Spin-off price factors (ex-date, prior close / ex-date open): earlier prices only, volume unchanged.
    spinoffs: dict[str, list[tuple[str, float]]] = field(default_factory=dict)


class MarketDataProvider(Protocol):
    name: str

    def fetch_history(self, symbols: list[str], period: str) -> FetchResult:
        """Unadjusted daily bars, plus any splits found in the same response."""

    def lookup(self, symbol: str, period: str) -> tuple[pd.DataFrame, dict]:
        """Daily history and name/sector/kind for one ticker. Raises provider-specific errors."""


def splits_in(df: pd.DataFrame) -> list[tuple[str, float]]:
    """(ex-date, ratio) rows from a yfinance frame. Ratio 4.0 is a 4-for-1 split."""
    if df is None or df.empty:
        return []
    col = next((c for c in df.columns if str(c).lower().replace("_", " ") == "stock splits"), None)
    if col is None:
        return []
    out: list[tuple[str, float]] = []
    for idx, val in df[col].items():
        if pd.isna(val):
            continue
        ratio = float(val)
        if not ratio or ratio == 1.0:
            continue
        ts = pd.Timestamp(idx)
        if ts.tzinfo is not None:
            ts = ts.tz_convert("America/New_York").tz_localize(None)
        out.append((ts.strftime("%Y-%m-%d"), ratio))
    return out


class YahooProvider:
    """Yahoo Finance via yfinance. Unofficial, personal-use, and the only Phase 1 source."""

    name = "yahoo"

    def fetch_history(self, symbols: list[str], period: str) -> FetchResult:
        """Daily bars for ``symbols``.

        A 5-day poll is one serial request. Threaded downloads share yfinance's
        SQLite cache and log ``database is locked`` for the symbols that lose;
        those symbols come back empty instead of raising, so a partial result is
        retried once, serially.
        """
        threads = period != "5d"
        result = self._download(symbols, period, threads=threads)
        missing = [sym for sym in symbols if sym not in result.frames]
        if missing and result.frames:
            retried = self._download(missing, period, threads=False)
            result.frames.update(retried.frames)
            result.splits.update(retried.splits)
        return result

    def _download(self, symbols: list[str], period: str, *, threads: bool) -> FetchResult:
        import yfinance as yf

        df = yf.download(
            list(symbols),
            period=period,
            interval="1d",
            group_by="ticker",
            auto_adjust=False,
            actions=True,
            progress=False,
            threads=threads,
        )
        result = FetchResult()
        if df is None or df.empty:
            return result
        many = isinstance(df.columns, pd.MultiIndex)
        for sym in symbols:
            try:
                sub = df[sym] if many else df
            except KeyError:
                continue
            if sub is None or sub.empty:
                continue
            result.frames[sym] = sub
            found = splits_in(sub)
            if found:
                result.splits[sym] = found
        return result

    def lookup(self, symbol: str, period: str) -> tuple[pd.DataFrame, dict]:
        import yfinance as yf

        from .universe import OTHER_SECTOR, YAHOO_TO_GICS

        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval="1d", auto_adjust=False, actions=True, raise_errors=True)
        if df is None or df.empty:
            raise LookupError(symbol)
        try:
            info = ticker.info or {}
        except Exception:
            info = {}
        is_etf = info.get("quoteType") == "ETF"
        meta = {
            "name": info.get("shortName") or info.get("longName") or symbol,
            "sector": YAHOO_TO_GICS.get(info.get("sector") or "", OTHER_SECTOR),
            "kind": "etf" if is_etf else "stock",
            "industry": "" if is_etf else str(info.get("industry") or ""),
        }
        return df, meta

    def fetch_prepost(self, symbols: list[str]) -> pd.DataFrame:
        """One day of 1-minute bars including premarket and after hours.

        Daily bars stop at the last regular session, and ``fast_info`` repeats that
        session during premarket. The latest pre/post minute is the live print.
        ``threads=False`` keeps the fetch to one request for the handful of index symbols.
        """
        import yfinance as yf

        if not symbols:
            return pd.DataFrame()
        df = yf.download(
            list(symbols),
            period="1d",
            interval="1m",
            group_by="ticker",
            auto_adjust=False,
            prepost=True,
            progress=False,
            threads=False,
        )
        return df if df is not None else pd.DataFrame()


def release_download_cache() -> None:
    """Drop yfinance's cached HTTP responses. A price poll never reads them again."""
    try:
        from yfinance.data import YfData

        YfData.cache_get.cache_clear()
    except Exception:
        return


class AlpacaProvider:
    """Alpaca Market Data: daily SIP bars, real-time IEX 5-minute bars for the session in progress.

    Daily bars are requested unadjusted (``ALPACA_ADJUSTMENT=raw``) and the splits come from
    Alpaca's corporate-actions endpoint, so the cache keeps raw bars plus a split table exactly
    like the Yahoo path and ``adjust.apply_splits`` stays point-in-time.
    """

    name = "alpaca"
    # The session in progress comes from 5-minute bars (see intraday.py), polled on 5-minute marks.
    live_bars = True

    def __init__(self, client=None):
        from .alpaca import AlpacaClient

        self.client = client or AlpacaClient()
        self.failed: list[str] = []

    def fetch_history(self, symbols: list[str], period: str) -> FetchResult:
        from .alpaca import ADJUSTMENT, daily_frame, period_start

        start = period_start(period)
        bars, invalid = self.client.bars(symbols, "1Day", start)
        self.failed.extend(invalid)
        result = FetchResult()
        for sym in symbols:
            rows = bars.get(sym)
            if rows:
                result.frames[sym] = daily_frame(rows)
        if ADJUSTMENT in ("raw", "dividend") and result.frames:
            self._corporate_actions(result, start)
        return result

    def _corporate_actions(self, result: FetchResult, start) -> None:
        """Splits and spin-off factors for ``result.frames``, checked against the raw bars."""
        from datetime import datetime

        from .alpaca import ET, validate_actions

        try:
            actions = self.client.corporate_actions(list(result.frames), start, datetime.now(ET).date())
        except Exception:
            log.warning("alpaca corporate actions lookup failed; bars saved without new splits", exc_info=True)
            return
        for sym, found in actions.items():
            if sym not in result.frames:
                continue
            splits, spins = validate_actions(result.frames[sym], found)
            if splits:
                result.splits[sym] = splits
            if spins:
                result.spinoffs[sym] = spins

    def lookup(self, symbol: str, period: str) -> tuple[pd.DataFrame, dict]:
        """Bars from Alpaca; name, sector, kind and industry from Yahoo (Alpaca has no sector data)."""
        from .alpaca import ADJUSTMENT, daily_frame, period_start

        start = period_start(period)
        bars, invalid = self.client.bars([symbol], "1Day", start)
        rows = bars.get(symbol)
        if invalid or not rows:
            raise LookupError(symbol)
        df = daily_frame(rows)
        if ADJUSTMENT in ("raw", "dividend"):
            found = FetchResult(frames={symbol: df})
            self._corporate_actions(found, start)
            # Same shape as a yfinance frame so api._fetch_off_universe -> splits_in() stores them.
            df["Stock Splits"] = 0.0
            for ex, ratio in found.splits.get(symbol, []):
                ts = pd.Timestamp(ex)
                if ts in df.index:
                    df.loc[ts, "Stock Splits"] = ratio
            df.attrs["spinoffs"] = found.spinoffs.get(symbol, [])
        return df, yahoo_meta(symbol)

    def fetch_prepost(self, symbols: list[str]) -> pd.DataFrame:
        """Premarket / after-hours index prints stay on Yahoo (IEX barely trades outside 9:30-16:00)."""
        return YahooProvider().fetch_prepost(symbols)


def yahoo_meta(symbol: str) -> dict:
    """Name, sector, kind, industry from Yahoo. Falls back to bare defaults when Yahoo fails."""
    from .universe import OTHER_SECTOR, YAHOO_TO_GICS

    try:
        import yfinance as yf

        info = yf.Ticker(symbol).info or {}
    except Exception:
        info = {}
    is_etf = info.get("quoteType") == "ETF"
    return {
        "name": info.get("shortName") or info.get("longName") or symbol,
        "sector": YAHOO_TO_GICS.get(info.get("sector") or "", OTHER_SECTOR),
        "kind": "etf" if is_etf else "stock",
        "industry": "" if is_etf else str(info.get("industry") or ""),
    }


def active_name() -> str:
    """``STRAT_DATA_PROVIDER`` when set; otherwise ``alpaca`` when its keys are present, else ``yahoo``."""
    name = os.environ.get("STRAT_DATA_PROVIDER", "").strip().lower()
    if name:
        return name
    from .alpaca import has_credentials

    return "alpaca" if has_credentials() else "yahoo"


def live_bars_enabled() -> bool:
    """True when today's session is built from 5-minute bars polled on the 5-minute marks (Alpaca)."""
    try:
        return active_name() == "alpaca"
    except Exception:
        return False


def get_provider() -> MarketDataProvider:
    name = active_name()
    if name == "yahoo":
        return YahooProvider()
    if name == "alpaca":
        return AlpacaProvider()
    raise ValueError(f"Unknown STRAT_DATA_PROVIDER {name!r}")
