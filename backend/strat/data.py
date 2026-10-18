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
CREATE TABLE IF NOT EXISTS positions (
    symbol      TEXT PRIMARY KEY,
    entry_price REAL NOT NULL,
    shares      REAL,
    entry_date  TEXT NOT NULL,
    added_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS earnings (
    symbol     TEXT PRIMARY KEY,
    date       TEXT,
    date_end   TEXT,
    timing     TEXT,
    fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS extra_symbols (
    symbol TEXT PRIMARY KEY,
    name   TEXT NOT NULL,
    sector TEXT NOT NULL,
    kind   TEXT NOT NULL,
    industry TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS corporate_actions (
    symbol  TEXT NOT NULL,
    ex_date TEXT NOT NULL,
    kind    TEXT NOT NULL,
    ratio   REAL NOT NULL,
    PRIMARY KEY (symbol, ex_date, kind)
);
CREATE TABLE IF NOT EXISTS session_bar (
    symbol     TEXT PRIMARY KEY,
    date       TEXT NOT NULL,
    open       REAL NOT NULL,
    high       REAL NOT NULL,
    low        REAL NOT NULL,
    close      REAL NOT NULL,
    volume     REAL NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scan_snapshot (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    version     INTEGER NOT NULL,
    computed_at TEXT NOT NULL,
    payload     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS leader_snapshots (
    date   TEXT NOT NULL,
    rank   INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    score  REAL NOT NULL,
    rs     REAL,
    name   TEXT NOT NULL DEFAULT '',
    as_of  TEXT NOT NULL,
    PRIMARY KEY (date, rank)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_leader_snapshots_symbol ON leader_snapshots(date, symbol);
CREATE TABLE IF NOT EXISTS intraday_bars (
    symbol   TEXT NOT NULL,
    ts       TEXT NOT NULL,
    interval TEXT NOT NULL,
    open     REAL NOT NULL,
    high     REAL NOT NULL,
    low      REAL NOT NULL,
    close    REAL NOT NULL,
    volume   REAL NOT NULL,
    source   TEXT NOT NULL,
    PRIMARY KEY (symbol, ts, interval)
);
CREATE INDEX IF NOT EXISTS idx_intraday_symbol_ts ON intraday_bars(symbol, ts);
CREATE TABLE IF NOT EXISTS intraday_gaps (
    symbol     TEXT NOT NULL,
    date       TEXT NOT NULL,
    interval   TEXT NOT NULL,
    source     TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    PRIMARY KEY (symbol, date, interval)
);
CREATE TABLE IF NOT EXISTS interval_ranks (
    date        TEXT NOT NULL,
    window      TEXT NOT NULL,
    rank        INTEGER NOT NULL,
    symbol      TEXT NOT NULL,
    score       REAL NOT NULL,
    day_move    REAL,
    vs_qqq      REAL,
    or_position REAL,
    PRIMARY KEY (date, window, rank)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_interval_ranks_symbol ON interval_ranks(date, window, symbol);
CREATE TABLE IF NOT EXISTS entry_results (
    date        TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    window      TEXT NOT NULL,
    entry_price REAL NOT NULL,
    candle_low  REAL,
    eod_ret     REAL,
    d1_ret      REAL,
    d2_ret      REAL,
    d3_ret      REAL,
    d4_ret      REAL,
    d5_ret      REAL,
    stopped     INTEGER NOT NULL DEFAULT 0,
    stop_day    INTEGER,
    stop_ret    REAL,
    mfe         REAL,
    mae         REAL,
    role        TEXT NOT NULL DEFAULT 'leader',
    PRIMARY KEY (date, symbol, window)
);
CREATE INDEX IF NOT EXISTS idx_entry_results_window ON entry_results(window, date);
"""


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns introduced after a cache file was created."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(extra_symbols)")}
    if "industry" not in cols:
        conn.execute("ALTER TABLE extra_symbols ADD COLUMN industry TEXT NOT NULL DEFAULT ''")

_write_lock = threading.Lock()


@contextmanager
def connect(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    path = Path(db_path or config.CACHE_DB)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
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


def positions(db_path: Path | None = None) -> list[dict]:
    """Open positions, oldest first: symbol, entry_price, shares (None when not given), entry_date."""
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT symbol, entry_price, shares, entry_date FROM positions ORDER BY added_at, symbol"
        ).fetchall()
    return [dict(zip(("symbol", "entry_price", "shares", "entry_date"), r)) for r in rows]


def save_position(
    symbol: str, entry_price: float, shares: Optional[float], entry_date: str, db_path: Path | None = None
) -> None:
    """Insert or update a position, keeping its original place in the list."""
    added = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    with _write_lock, connect(db_path) as conn:
        conn.execute(
            "INSERT INTO positions(symbol, entry_price, shares, entry_date, added_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(symbol) DO UPDATE SET entry_price = excluded.entry_price, shares = excluded.shares, "
            "entry_date = excluded.entry_date",
            (symbol, entry_price, shares, entry_date, added),
        )


def remove_position(symbol: str, db_path: Path | None = None) -> None:
    with _write_lock, connect(db_path) as conn:
        conn.execute("DELETE FROM positions WHERE symbol = ?", (symbol,))


def tracked_symbols(db_path: Path | None = None) -> set[str]:
    """Symbols on the watchlist or held as positions."""
    return set(watchlist(db_path)) | {p["symbol"] for p in positions(db_path)}


def extra_symbols(db_path: Path | None = None) -> list[dict]:
    """Symbols outside the scan universe that were added from the watchlist, with their metadata."""
    with connect(db_path) as conn:
        rows = conn.execute("SELECT symbol, name, sector, kind, industry FROM extra_symbols ORDER BY symbol").fetchall()
    return [dict(zip(("symbol", "name", "sector", "kind", "industry"), r)) for r in rows]


def save_extra_symbol(
    symbol: str, name: str, sector: str, kind: str, industry: str = "", db_path: Path | None = None
) -> None:
    with _write_lock, connect(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO extra_symbols(symbol, name, sector, kind, industry) VALUES (?, ?, ?, ?, ?)",
            (symbol, name, sector, kind, industry),
        )


def set_extra_industry(symbol: str, industry: str, db_path: Path | None = None) -> None:
    with _write_lock, connect(db_path) as conn:
        conn.execute("UPDATE extra_symbols SET industry = ? WHERE symbol = ?", (industry, symbol))


def fetch_industry(symbol: str) -> str:
    """Yahoo Finance industry for a ticker ("" when unknown); raises on network errors."""
    import yfinance as yf

    return str((yf.Ticker(symbol).info or {}).get("industry") or "")


def load_earnings(db_path: Path | None = None) -> dict[str, dict]:
    """symbol -> {date, date_end, timing, fetched_at}; date is None when the source had no upcoming date."""
    with connect(db_path) as conn:
        rows = conn.execute("SELECT symbol, date, date_end, timing, fetched_at FROM earnings").fetchall()
    return {r[0]: dict(zip(("date", "date_end", "timing", "fetched_at"), r[1:])) for r in rows}


def save_earnings(entries: list[dict], db_path: Path | None = None) -> None:
    fetched = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _write_lock, connect(db_path) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO earnings(symbol, date, date_end, timing, fetched_at) VALUES (?, ?, ?, ?, ?)",
            [(e["symbol"], e.get("date"), e.get("date_end"), e.get("timing"), fetched) for e in entries],
        )


class SymbolNotFound(Exception):
    """Yahoo Finance has no such ticker (or no price history for it)."""


class LookupFailed(Exception):
    """The lookup could not be completed (network error, rate limit, ...); the symbol may still exist."""


def lookup_symbol(symbol: str) -> tuple[pd.DataFrame, dict]:
    """Daily history plus name/sector/kind for any ticker the configured provider knows."""
    from .provider import LookupError, get_provider

    try:
        return get_provider().lookup(symbol, config.HISTORY_PERIOD)
    except LookupError as exc:
        raise SymbolNotFound(symbol) from exc
    except Exception as exc:
        if type(exc).__name__ in ("YFTickerMissingError", "SymbolNotFound"):
            raise SymbolNotFound(symbol) from exc
        raise LookupFailed(f"{symbol}: {exc}") from exc


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


def _as_of_date() -> str:
    if config.AS_OF:
        return config.AS_OF
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("America/New_York")).date().isoformat()


def save_splits(symbol: str, splits: list[tuple[str, float]], db_path: Path | None = None) -> None:
    if not splits:
        return
    with _write_lock, connect(db_path) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO corporate_actions(symbol, ex_date, kind, ratio) VALUES (?, ?, 'split', ?)",
            [(symbol, ex, float(ratio)) for ex, ratio in splits if ratio and float(ratio) != 1.0],
        )


def load_splits(db_path: Path | None = None) -> dict[str, list[tuple[str, float]]]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT symbol, ex_date, ratio FROM corporate_actions WHERE kind = 'split' ORDER BY symbol, ex_date"
        ).fetchall()
    out: dict[str, list[tuple[str, float]]] = {}
    for sym, ex, ratio in rows:
        out.setdefault(sym, []).append((ex, float(ratio)))
    return out


def save_session_bar(symbol: str, df: pd.DataFrame, db_path: Path | None = None) -> None:
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    if df.empty:
        return
    idx, r = next(iter(df.iloc[[-1]].iterrows()))
    ts = pd.Timestamp(idx)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("America/New_York").tz_localize(None)
    updated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _write_lock, connect(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO session_bar(symbol, date, open, high, low, close, volume, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                symbol,
                ts.strftime("%Y-%m-%d"),
                float(r.Open),
                float(r.High),
                float(r.Low),
                float(r.Close),
                float(0 if pd.isna(r.Volume) else r.Volume),
                updated,
            ),
        )


def clear_session_bar(symbol: str, db_path: Path | None = None) -> None:
    with _write_lock, connect(db_path) as conn:
        conn.execute("DELETE FROM session_bar WHERE symbol = ?", (symbol,))


def _session_frames(db_path: Path | None) -> dict[str, pd.DataFrame]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT symbol, date, open, high, low, close, volume FROM session_bar"
        ).fetchall()
    out = {}
    for sym, day, o, h, low, c, v in rows:
        out[sym] = pd.DataFrame(
            [{"open": o, "high": h, "low": low, "close": c, "volume": v}],
            index=pd.DatetimeIndex([pd.Timestamp(day)]),
        )
    return out


def _overlay_session(frames: dict[str, pd.DataFrame], db_path: Path | None) -> dict[str, pd.DataFrame]:
    for sym, bar in _session_frames(db_path).items():
        have = frames.get(sym)
        if have is None or have.empty or bar.index[-1] > have.index[-1]:
            frames[sym] = bar if have is None or have.empty else pd.concat([have, bar])
        elif bar.index[-1] == have.index[-1]:
            frames[sym] = pd.concat([have.iloc[:-1], bar])
    return frames


def _adjust(frames: dict[str, pd.DataFrame], as_of: str, db_path: Path | None) -> dict[str, pd.DataFrame]:
    from .adjust import apply_splits

    splits = load_splits(db_path)
    if not splits:
        return frames
    return {sym: apply_splits(df, splits.get(sym, ()), as_of) for sym, df in frames.items()}


def load_daily(symbol: str, db_path: Path | None = None, *, adjust: bool = True) -> pd.DataFrame:
    frames = load_all_daily(db_path, adjust=adjust)
    return frames.get(symbol, pd.DataFrame())


def load_all_daily(db_path: Path | None = None, *, adjust: bool = True) -> dict[str, pd.DataFrame]:
    as_of = config.AS_OF or "9999-12-31"
    with connect(db_path) as conn:
        df = pd.read_sql_query(
            "SELECT symbol, date, open, high, low, close, volume FROM bars WHERE date <= ? ORDER BY symbol, date",
            conn,
            params=(as_of,),
        )
    frames: dict[str, pd.DataFrame] = {}
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        frames = {sym: g.drop(columns="symbol").set_index("date") for sym, g in df.groupby("symbol", sort=False)}
    if adjust:
        frames = _adjust(frames, _as_of_date() if not config.AS_OF else config.AS_OF, db_path)
        if not config.AS_OF:
            frames = _overlay_session(frames, db_path)
    return frames


def newest_bar_date(db_path: Path | None = None):
    with connect(db_path) as conn:
        row = conn.execute("SELECT MAX(date) FROM bars").fetchone()
    if not row or not row[0]:
        return None
    from datetime import date as date_cls

    return date_cls.fromisoformat(row[0])


def save_snapshot(version: int, computed_at: str, rows: list, db_path: Path | None = None) -> None:
    import json
    from datetime import date as date_cls

    def _json_default(obj):
        if isinstance(obj, (datetime, date_cls)):
            return obj.isoformat()
        item = getattr(obj, "item", None)
        if callable(item):
            try:
                return item()
            except Exception:
                return str(obj)
        return str(obj)

    payload = json.dumps(rows, default=_json_default)
    with _write_lock, connect(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO scan_snapshot(id, version, computed_at, payload) VALUES (1, ?, ?, ?)",
            (version, computed_at, payload),
        )


def load_snapshot(db_path: Path | None = None) -> Optional[dict]:
    import json

    with connect(db_path) as conn:
        row = conn.execute("SELECT version, computed_at, payload FROM scan_snapshot WHERE id = 1").fetchone()
    if not row:
        return None
    return {"version": int(row[0]), "computed_at": row[1], "rows": json.loads(row[2])}


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


def _normalize_index(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    idx = pd.DatetimeIndex(pd.to_datetime(out.index))
    if idx.tz is not None:
        idx = idx.tz_convert("America/New_York").tz_localize(None)
    out.index = idx
    return out


def _split_partial(df: pd.DataFrame, now: datetime | None = None) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    """During the regular session, keep today's unfinished bar out of the confirmed history."""
    from .scheduler import regular_session

    df = _normalize_index(df)
    clock = now or datetime.now(timezone.utc)
    if not regular_session(clock):
        return df, None
    from zoneinfo import ZoneInfo

    today = pd.Timestamp(clock.astimezone(ZoneInfo("America/New_York")).date())
    session = df[df.index.normalize() == today]
    done = df[df.index.normalize() < today]
    if session.empty:
        return done, None
    return done, session.iloc[[-1]]


def refresh(
    symbols: Iterable[str],
    full: bool = False,
    progress: Callable[[int, int, str], None] | None = None,
    db_path: Path | None = None,
    period: str | None = None,
) -> dict[str, int]:
    """Download daily bars for ``symbols`` through the configured provider.

    Symbols already in the cache fetch ``period`` (default: the incremental window).
    New symbols, or ``full=True``, fetch the full history period. Splits are stored
    raw; today's bar stays in ``session_bar`` while the regular session is open.
    """
    from .provider import get_provider

    symbols = list(dict.fromkeys(symbols))
    have = cached_symbols(db_path)
    groups: dict[str, list[str]] = {}
    for s in symbols:
        window = config.HISTORY_PERIOD if full or s not in have else (period or config.INCREMENTAL_PERIOD)
        groups.setdefault(window, []).append(s)

    provider = get_provider()
    saved: dict[str, int] = {}
    done = 0
    total = len(symbols)
    for window, syms in groups.items():
        for i in range(0, len(syms), config.DOWNLOAD_BATCH):
            batch = syms[i : i + config.DOWNLOAD_BATCH]
            if progress:
                progress(done, total, f"Downloading {batch[0]}…{batch[-1]} ({window})")
            fetched = None
            for attempt in range(3):
                try:
                    fetched = provider.fetch_history(batch, window)
                    break
                except Exception as exc:  # network hiccups / rate limits
                    log.warning("download failed (%s), retrying: %s", attempt + 1, exc)
                    time.sleep(2 * (attempt + 1))
            if fetched is not None:
                for sym, sub in fetched.frames.items():
                    save_splits(sym, fetched.splits.get(sym, []), db_path)
                    done_bars, session = _split_partial(sub)
                    n = save_bars(sym, done_bars, db_path)
                    if session is None:
                        clear_session_bar(sym, db_path)
                    else:
                        save_session_bar(sym, session, db_path)
                    if n or session is not None:
                        saved[sym] = n
            done += len(batch)
    set_meta("last_refresh", datetime.now(timezone.utc).isoformat(timespec="seconds"), db_path)
    if progress:
        progress(total, total, "Done")
    return saved
