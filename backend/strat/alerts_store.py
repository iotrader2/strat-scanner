"""Alerts and alert settings in the user database (Postgres on stage, SQLite locally).

Live rows stay on ``alerts`` through the session. After the close they move, in one transaction,
to ``alerts_history`` with the same id. A live row whose key is already in history is a
re-creation (new id, same alert): it is not copied again, and it is removed from the live table.
"""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from . import userdb
from .alerts import MA_PERIODS, SETTING_LIMITS, Alert, Settings, mark_top

_lock = threading.Lock()

# One-shot: rewrite a stored max_stop_pct of exactly 2 to the new default of 1.
_MAX_STOP_PCT_1_META = "max_stop_pct_1"


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

    An alert that moves from watching (``pending``) to ``triggered`` is marked unread again and
    returned in ``triggered``, so the page chimes a second time for the entry.

    A key already in ``alerts_history`` has already fired. It is not inserted again — the local
    order app uses the alert id as ``clientOrderId``, so a new id would be a second order — and a
    live duplicate of that key is removed. Alerts stored earlier but missing from this run are
    left as they were.
    """
    clock = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stamp = clock.strftime("%Y-%m-%dT%H:%M:%SZ")
    inserted, triggered, updated, removed = [], [], 0, 0
    with _lock, _writing(), userdb.connect(db_path) as conn:
        archived = {
            r[0]
            for r in conn.execute("SELECT key FROM alerts_history WHERE session = ?", (session,)).fetchall()
        }
        if archived:
            removed = int(
                conn.execute(
                    "SELECT COUNT(*) FROM alerts WHERE session = ? AND key IN "
                    "(SELECT key FROM alerts_history WHERE session = ?)",
                    (session, session),
                ).fetchone()[0]
            )
            if removed:
                conn.execute(
                    "DELETE FROM alerts WHERE session = ? AND key IN "
                    "(SELECT key FROM alerts_history WHERE session = ?)",
                    (session, session),
                )
        known = {
            r[0]: r[1:]
            for r in conn.execute(
                f"SELECT key, {', '.join(OUTCOME)}, id FROM alerts WHERE session = ?", (session,)
            ).fetchall()
        }
        status_at = OUTCOME.index("status")
        for a in alerts:
            rec = a.record()
            if rec["key"] in archived:
                continue
            if rec["key"] in known:
                old = known[rec["key"]]
                if tuple(old[: len(OUTCOME)]) != tuple(rec[c] for c in OUTCOME):
                    conn.execute(
                        f"UPDATE alerts SET {', '.join(c + ' = ?' for c in OUTCOME)}, updated_at = ? WHERE key = ?",
                        tuple(rec[c] for c in OUTCOME) + (stamp, rec["key"]),
                    )
                    updated += 1
                    if old[status_at] == "pending" and rec["filled"]:
                        conn.execute("UPDATE alerts SET acknowledged = 0 WHERE key = ?", (rec["key"],))
                        triggered.append({"id": old[-1], "symbol": a.symbol, "setup": a.setup})
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
    return {"inserted": inserted, "triggered": triggered, "updated": updated, "removed": removed}


def _migrate_max_stop_pct_to_1(conn) -> bool:
    """If ``user_meta`` has not recorded it yet, rewrite a stored ``max_stop_pct`` of exactly 2 to 1.

    Same idea as a ``min_avg_dollar_volume_100m``-style one-shot: flag in ``user_meta`` so it runs once.
    Custom values other than exactly 2 are left alone. Returns True when a rewrite happened.
    """
    if conn.execute("SELECT 1 FROM user_meta WHERE key = ?", (_MAX_STOP_PCT_1_META,)).fetchone():
        return False
    changed = False
    row = conn.execute("SELECT value FROM alert_settings WHERE key = 'max_stop_pct'").fetchone()
    if row is not None:
        try:
            current = float(json.loads(row[0]))
        except (TypeError, ValueError):
            current = None
        if current == 2.0:
            conn.execute(
                "UPDATE alert_settings SET value = ? WHERE key = 'max_stop_pct'",
                (json.dumps(1.0),),
            )
            changed = True
    conn.execute(
        "INSERT INTO user_meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (_MAX_STOP_PCT_1_META, "1"),
    )
    return changed


def load_settings(db_path: Optional[Path] = None) -> Settings:
    def read() -> list:
        with userdb.connect(db_path) as conn:
            # Run the one-shot rewrite inside the same connection before reading settings.
            if _migrate_max_stop_pct_to_1(conn):
                userdb.bump()
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
    # MA-touch mode needs at least one of 120/240/480 on; cross mode uses cross_ema_period instead.
    if int(merged.get("entry_trigger", 1)) == 0 and not any(merged[f"ma_{p}"] for p in MA_PERIODS):
        raise SettingsError("Turn on at least one moving average")
    if int(merged["stop_mode"]) == 2 and float(merged["fixed_stop_pct"]) > float(merged["max_stop_pct"]) and int(merged.get("entry_trigger", 1)) == 0:
        raise SettingsError("The fixed stop is wider than the max stop, so every order would be skipped")
    if float(merged["atr_pct_min"]) > float(merged["atr_pct_max"]):
        raise SettingsError("ATR % minimum is above the maximum")
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


def clear_history(db_path: Optional[Path] = None) -> dict:
    """Delete every live alert and every archived alert, including ones still watching.

    Pending, filled, and closed rows all go, so the Alerts list and the metrics start empty.
    Watchlist, positions, trims, extra symbols, alert settings, and user_meta are not touched.
    """
    with _lock, _writing(), userdb.connect(db_path) as conn:
        live = int(conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0])
        archived = int(conn.execute("SELECT COUNT(*) FROM alerts_history").fetchone()[0])
        conn.execute("DELETE FROM alerts")
        conn.execute("DELETE FROM alerts_history")
    return {"alerts": live, "alerts_history": archived}


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

    A live row whose key is already in history is skipped (``alerts_history.key`` is unique, and
    ``ON CONFLICT (id)`` does not cover it) and then deleted. That duplicate must not roll the
    clean alerts in the same run back. The same SQL runs on Postgres and SQLite.
    """
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    stamp = clock.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    day = through.isoformat()
    live_cols = ", ".join(COLUMNS)
    hist_cols = ", ".join((*COLUMNS, *HISTORY_EXTRA))
    # Skip keys already archived. Inserting them raises UniqueViolation on alerts_history.key
    # and aborts the whole transaction, including alerts that should move.
    insert_sql = (
        f"INSERT INTO alerts_history ({hist_cols}) "
        f"SELECT {live_cols}, session, ? FROM alerts WHERE session <= ? "
        "AND key NOT IN (SELECT key FROM alerts_history) "
        "ON CONFLICT (id) DO NOTHING"
    )
    delete_sql = (
        "DELETE FROM alerts WHERE session <= ? AND ("
        "id IN (SELECT id FROM alerts_history) OR key IN (SELECT key FROM alerts_history))"
    )
    with _lock, _writing(), userdb.connect(db_path) as conn:
        before = int(conn.execute("SELECT COUNT(*) FROM alerts WHERE session <= ?", (day,)).fetchone()[0])
        dropped = int(
            conn.execute(
                "SELECT COUNT(*) FROM alerts WHERE session <= ? AND key IN (SELECT key FROM alerts_history)",
                (day,),
            ).fetchone()[0]
        )
        conn.execute(insert_sql, (stamp, day))
        conn.execute(delete_sql, (day,))
        after = int(conn.execute("SELECT COUNT(*) FROM alerts WHERE session <= ?", (day,)).fetchone()[0])
    return {"moved": before - dropped - after, "dropped": dropped, "through": day, "skipped": False}


def archive_if_due(now: Optional[datetime] = None, db_path: Optional[Path] = None) -> dict:
    """Archive every session the clock says is already closed, unless the setting is off."""
    from .scheduler import archive_through, now_et

    clock = now_et(now)
    if not load_settings(db_path).auto_archive:
        return {"moved": 0, "dropped": 0, "skipped": True, "through": None}
    result = archive_alerts(archive_through(clock), now=clock, db_path=db_path)
    result["skipped"] = False
    return result
