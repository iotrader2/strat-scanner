"""Durable user data: watchlist, positions, trims, off-universe symbols, alerts and alert settings.

Postgres when ``DATABASE_URL`` is set (Neon free tier on stage), so a deploy no longer wipes these
tables. Without it (local runs, tests) they live in the SQLite cache file, exactly as before.

The market-data cache (bars, earnings, snapshots) stays in SQLite either way: it is rebuilt from the
data provider and would only waste the free Postgres quota.

One Postgres connection is held for the process and reopened when the server drops it (Neon suspends
an idle compute after a few minutes). Queries are written once with ``?`` placeholders; the Postgres
wrapper rewrites them to ``%s``. The URL is never logged.
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional, Sequence

from . import config

log = logging.getLogger(__name__)

# Tables owned by this module (also the order the import script copies them in).
TABLES = ("watchlist", "positions", "position_trims", "extra_symbols", "alerts", "alert_settings")

_COMMON = """
CREATE TABLE IF NOT EXISTS watchlist (
    symbol   TEXT PRIMARY KEY,
    added_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS positions (
    symbol      TEXT PRIMARY KEY,
    entry_price {REAL} NOT NULL,
    shares      {REAL},
    entry_date  TEXT NOT NULL,
    added_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS position_trims (
    id         {SERIAL},
    symbol     TEXT NOT NULL,
    shares     {REAL} NOT NULL,
    price      {REAL} NOT NULL,
    trimmed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS position_trims_symbol ON position_trims(symbol);
CREATE TABLE IF NOT EXISTS extra_symbols (
    symbol   TEXT PRIMARY KEY,
    name     TEXT NOT NULL,
    sector   TEXT NOT NULL,
    kind     TEXT NOT NULL,
    industry TEXT NOT NULL DEFAULT ''
);
-- One row per alert, kept forever. key = symbol|session|setup|first setup bar (stable across polls).
CREATE TABLE IF NOT EXISTS alerts (
    id            {SERIAL},
    key           TEXT NOT NULL UNIQUE,
    symbol        TEXT NOT NULL,
    session       TEXT NOT NULL,
    setup         TEXT NOT NULL,
    setup_bar     TEXT NOT NULL,
    fired_at      TEXT NOT NULL,
    detected_at   TEXT NOT NULL,
    late          INTEGER NOT NULL DEFAULT 0,
    top           INTEGER NOT NULL DEFAULT 0,
    trigger_price {REAL} NOT NULL,
    stop_price    {REAL} NOT NULL,
    setup_low     {REAL} NOT NULL,
    setup_high    {REAL} NOT NULL,
    ref_price     {REAL} NOT NULL,
    status        TEXT NOT NULL,
    filled        INTEGER NOT NULL DEFAULT 0,
    fill_price    {REAL},
    fill_at       TEXT,
    high_reached  {REAL},
    stop_hit      INTEGER NOT NULL DEFAULT 0,
    breakeven_at  TEXT,
    exit_price    {REAL},
    exit_at       TEXT,
    exit_reason   TEXT,
    r_multiple    {REAL},
    details       TEXT NOT NULL DEFAULT '{{}}',
    acknowledged  INTEGER NOT NULL DEFAULT 0,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS alerts_session ON alerts(session);
CREATE INDEX IF NOT EXISTS alerts_symbol ON alerts(symbol);
CREATE TABLE IF NOT EXISTS alert_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

SQLITE_SCHEMA = _COMMON.format(REAL="REAL", SERIAL="INTEGER PRIMARY KEY AUTOINCREMENT")
PG_SCHEMA = _COMMON.format(REAL="DOUBLE PRECISION", SERIAL="BIGSERIAL PRIMARY KEY")

_SCHEMA_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,40}$")


def database_url() -> str:
    return os.environ.get("DATABASE_URL", "").strip()


def pg_schema() -> str:
    """Postgres schema for these tables (``STRAT_PG_SCHEMA``, default public). Dev and tests use their own."""
    name = os.environ.get("STRAT_PG_SCHEMA", "public").strip().lower() or "public"
    if not _SCHEMA_NAME.match(name):
        raise ValueError("STRAT_PG_SCHEMA must be a plain lowercase identifier")
    return name


def backend() -> str:
    return "postgres" if database_url() else "sqlite"


class _PgCursor:
    def __init__(self, cur):
        self._cur = cur

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def __iter__(self):
        return iter(self._cur.fetchall())

    @property
    def rowcount(self) -> int:
        return self._cur.rowcount


class _PgConn:
    """Just enough of the sqlite3.Connection surface for this module's callers."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql: str, params: Sequence[Any] = ()) -> _PgCursor:
        cur = self._conn.cursor()
        cur.execute(sql.replace("?", "%s"), tuple(params))
        return _PgCursor(cur)


_pg_lock = threading.RLock()
_pg_conn = None
_pg_ready: set[str] = set()  # schemas already created in this process


def _pg_open():
    import psycopg

    conn = psycopg.connect(database_url(), connect_timeout=15, application_name="tiltkiller")
    schema = pg_schema()
    with conn.cursor() as cur:
        if schema != "public":
            cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        cur.execute(f'SET search_path TO "{schema}"')
        if schema not in _pg_ready:
            cur.execute(PG_SCHEMA)
    conn.commit()
    _pg_ready.add(schema)
    return conn


def _pg_alive(conn) -> bool:
    if conn is None or conn.closed:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        conn.rollback()
        return True
    except Exception:
        return False


@contextmanager
def _pg_connect() -> Iterator[_PgConn]:
    global _pg_conn
    with _pg_lock:
        if not _pg_alive(_pg_conn):
            if _pg_conn is not None:
                try:
                    _pg_conn.close()
                except Exception:
                    pass
                log.info("userdb: reconnecting to Postgres")
            _pg_conn = _pg_open()
        conn = _pg_conn
        try:
            yield _PgConn(conn)
            conn.commit()
        except BaseException:
            try:
                conn.rollback()
            except Exception:
                pass
            raise


def _sqlite_migrate(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(extra_symbols)")}
    if "industry" not in cols:
        conn.execute("ALTER TABLE extra_symbols ADD COLUMN industry TEXT NOT NULL DEFAULT ''")


@contextmanager
def _sqlite_connect(path: Path) -> Iterator[sqlite3.Connection]:
    path.parent.mkdir(parents=True, exist_ok=True)
    timeout = float(os.environ.get("STRAT_SQLITE_BUSY_TIMEOUT", "60"))
    conn = sqlite3.connect(path, timeout=timeout)
    conn.execute(f"PRAGMA busy_timeout = {int(timeout * 1000)}")
    try:
        conn.executescript(SQLITE_SCHEMA)
        _sqlite_migrate(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


@contextmanager
def connect(db_path: Optional[Path] = None) -> Iterator[Any]:
    """User-data connection. An explicit ``db_path`` always means that SQLite file (tests, tools)."""
    if db_path is None and backend() == "postgres":
        with _pg_connect() as conn:
            yield conn
        return
    with _sqlite_connect(Path(db_path or config.CACHE_DB)) as conn:
        yield conn


def insert_returning_id(conn, sql: str, params: Sequence[Any]) -> int:
    """Run an INSERT and return the new row id on either backend (both support RETURNING)."""
    row = conn.execute(sql + " RETURNING id", params).fetchone()
    return int(row[0])


def describe() -> dict:
    """Backend summary for /api/status (never includes the URL)."""
    if backend() == "postgres":
        return {"backend": "postgres", "schema": pg_schema()}
    return {"backend": "sqlite"}


def close() -> None:
    global _pg_conn
    with _pg_lock:
        if _pg_conn is not None:
            try:
                _pg_conn.close()
            finally:
                _pg_conn = None
