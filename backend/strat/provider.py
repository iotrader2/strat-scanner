"""Upstream market-data providers.

One process holds the only connection. ``yahoo`` is the Phase 1 implementation. A later
provider (Massive) can satisfy the same protocol without changing the scheduler or the scan.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Protocol

import pandas as pd


class LookupError(Exception):
    """The provider has no price history for this ticker."""


@dataclass
class FetchResult:
    frames: dict[str, pd.DataFrame] = field(default_factory=dict)
    splits: dict[str, list[tuple[str, float]]] = field(default_factory=dict)


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


def get_provider() -> MarketDataProvider:
    name = os.environ.get("STRAT_DATA_PROVIDER", "yahoo").strip().lower()
    if name == "yahoo":
        return YahooProvider()
    raise ValueError(f"Unknown STRAT_DATA_PROVIDER {name!r}")
