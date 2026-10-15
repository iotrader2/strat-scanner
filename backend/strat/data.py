"""Local OHLCV cache (SQLite) filled from Yahoo Finance via yfinance (no API key)."""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Iterator, Optional

import pandas as pd

from . import config
from .universe import OTHER_SECTOR, YAHOO_TO_GICS

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS bars (
    symbol TEXT NOT NULL,
    date   TEXT NOT NULL,
    open   REAL NOT NULL,
    high   REAL NOT NULL,
    low    REAL NOT NULL,
    close  REAL NOT NULL,
    volume REAL NOT NULL,
    PRIMARY KEY (symbol, date)
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS watchlist (
    symbol   TEXT PRIMARY KEY,
    added_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS extra_symbols (
    symbol TEXT PRIMARY KEY,
    name   TEXT NOT NULL,
    sector TEXT NOT NULL,
    kind   TEXT NOT NULL
);
"""

_write_lock = threading.Lock()


@contextmanager
def connect(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    path = Path(db_path or config.CACHE_DB)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def get_meta(key: str, db_path: Path | None = None) -> Optional[str]:
    with connect(db_path) as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def set_meta(key: str, value: str, db_path: Path | None = None) -> None:
    with _write_lock, connect(db_path) as conn:
        conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, value))


def watchlist(db_path: Path | None = None) -> list[str]:
    """Watched symbols, oldest addition first."""
    with connect(db_path) as conn:
        return [r[0] for r in conn.execute("SELECT symbol FROM watchlist ORDER BY added_at, symbol")]


def add_to_watchlist(symbol: str, db_path: Path | None = None) -> None:
    added = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    with _write_lock, connect(db_path) as conn:
        conn.execute("INSERT OR IGNORE INTO watchlist(symbol, added_at) VALUES (?, ?)", (symbol, added))


def remove_from_watchlist(symbol: str, db_path: Path | None = None) -> None:
    with _write_lock, connect(db_path) as conn:
        conn.execute("DELETE FROM watchlist WHERE symbol = ?", (symbol,))


def extra_symbols(db_path: Path | None = None) -> list[dict]:
    """Symbols outside the scan universe that were added from the watchlist, with their metadata."""
    with connect(db_path) as conn:
        rows = conn.execute("SELECT symbol, name, sector, kind FROM extra_symbols ORDER BY symbol").fetchall()
    return [dict(zip(("symbol", "name", "sector", "kind"), r)) for r in rows]


def save_extra_symbol(symbol: str, name: str, sector: str, kind: str, db_path: Path | None = None) -> None:
    with _write_lock, connect(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO extra_symbols(symbol, name, sector, kind) VALUES (?, ?, ?, ?)",
            (symbol, name, sector, kind),
        )


class SymbolNotFound(Exception):
    """Yahoo Finance has no such ticker (or no price history for it)."""


class LookupFailed(Exception):
    """The lookup could not be completed (network error, rate limit, ...); the symbol may still exist."""


def lookup_symbol(symbol: str) -> tuple[pd.DataFrame, dict]:
    """Daily history plus name/sector/kind for any Yahoo Finance ticker."""
    import yfinance as yf
    from yfinance.exceptions import YFTickerMissingError

    ticker = yf.Ticker(symbol)
    try:
        df = ticker.history(
            period=config.HISTORY_PERIOD, interval="1d", auto_adjust=False, actions=False, raise_errors=True
        )
    except YFTickerMissingError as exc:
        raise SymbolNotFound(symbol) from exc
    except Exception as exc:
        raise LookupFailed(f"{symbol}: {exc}") from exc
    if df.empty:
        raise SymbolNotFound(symbol)
    try:
        info = ticker.info or {}
    except Exception:  # metadata is cosmetic; prices are what matter
        info = {}
    is_etf = info.get("quoteType") == "ETF"
    sector = YAHOO_TO_GICS.get(info.get("sector") or "", OTHER_SECTOR)
    meta = {
        "name": info.get("shortName") or info.get("longName") or symbol,
        "sector": sector,
        "kind": "etf" if is_etf else "stock",
    }
    return df, meta


def cached_symbols(db_path: Path | None = None) -> dict[str, str]:
    """symbol -> last cached date."""
    with connect(db_path) as conn:
        return dict(conn.execute("SELECT symbol, MAX(date) FROM bars GROUP BY symbol").fetchall())


def save_bars(symbol: str, df: pd.DataFrame, db_path: Path | None = None) -> int:
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    if df.empty:
        return 0
    rows = [
        (
            symbol,
            idx.strftime("%Y-%m-%d"),
            float(r.Open),
            float(r.High),
            float(r.Low),
            float(r.Close),
            float(0 if pd.isna(r.Volume) else r.Volume),
        )
        for idx, r in df.iterrows()
    ]
    with _write_lock, connect(db_path) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO bars(symbol, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
            rows,
        )
    return len(rows)


def load_daily(symbol: str, db_path: Path | None = None) -> pd.DataFrame:
    with connect(db_path) as conn:
        df = pd.read_sql_query(
            "SELECT date, open, high, low, close, volume FROM bars WHERE symbol = ? ORDER BY date",
            conn,
            params=(symbol,),
        )
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")


def load_all_daily(db_path: Path | None = None) -> dict[str, pd.DataFrame]:
    with connect(db_path) as conn:
        df = pd.read_sql_query(
            "SELECT symbol, date, open, high, low, close, volume FROM bars ORDER BY symbol, date", conn
        )
    if df.empty:
        return {}
    df["date"] = pd.to_datetime(df["date"])
    return {sym: g.drop(columns="symbol").set_index("date") for sym, g in df.groupby("symbol", sort=False)}


def resample(daily: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Aggregate daily bars into weekly (Mon-Fri) or calendar-month candles.

    The last candle is the current, still-forming period, which is what The
    Strat classifies in real time.
    """
    if tf == "D" or daily.empty:
        return daily
    rule = {"W": "W-FRI", "M": "MS"}[tf]
    agg = daily.resample(rule, label="left" if tf == "M" else "right", closed="left" if tf == "M" else "right").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    agg = agg.dropna(subset=["open"])
    if tf == "W":
        # Label weeks by their first trading day so chart times line up with the week open.
        first_day = daily.index.to_series().resample(rule, label="right", closed="right").first()
        agg.index = first_day.reindex(agg.index).values
    return agg


def _download(tickers: list[str], period: str) -> pd.DataFrame:
    import yfinance as yf

    return yf.download(
        tickers,
        period=period,
        interval="1d",
        group_by="ticker",
        auto_adjust=False,
        actions=False,
        progress=False,
        threads=True,
    )


def refresh(
    symbols: Iterable[str],
    full: bool = False,
    progress: Callable[[int, int, str], None] | None = None,
    db_path: Path | None = None,
) -> dict[str, int]:
    """Download daily bars for ``symbols``.

    Symbols already in the cache only fetch a recent window (incremental);
    new symbols, or ``full=True``, fetch the full history period.
    """
    symbols = list(dict.fromkeys(symbols))
    have = cached_symbols(db_path)
    groups: dict[str, list[str]] = {}
    for s in symbols:
        period = config.HISTORY_PERIOD if full or s not in have else config.INCREMENTAL_PERIOD
        groups.setdefault(period, []).append(s)

    saved: dict[str, int] = {}
    done = 0
    total = len(symbols)
    for period, syms in groups.items():
        for i in range(0, len(syms), config.DOWNLOAD_BATCH):
            batch = syms[i : i + config.DOWNLOAD_BATCH]
            if progress:
                progress(done, total, f"Downloading {batch[0]}…{batch[-1]} ({period})")
            df = None
            for attempt in range(3):
                try:
                    df = _download(batch, period)
                    break
                except Exception as exc:  # network hiccups / rate limits
                    log.warning("download failed (%s), retrying: %s", attempt + 1, exc)
                    time.sleep(2 * (attempt + 1))
            if df is not None and not df.empty:
                for sym in batch:
                    try:
                        sub = df[sym] if isinstance(df.columns, pd.MultiIndex) else df
                    except KeyError:
                        continue
                    n = save_bars(sym, sub)
                    if n:
                        saved[sym] = n
            done += len(batch)
    set_meta("last_refresh", datetime.now(timezone.utc).isoformat(timespec="seconds"), db_path)
    if progress:
        progress(total, total, "Done")
    return saved
