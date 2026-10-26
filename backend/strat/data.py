"""Local OHLCV cache (SQLite) filled by the configured provider (Alpaca by default, Yahoo selectable)."""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Iterator, Optional

import pandas as pd

from . import config, userdb
from .periods import period_complete

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
-- Partial sells. symbol is the position id (positions.symbol). One position can have many trims.
CREATE TABLE IF NOT EXISTS position_trims (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol     TEXT NOT NULL,
    shares     REAL NOT NULL,
    price      REAL NOT NULL,
    trimmed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS position_trims_symbol ON position_trims(symbol);
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
-- Today's 5-minute bars (Alpaca: IEX live, replaced by SIP once 15 minutes old). See intraday.py.
CREATE TABLE IF NOT EXISTS intraday_bars (
    symbol TEXT NOT NULL,
    ts     TEXT NOT NULL,
    open   REAL NOT NULL,
    high   REAL NOT NULL,
    low    REAL NOT NULL,
    close  REAL NOT NULL,
    volume REAL NOT NULL,
    feed   TEXT NOT NULL,
    PRIMARY KEY (symbol, ts)
);
CREATE TABLE IF NOT EXISTS index_quote (
    symbol         TEXT PRIMARY KEY,
    price          REAL NOT NULL,
    previous_close REAL NOT NULL,
    change_pct     REAL NOT NULL,
    session        TEXT NOT NULL,
    day            TEXT NOT NULL,
    as_of          TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scan_snapshot (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    version     INTEGER NOT NULL,
    computed_at TEXT NOT NULL,
    payload     TEXT NOT NULL
);
"""


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns and tables introduced after a cache file was created.

    New tables in SCHEMA are created above via CREATE TABLE IF NOT EXISTS, so an
    existing cache gains position_trims the next time it is opened.
    """
    cols = {r[1] for r in conn.execute("PRAGMA table_info(extra_symbols)")}
    if "industry" not in cols:
        conn.execute("ALTER TABLE extra_symbols ADD COLUMN industry TEXT NOT NULL DEFAULT ''")
    # Restate the trim table for caches opened before it existed. executescript(SCHEMA)
    # already does this; repeating it here keeps the migration next to the other upgrades.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS position_trims (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol     TEXT NOT NULL,
            shares     REAL NOT NULL,
            price      REAL NOT NULL,
            trimmed_at TEXT NOT NULL
        )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS position_trims_symbol ON position_trims(symbol)")

_write_lock = threading.Lock()
WAL = os.environ.get("STRAT_SQLITE_WAL", "").strip().lower() in ("1", "true", "yes")
# Seconds a connection waits on another writer (the fetch child, the API process) before "database is locked".
BUSY_TIMEOUT = float(os.environ.get("STRAT_SQLITE_BUSY_TIMEOUT", "60"))


@contextmanager
def connect(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    path = Path(db_path or config.CACHE_DB)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=BUSY_TIMEOUT)
    conn.execute(f"PRAGMA busy_timeout = {int(BUSY_TIMEOUT * 1000)}")
    if WAL:
        # Readers (the API) and the writer (the fetcher, possibly a child process) stop blocking each other.
        conn.execute("PRAGMA journal_mode=WAL")
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
    with userdb.connect(db_path) as conn:
        return [r[0] for r in conn.execute("SELECT symbol FROM watchlist ORDER BY added_at, symbol").fetchall()]


def add_to_watchlist(symbol: str, db_path: Path | None = None) -> None:
    added = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    with _write_lock, userdb.connect(db_path) as conn:
        conn.execute("INSERT INTO watchlist(symbol, added_at) VALUES (?, ?) ON CONFLICT(symbol) DO NOTHING", (symbol, added))


def remove_from_watchlist(symbol: str, db_path: Path | None = None) -> None:
    with _write_lock, userdb.connect(db_path) as conn:
        conn.execute("DELETE FROM watchlist WHERE symbol = ?", (symbol,))


def positions(db_path: Path | None = None) -> list[dict]:
    """Open positions, oldest first: symbol, entry_price, shares (None when not given), entry_date."""
    with userdb.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT symbol, entry_price, shares, entry_date FROM positions ORDER BY added_at, symbol"
        ).fetchall()
    return [dict(zip(("symbol", "entry_price", "shares", "entry_date"), r)) for r in rows]


def save_position(
    symbol: str, entry_price: float, shares: Optional[float], entry_date: str, db_path: Path | None = None
) -> None:
    """Insert or update a position, keeping its original place in the list."""
    added = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    with _write_lock, userdb.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO positions(symbol, entry_price, shares, entry_date, added_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(symbol) DO UPDATE SET entry_price = excluded.entry_price, shares = excluded.shares, "
            "entry_date = excluded.entry_date",
            (symbol, entry_price, shares, entry_date, added),
        )


class PositionMissing(Exception):
    """No open position for this symbol."""


class TrimRejected(Exception):
    """A trim (or an edit that would contradict one) cannot be saved."""


def _fmt_shares(n: float) -> str:
    return f"{n:g}"


def trims_by_symbol(db_path: Path | None = None) -> dict[str, list[dict]]:
    """symbol -> trims, oldest first. Each trim is id, shares, price, trimmed_at."""
    with userdb.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, symbol, shares, price, trimmed_at FROM position_trims ORDER BY trimmed_at, id"
        ).fetchall()
    grouped: dict[str, list[dict]] = {}
    for trim_id, symbol, shares, price, trimmed_at in rows:
        grouped.setdefault(symbol, []).append(
            {"id": trim_id, "shares": shares, "price": price, "trimmed_at": trimmed_at}
        )
    return grouped


def trimmed_shares(symbol: str, db_path: Path | None = None) -> float:
    with userdb.connect(db_path) as conn:
        row = conn.execute("SELECT COALESCE(SUM(shares), 0) FROM position_trims WHERE symbol = ?", (symbol,)).fetchone()
    return float(row[0])


def add_trim(symbol: str, shares: float, price: float, db_path: Path | None = None) -> dict:
    """Record a partial sell. Shares stay on the position; remaining is initial minus trims.

    Rejects a trim that would sell every share still held — that is a close, not a trim.
    """
    when = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _write_lock, userdb.connect(db_path) as conn:
        row = conn.execute("SELECT shares FROM positions WHERE symbol = ?", (symbol,)).fetchone()
        if row is None:
            raise PositionMissing(symbol)
        initial = row[0]
        if initial is None:
            raise TrimRejected("Add a share count before trimming. Use Edit entry.")
        sold = float(
            conn.execute("SELECT COALESCE(SUM(shares), 0) FROM position_trims WHERE symbol = ?", (symbol,)).fetchone()[0]
        )
        remaining = float(initial) - sold
        if shares >= remaining - 1e-9:
            raise TrimRejected(
                f"Only {_fmt_shares(remaining)} shares remain. Selling all of them closes the position — use Close position."
            )
        trim_id = userdb.insert_returning_id(
            conn,
            "INSERT INTO position_trims(symbol, shares, price, trimmed_at) VALUES (?, ?, ?, ?)",
            (symbol, shares, price, when),
        )
        return {"id": trim_id, "shares": shares, "price": price, "trimmed_at": when}


def delete_trim(symbol: str, trim_id: int, db_path: Path | None = None) -> None:
    """Remove one trim. Raises PositionMissing when that trim is not on this position."""
    with _write_lock, userdb.connect(db_path) as conn:
        held = conn.execute("SELECT 1 FROM positions WHERE symbol = ?", (symbol,)).fetchone()
        if held is None:
            raise PositionMissing(symbol)
        cur = conn.execute("DELETE FROM position_trims WHERE id = ? AND symbol = ?", (trim_id, symbol))
        if cur.rowcount == 0:
            raise PositionMissing(trim_id)


def remove_position(symbol: str, db_path: Path | None = None) -> None:
    with _write_lock, userdb.connect(db_path) as conn:
        conn.execute("DELETE FROM position_trims WHERE symbol = ?", (symbol,))
        conn.execute("DELETE FROM positions WHERE symbol = ?", (symbol,))


def tracked_symbols(db_path: Path | None = None) -> set[str]:
    """Symbols on the watchlist or held as positions."""
    return set(watchlist(db_path)) | {p["symbol"] for p in positions(db_path)}


def extra_symbols(db_path: Path | None = None) -> list[dict]:
    """Symbols outside the scan universe that were added from the watchlist, with their metadata."""
    with userdb.connect(db_path) as conn:
        rows = conn.execute("SELECT symbol, name, sector, kind, industry FROM extra_symbols ORDER BY symbol").fetchall()
    return [dict(zip(("symbol", "name", "sector", "kind", "industry"), r)) for r in rows]


def save_extra_symbol(
    symbol: str, name: str, sector: str, kind: str, industry: str = "", db_path: Path | None = None
) -> None:
    with _write_lock, userdb.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO extra_symbols(symbol, name, sector, kind, industry) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(symbol) DO UPDATE SET name = excluded.name, sector = excluded.sector, "
            "kind = excluded.kind, industry = excluded.industry",
            (symbol, name, sector, kind, industry),
        )


def set_extra_industry(symbol: str, industry: str, db_path: Path | None = None) -> None:
    with _write_lock, userdb.connect(db_path) as conn:
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


def save_spinoffs(symbol: str, factors: list[tuple[str, float]], db_path: Path | None = None) -> None:
    """Spin-off price factors (prior close / ex-date open). Earlier prices are divided by them; volume is not."""
    if not factors:
        return
    with _write_lock, connect(db_path) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO corporate_actions(symbol, ex_date, kind, ratio) VALUES (?, ?, 'spinoff', ?)",
            [(symbol, ex, float(f)) for ex, f in factors if f and float(f) != 1.0],
        )


def load_spinoffs(db_path: Path | None = None) -> dict[str, list[tuple[str, float]]]:
    return load_splits(db_path, kind="spinoff")


def load_splits(db_path: Path | None = None, kind: str = "split") -> dict[str, list[tuple[str, float]]]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT symbol, ex_date, ratio FROM corporate_actions WHERE kind = ? ORDER BY symbol, ex_date", (kind,)
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


def save_session_bars(rows: list[tuple], db_path: Path | None = None) -> None:
    """Bulk (symbol, date, open, high, low, close, volume) into ``session_bar``."""
    if not rows:
        return
    updated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _write_lock, connect(db_path) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO session_bar(symbol, date, open, high, low, close, volume, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(*r, updated) for r in rows],
        )


def clear_session_bar(symbol: str, db_path: Path | None = None) -> None:
    with _write_lock, connect(db_path) as conn:
        conn.execute("DELETE FROM session_bar WHERE symbol = ?", (symbol,))


def load_index_quotes(db_path: Path | None = None) -> list[dict]:
    """Cached premarket / after-hours prints for the index cards."""
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT symbol, price, previous_close, change_pct, session, day, as_of FROM index_quote ORDER BY symbol"
        ).fetchall()
    return [
        {
            "symbol": sym,
            "price": price,
            "previous_close": prev,
            "change_pct": change,
            "session": session,
            "day": day,
            "as_of": as_of,
        }
        for sym, price, prev, change, session, day, as_of in rows
    ]


def _index_quote_key(row: dict) -> tuple:
    return (row["symbol"], row["price"], row["previous_close"], row["change_pct"], row["session"], row["day"])


def save_index_quotes(rows: list[dict], db_path: Path | None = None) -> bool:
    """Replace the cached index quotes. False when the displayed values did not change."""
    rows = sorted(rows, key=lambda r: r["symbol"])
    if [_index_quote_key(r) for r in load_index_quotes(db_path)] == [_index_quote_key(r) for r in rows]:
        return False
    with _write_lock, connect(db_path) as conn:
        conn.execute("DELETE FROM index_quote")
        conn.executemany(
            "INSERT INTO index_quote(symbol, price, previous_close, change_pct, session, day, as_of) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (r["symbol"], r["price"], r["previous_close"], r["change_pct"], r["session"], r["day"], r["as_of"])
                for r in rows
            ],
        )
    return True


def clear_index_quotes(db_path: Path | None = None) -> bool:
    """Drop cached index quotes. False when there was nothing to drop."""
    with _write_lock, connect(db_path) as conn:
        n = conn.execute("SELECT COUNT(*) FROM index_quote").fetchone()[0]
        if not n:
            return False
        conn.execute("DELETE FROM index_quote")
    return True


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
    spins = load_spinoffs(db_path)
    if not splits and not spins:
        return frames
    out = {}
    for sym, df in frames.items():
        df = apply_splits(df, splits.get(sym, ()), as_of)
        out[sym] = apply_splits(df, spins.get(sym, ()), as_of, volume=False)
    return out


# Retry policy for symbols a download batch came back without (see ``refresh``).
RETRY_PASSES = 2
RETRY_BATCH = 10
RETRY_SLEEP = float(os.environ.get("STRAT_RETRY_SLEEP", "2"))
BENCHMARK_ATTEMPTS = 3
REQUIRED_SYMBOLS = ("QQQ", "SPY", "IWM")

# A rescan used to read every symbol into a second dict while the API still held the
# previous one. Batching keeps the extra allocation to one slice of the universe.
RELOAD_BATCH = 40

_BARS_SQL = "SELECT symbol, date, open, high, low, close, volume FROM bars WHERE date <= ?"


def _bars_cutoff() -> str:
    return config.AS_OF or "9999-12-31"


def _frames_from_df(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """One frame per symbol, owning its own block.

    ``groupby`` hands back views of the query result. Keeping those views pins the
    whole query — including the symbol column — for as long as any symbol is held.
    Copying each symbol lets the query buffer be freed.
    """
    if df.empty:
        return {}
    df["date"] = pd.to_datetime(df["date"])
    frames = {}
    for sym, group in df.groupby("symbol", sort=False):
        frames[sym] = group.drop(columns="symbol").set_index("date").copy()
    return frames


def _finalize_frames(
    frames: dict[str, pd.DataFrame], db_path: Path | None, adjust: bool
) -> dict[str, pd.DataFrame]:
    if not adjust:
        return frames
    frames = _adjust(frames, _as_of_date() if not config.AS_OF else config.AS_OF, db_path)
    if not config.AS_OF:
        frames = _overlay_session(frames, db_path)
    return frames


def _load_raw_into(
    frames: dict[str, pd.DataFrame],
    db_path: Path | None,
    symbols: list[str] | None = None,
    *,
    batch: int = RELOAD_BATCH,
    adjust: bool = False,
) -> None:
    """Replace ``frames`` from the cache, ``batch`` symbols at a time.

    The dict is updated in place, so a caller that already holds the previous
    bars drops each symbol as its new frame arrives instead of keeping both copies.
    ``symbols`` limits the read to one name (a single-symbol rescan). With
    ``adjust``, each batch is split-adjusted before it is published, so a reader
    never sees raw bars for a name that has already been refreshed.
    """
    cutoff = _bars_cutoff()
    as_of = _as_of_date() if not config.AS_OF else config.AS_OF
    with connect(db_path) as conn:
        if symbols is None:
            wanted = [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM bars WHERE date <= ?", (cutoff,))]
        else:
            wanted = list(symbols)
    seen: set[str] = set()
    for i in range(0, len(wanted), batch):
        chunk = wanted[i : i + batch]
        placeholders = ",".join("?" * len(chunk))
        sql = f"{_BARS_SQL} AND symbol IN ({placeholders}) ORDER BY symbol, date"
        with connect(db_path) as conn:
            df = pd.read_sql_query(sql, conn, params=(cutoff, *chunk))
        built = _frames_from_df(df)
        del df
        if adjust:
            built = _adjust(built, as_of, db_path)
        for sym, frame in built.items():
            frames[sym] = frame
            seen.add(sym)
        del built
    if symbols is None:
        for sym in [s for s in frames if s not in seen]:
            del frames[sym]


def load_daily(symbol: str, db_path: Path | None = None, *, adjust: bool = True) -> pd.DataFrame:
    """One symbol. Does not load the rest of the universe."""
    frames: dict[str, pd.DataFrame] = {}
    _load_raw_into(frames, db_path, [symbol], batch=1)
    frames = _finalize_frames(frames, db_path, adjust)
    return frames.get(symbol, pd.DataFrame())


def load_all_daily(db_path: Path | None = None, *, adjust: bool = True) -> dict[str, pd.DataFrame]:
    """Every symbol in the cache.

    Read in batches. One query for the whole universe comes back as views onto a
    single block, and that block plus the allocator's leftover pages stayed
    resident for the life of the process (~260 MB here for ~23 MB of prices).
    """
    return reload_daily({}, db_path, adjust=adjust)


def reload_daily(
    frames: dict[str, pd.DataFrame], db_path: Path | None = None, *, adjust: bool = True, batch: int = RELOAD_BATCH
) -> dict[str, pd.DataFrame]:
    """Refresh ``frames`` from the cache without building a second full copy.

    The same dict is returned, so ``State.daily`` keeps serving charts while a
    rescan is in progress. A symbol keeps its previous adjusted bars until its
    batch is read, then switches to the new ones. Today's session bar is applied
    after the last batch.
    """
    _load_raw_into(frames, db_path, batch=batch, adjust=adjust)
    if adjust and not config.AS_OF:
        _overlay_session(frames, db_path)
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


def resample(
    daily: pd.DataFrame,
    tf: str,
    *,
    completed_only: bool = True,
    now: datetime | None = None,
) -> pd.DataFrame:
    """Aggregate daily bars into weekly, monthly, quarterly, or 6-month candles.

    Weeks are ``W-FRI`` bins closed and labeled on the right, then relabeled to
    their first trading day. A Monday therefore opens the *next* Friday's bin;
    it is never folded into the week that already ended. Months, quarters, and
    half-years are left-labeled period starts (``MS``, ``QS``, ``6MS``).

    By default the in-progress bin is dropped. Strat setup, trigger and the
    higher-timeframe chips all read this series (continuity reads the bin in progress), so they stay on the
    last completed week or month: after the close on Friday (or Thursday when
    Friday is a holiday), and not on Monday's high. ``completed_only=False``
    keeps the forming bin for callers that scale a partial week on purpose.
    """
    if tf == "D" or daily.empty:
        return daily
    rule = {"W": "W-FRI", "M": "MS", "3M": "QS", "6M": "6MS"}[tf]
    period_start = tf in {"M", "3M", "6M"}
    agg = daily.resample(rule, label="left" if period_start else "right", closed="left" if period_start else "right").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    agg = agg.dropna(subset=["open"])
    if completed_only and not agg.empty:
        last = pd.Timestamp(daily.index[-1])
        if last.tzinfo is not None:
            last = last.tz_convert("America/New_York").tz_localize(None)
        if not period_complete(tf, last.date(), now):
            agg = agg.iloc[:-1].copy()
    if tf == "W" and not agg.empty:
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
    from .provider import get_provider, release_download_cache

    symbols = list(dict.fromkeys(symbols))
    have = cached_symbols(db_path)
    groups: dict[str, list[str]] = {}
    for s in symbols:
        window = config.HISTORY_PERIOD if full or s not in have else (period or config.INCREMENTAL_PERIOD)
        groups.setdefault(window, []).append(s)

    provider = get_provider()
    saved: dict[str, int] = {}
    got: set[str] = set()
    done = 0
    total = len(symbols)

    def fetch_batch(batch: list[str], window: str) -> None:
        fetched = None
        for attempt in range(3):
            try:
                fetched = provider.fetch_history(batch, window)
                break
            except Exception as exc:  # network hiccups / rate limits
                log.warning("download failed (%s), retrying: %s", attempt + 1, exc)
                time.sleep(RETRY_SLEEP * (attempt + 1))
        if fetched is None:
            return
        for sym, sub in fetched.frames.items():
            if sub is None or sub.dropna(subset=[c for c in ("Open", "High", "Low", "Close") if c in sub.columns]).empty:
                continue  # an all-NaN frame is a failed download (yfinance reports it but still returns columns)
            save_splits(sym, fetched.splits.get(sym, []), db_path)
            save_spinoffs(sym, getattr(fetched, "spinoffs", {}).get(sym, []), db_path)
            done_bars, session = _split_partial(sub)
            n = save_bars(sym, done_bars, db_path)
            if session is None:
                clear_session_bar(sym, db_path)
            else:
                save_session_bar(sym, session, db_path)
            got.add(sym)
            if n or session is not None:
                saved[sym] = n

    for window, syms in groups.items():
        for i in range(0, len(syms), config.DOWNLOAD_BATCH):
            batch = syms[i : i + config.DOWNLOAD_BATCH]
            if progress:
                progress(done, total, f"Downloading {batch[0]}…{batch[-1]} ({window})")
            fetch_batch(batch, window)
            done += len(batch)

    # Symbols a batch came back without (a lock or rate-limit miss, a transient error) are retried in small
    # batches instead of being dropped. Benchmarks get extra single-symbol attempts: without QQQ every
    # Vs QQQ score would silently be zero.
    window_of = {s: w for w, syms in groups.items() for s in syms}
    missing = [s for s in symbols if s not in got]
    for attempt in range(RETRY_PASSES):
        if not missing:
            break
        log.warning("refresh: retrying %d symbols with no bars (pass %d): %s", len(missing), attempt + 1, missing[:20])
        time.sleep(RETRY_SLEEP * (attempt + 1))
        for i in range(0, len(missing), RETRY_BATCH):
            chunk = missing[i : i + RETRY_BATCH]
            by_window: dict[str, list[str]] = {}
            for s in chunk:
                by_window.setdefault(window_of[s], []).append(s)
            for window, syms in by_window.items():
                fetch_batch(syms, window)
        missing = [s for s in missing if s not in got]
    required = [s for s in missing if s in REQUIRED_SYMBOLS]
    for attempt in range(BENCHMARK_ATTEMPTS):
        if not required:
            break
        time.sleep(RETRY_SLEEP * (attempt + 1))
        for s in required:
            fetch_batch([s], window_of[s])
        required = [s for s in required if s not in got]
    missing = [s for s in missing if s not in got]
    if missing:
        log.warning("refresh: %d symbols returned no bars after retries: %s", len(missing), missing)
    cached = cached_symbols(db_path)
    lost = [s for s in REQUIRED_SYMBOLS if s in symbols and s not in cached]
    if lost:
        # Previous bars (if any) are kept; with none at all, fail loudly instead of scoring Vs QQQ as zero.
        raise RuntimeError(f"benchmark download failed: {', '.join(lost)} has no bars")
    set_meta("last_refresh", datetime.now(timezone.utc).isoformat(timespec="seconds"), db_path)
    release_download_cache()
    if progress:
        progress(total, total, "Done")
    return saved
