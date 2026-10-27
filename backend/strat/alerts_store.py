"""Alerts and alert settings in the user database (Postgres on stage, SQLite locally).

Live rows stay on ``alerts`` through the session. After the close they move, in one transaction,
to ``alerts_history`` with the same id. Nothing is dropped.
"""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from . import userdb
from .alerts import SETTING_LIMITS, Alert, Settings, mark_top

_lock = threading.Lock()


@contextmanager
def _writing():
    try:
        yield
    finally:
        userdb.bump()

COLUMNS = (
    "id", "key", "symbol", "session", "setup", "setup_bar", "fired_at", "detected_at", "late", "top",
    "trigger_price", "stop_price", "setup_low", "setup_high", "ref_price", "status", "filled", "fill_price",
    "fill_at", "high_reached", "stop_hit", "breakeven_at", "exit_price", "exit_at", "exit_reason", "r_multiple",
    "details", "acknowledged", "updated_at",
)
# Outcome columns a later poll may change. Fire time, detection time, late, top and acknowledged never change.
OUTCOME = (
    "setup_bar", "trigger_price", "stop_price", "setup_low", "setup_high", "ref_price", "status", "filled",
    "fill_price", "fill_at", "high_reached", "stop_hit", "breakeven_at", "exit_price", "exit_at", "exit_reason",
    "r_multiple", "details",
)
# A backfilled alert (found after a restart or a missed poll) is marked late and does not chime.
LATE_AFTER_SECONDS = 8 * 60
# Written once, when the row leaves the live table.
HISTORY_EXTRA = ("trading_date", "archived_at")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row(r) -> dict:
    d = dict(zip(COLUMNS, r))
    for k in ("late", "top", "filled", "stop_hit", "acknowledged"):
        d[k] = bool(d[k])
    try:
        d["details"] = json.loads(d["details"] or "{}")
    except ValueError:
        d["details"] = {}
    return d


def _select(where: str = "", params: tuple = (), order: str = "fired_at DESC, id DESC", limit: Optional[int] = None):
    sql = f"SELECT {', '.join(COLUMNS)} FROM alerts"
    if where:
        sql += f" WHERE {where}"
    sql += f" ORDER BY {order}"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return sql, params


def list_alerts(
    session: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    symbol: Optional[str] = None,
    limit: Optional[int] = 500,
    db_path: Optional[Path] = None,
) -> list[dict]:
    clauses, params = [], []
    if session:
        clauses.append("session = ?")
        params.append(session)
    if start:
        clauses.append("session >= ?")
        params.append(start)
    if end:
        clauses.append("session <= ?")
        params.append(end)
    if symbol:
        clauses.append("symbol = ?")
        params.append(symbol.upper())
    sql, p = _select(" AND ".join(clauses), tuple(params), limit=limit)

    def read() -> list:
        with userdb.connect(db_path) as conn:
            return conn.execute(sql, p).fetchall()

    return [_row(r) for r in userdb.cached(("alerts", sql, p), read, db_path)]


def sessions(db_path: Optional[Path] = None) -> list[str]:
    def read() -> list[str]:
        with userdb.connect(db_path) as conn:
            return [r[0] for r in conn.execute("SELECT DISTINCT session FROM alerts ORDER BY session DESC").fetchall()]

    return list(userdb.cached("alert_sessions", read, db_path))


def unread_count(db_path: Optional[Path] = None) -> int:
    def read() -> int:
        with userdb.connect(db_path) as conn:
            return int(conn.execute("SELECT COUNT(*) FROM alerts WHERE acknowledged = 0").fetchone()[0])

    return userdb.cached("alert_unread", read, db_path)


def acknowledge(ids: Optional[Iterable[int]] = None, db_path: Optional[Path] = None) -> int:
    """Mark alerts read. ``ids=None`` acknowledges every unread alert."""
    with _lock, _writing(), userdb.connect(db_path) as conn:
        if ids is None:
            return conn.execute("UPDATE alerts SET acknowledged = 1 WHERE acknowledged = 0").rowcount
        n = 0
        for i in ids:
            n += conn.execute("UPDATE alerts SET acknowledged = 1 WHERE id = ?", (int(i),)).rowcount
        return n


def save_session(
    session: str,
    alerts: Iterable[Alert],
    now: Optional[datetime] = None,
    top_names: int = 3,
    db_path: Optional[Path] = None,
) -> dict:
    """Insert new alerts and update the outcome of known ones (by key) for one session, then mark "top".

    Alerts stored earlier but missing from this run are left as they were.
    """
    clock = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stamp = clock.strftime("%Y-%m-%dT%H:%M:%SZ")
    inserted, updated = [], 0
    with _lock, _writing(), userdb.connect(db_path) as conn:
        known = {
            r[0]: r[1:]
            for r in conn.execute(
                f"SELECT key, {', '.join(OUTCOME)} FROM alerts WHERE session = ?", (session,)
            ).fetchall()
        }
        for a in alerts:
            rec = a.record()
            if rec["key"] in known:
                if tuple(known[rec["key"]]) != tuple(rec[c] for c in OUTCOME):
                    conn.execute(
                        f"UPDATE alerts SET {', '.join(c + ' = ?' for c in OUTCOME)}, updated_at = ? WHERE key = ?",
                        tuple(rec[c] for c in OUTCOME) + (stamp, rec["key"]),
                    )
                    updated += 1
                continue
            late = (clock - a.fired_at).total_seconds() > LATE_AFTER_SECONDS
            cols = list(rec) + ["detected_at", "late", "top", "acknowledged", "updated_at"]
            vals = list(rec.values()) + [stamp, int(late), 0, 0, stamp]
            new_id = userdb.insert_returning_id(
                conn, f"INSERT INTO alerts({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", vals
            )
            inserted.append({"id": new_id, "symbol": a.symbol, "setup": a.setup, "late": late})
        rows = [
            {"symbol": r[0], "fired_at": r[1], "top": r[2]}
            for r in conn.execute("SELECT symbol, fired_at, top FROM alerts WHERE session = ?", (session,)).fetchall()
        ]
        already = {r["symbol"] for r in rows if r["top"]}
        if len(already) < top_names:
            names = mark_top(rows, top_names) | already
            for sym in sorted(names - already):
                conn.execute("UPDATE alerts SET top = 1 WHERE session = ? AND symbol = ?", (session, sym))
        elif already:
            # New alerts for names that are already top get the tag too.
            for sym in sorted(already):
                conn.execute("UPDATE alerts SET top = 1 WHERE session = ? AND symbol = ? AND top = 0", (session, sym))
    return {"inserted": inserted, "updated": updated}


def load_settings(db_path: Optional[Path] = None) -> Settings:
    def read() -> list:
        with userdb.connect(db_path) as conn:
            return conn.execute("SELECT key, value FROM alert_settings").fetchall()

    return Settings.from_mapping({k: json.loads(v) for k, v in userdb.cached("alert_settings", read, db_path)})


class SettingsError(ValueError):
    pass


def save_settings(changes: dict, db_path: Optional[Path] = None) -> Settings:
    """Validate and store changed values. Unknown keys and out-of-range values raise SettingsError."""
    current = load_settings(db_path).to_dict()
    clean = {}
    for k, v in changes.items():
        if k not in SETTING_LIMITS:
            raise SettingsError(f"Unknown setting: {k}")
        try:
            num = float(v)
        except (TypeError, ValueError):
            raise SettingsError(f"{k} must be a number") from None
        lo, hi = SETTING_LIMITS[k]
        if not lo <= num <= hi:
            raise SettingsError(f"{k} must be between {lo:g} and {hi:g}")
        clean[k] = int(num) if isinstance(current[k], int) else num
    merged = {**current, **clean}
    for a, b in (("b_from", "b_to"), ("c_from", "c_to"), ("d_from", "d_to"), ("e_from", "e_to"), ("f_from", "f_to")):
        if merged[a] > merged[b]:
            raise SettingsError(f"{a} must not be after {b}")
    with _lock, _writing(), userdb.connect(db_path) as conn:
        for k, v in clean.items():
            conn.execute(
                "INSERT INTO alert_settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (k, json.dumps(v)),
            )
    return Settings.from_mapping(merged)


def reset_settings(db_path: Optional[Path] = None) -> Settings:
    with _lock, _writing(), userdb.connect(db_path) as conn:
        conn.execute("DELETE FROM alert_settings")
    return Settings()


def _history_row(r) -> dict:
    d = _row(r[: len(COLUMNS)])
    d.update(zip(HISTORY_EXTRA, r[len(COLUMNS) :]))
    return d


def list_history(
    trading_date: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    symbol: Optional[str] = None,
    limit: Optional[int] = 500,
    db_path: Optional[Path] = None,
) -> list[dict]:
    """Archived alerts, newest fire first. ``trading_date`` is one session; start/end bound a range."""
    clauses, params = [], []
    if trading_date:
        clauses.append("trading_date = ?")
        params.append(trading_date)
    if start:
        clauses.append("trading_date >= ?")
        params.append(start)
    if end:
        clauses.append("trading_date <= ?")
        params.append(end)
    if symbol:
        clauses.append("symbol = ?")
        params.append(symbol.upper())
    cols = ", ".join((*COLUMNS, *HISTORY_EXTRA))
    sql = f"SELECT {cols} FROM alerts_history"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY fired_at DESC, id DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    bound = tuple(params)

    def read() -> list:
        with userdb.connect(db_path) as conn:
            return conn.execute(sql, bound).fetchall()

    return [_history_row(r) for r in userdb.cached(("alert_history", sql, bound), read, db_path)]


def history_dates(db_path: Optional[Path] = None) -> list[str]:
    """Trading dates that have archived alerts, newest first."""

    def read() -> list[str]:
        with userdb.connect(db_path) as conn:
            return [r[0] for r in conn.execute(
                "SELECT DISTINCT trading_date FROM alerts_history ORDER BY trading_date DESC"
            ).fetchall()]

    return list(userdb.cached("alert_history_dates", read, db_path))


def list_for_metrics(
    start: Optional[str] = None,
    end: Optional[str] = None,
    symbol: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> list[dict]:
    """Live and archived alerts for the metrics view. A row is in only one table."""
    return list_alerts(start=start, end=end, symbol=symbol, limit=None, db_path=db_path) + list_history(
        start=start, end=end, symbol=symbol, limit=None, db_path=db_path
    )


def metric_symbols(db_path: Optional[Path] = None) -> list[str]:
    def read() -> list[str]:
        with userdb.connect(db_path) as conn:
            live = [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM alerts").fetchall()]
            archived = [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM alerts_history").fetchall()]
        return sorted(set(live) | set(archived))

    return list(userdb.cached("alert_metric_symbols", read, db_path))


def archive_alerts(through: date, now: Optional[datetime] = None, db_path: Optional[Path] = None) -> dict:
    """Move live alerts with ``session <= through`` into history. One transaction, idempotent.

    The history row keeps the live id. A second call moves nothing. If this process dies before
    the transaction commits, both tables are unchanged and the next call tries again.
    """
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    stamp = clock.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    day = through.isoformat()
    live_cols = ", ".join(COLUMNS)
    hist_cols = ", ".join((*COLUMNS, *HISTORY_EXTRA))
    insert_sql = (
        f"INSERT INTO alerts_history ({hist_cols}) "
        f"SELECT {live_cols}, session, ? FROM alerts WHERE session <= ? "
        "ON CONFLICT (id) DO NOTHING"
    )
    delete_sql = "DELETE FROM alerts WHERE session <= ? AND id IN (SELECT id FROM alerts_history)"
    with _lock, _writing(), userdb.connect(db_path) as conn:
        before = int(conn.execute("SELECT COUNT(*) FROM alerts WHERE session <= ?", (day,)).fetchone()[0])
        conn.execute(insert_sql, (stamp, day))
        conn.execute(delete_sql, (day,))
        after = int(conn.execute("SELECT COUNT(*) FROM alerts WHERE session <= ?", (day,)).fetchone()[0])
    return {"moved": before - after, "through": day, "skipped": False}


def archive_if_due(now: Optional[datetime] = None, db_path: Optional[Path] = None) -> dict:
    """Archive every session the clock says is already closed, unless the setting is off."""
    from .scheduler import archive_through, now_et

    clock = now_et(now)
    if not load_settings(db_path).auto_archive:
        return {"moved": 0, "skipped": True, "through": None}
    result = archive_alerts(archive_through(clock), now=clock, db_path=db_path)
    result["skipped"] = False
    return result
