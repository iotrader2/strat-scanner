"""SQLite reads and writes for morning leaders. Every write replaces a key, so a re-run is a no-op."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional, Sequence

from . import data

LEADER_FIELDS = ("date", "rank", "symbol", "score", "rs", "name", "as_of")
RANK_FIELDS = (
    "date", "window", "rank", "symbol", "score", "day_move", "vs_qqq", "or_position", "qualified", "cross_time",
)
RESULT_FIELDS = (
    "date", "symbol", "window", "entry_price", "candle_low",
    "eod_ret", "d1_ret", "d2_ret", "d3_ret", "d4_ret", "d5_ret",
    "stopped", "stop_day", "stop_ret", "mfe", "mae", "gapped", "role",
)
SINGLE_FIELDS = (
    "date", "symbol", "rule", "entry_time", "entry_price", "stop_price", "stop_pct",
    "eod_pct", "d1_pct", "d2_pct", "d3_pct", "d4_pct", "d5_pct",
    "stopped", "stop_day", "exit_pct", "gapped", "mfe_pct", "rank", "cross_time",
)


def _rows(conn, sql: str, params: tuple = ()) -> list[dict]:
    conn.row_factory = None
    cursor = conn.execute(sql, params)
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def delete_day(day: str, db_path: Path | None = None) -> None:
    with data._write_lock, data.connect(db_path) as conn:
        conn.execute("DELETE FROM leader_snapshots WHERE date = ?", (day,))
        conn.execute("DELETE FROM interval_ranks WHERE date = ?", (day,))
        conn.execute("DELETE FROM entry_results WHERE date = ?", (day,))
        conn.execute("DELETE FROM intraday_gaps WHERE date = ?", (day,))
        conn.execute("DELETE FROM single_entry WHERE date = ?", (day,))
        conn.execute("DELETE FROM single_entry_day WHERE date = ?", (day,))
        conn.execute("DELETE FROM strat_reversal WHERE date = ?", (day,))
        conn.execute("DELETE FROM strat_reversal_day WHERE date = ?", (day,))
        conn.execute("DELETE FROM cross_trigger WHERE date = ?", (day,))
        conn.execute("DELETE FROM cross_trigger_day WHERE date = ?", (day,))


def leader_dates(db_path: Path | None = None) -> set[str]:
    with data.connect(db_path) as conn:
        return {r[0] for r in conn.execute("SELECT DISTINCT date FROM leader_snapshots")}


def latest_leader_date(db_path: Path | None = None) -> Optional[str]:
    with data.connect(db_path) as conn:
        row = conn.execute("SELECT MAX(date) FROM leader_snapshots").fetchone()
    return row[0] if row and row[0] else None


def earliest_leader_date(db_path: Path | None = None) -> Optional[str]:
    with data.connect(db_path) as conn:
        row = conn.execute("SELECT MIN(date) FROM leader_snapshots").fetchone()
    return row[0] if row and row[0] else None


def replace_leaders(day: str, rows: Sequence[dict], db_path: Path | None = None) -> None:
    payload = [
        (day, int(r["rank"]), r["symbol"], float(r["score"]), r.get("rs"), r.get("name") or "", r["as_of"])
        for r in rows
    ]
    with data._write_lock, data.connect(db_path) as conn:
        conn.execute("DELETE FROM leader_snapshots WHERE date = ?", (day,))
        conn.execute("DELETE FROM interval_ranks WHERE date = ?", (day,))
        conn.execute("DELETE FROM entry_results WHERE date = ? AND role = 'leader'", (day,))
        conn.executemany(
            "INSERT INTO leader_snapshots(date, rank, symbol, score, rs, name, as_of) VALUES (?,?,?,?,?,?,?)",
            payload,
        )


def leaders_between(start: str, end: str, db_path: Path | None = None) -> list[dict]:
    with data.connect(db_path) as conn:
        return _rows(
            conn,
            "SELECT date, rank, symbol, score, rs, name, as_of FROM leader_snapshots "
            "WHERE date >= ? AND date <= ? ORDER BY date, rank",
            (start, end),
        )


def all_leaders(db_path: Path | None = None) -> list[dict]:
    with data.connect(db_path) as conn:
        return _rows(
            conn,
            "SELECT date, rank, symbol, score, rs, name, as_of FROM leader_snapshots ORDER BY date, rank",
        )


def save_bars(symbol: str, frame, interval: str, source: str, db_path: Path | None = None) -> int:
    """Upsert raw 15-minute bars. ``frame`` is indexed by the bar's end time (naive US/Eastern)."""
    if frame is None or frame.empty:
        return 0
    rows = []
    for ts, row in frame.iterrows():
        stamp = pd_stamp(ts)
        rows.append(
            (
                symbol,
                stamp,
                interval,
                float(row.open),
                float(row.high),
                float(row.low),
                float(row.close),
                float(0 if row.volume != row.volume else row.volume),
                source,
            )
        )
    with data._write_lock, data.connect(db_path) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO intraday_bars(symbol, ts, interval, open, high, low, close, volume, source) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            rows,
        )
    return len(rows)


def pd_stamp(ts) -> str:
    import pandas as pd

    stamp = pd.Timestamp(ts)
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert("America/New_York").tz_localize(None)
    return stamp.strftime("%Y-%m-%dT%H:%M:%S")


def mark_gap(symbol: str, day: str, interval: str, source: str, db_path: Path | None = None) -> None:
    checked = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with data._write_lock, data.connect(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO intraday_gaps(symbol, date, interval, source, checked_at) VALUES (?,?,?,?,?)",
            (symbol, day, interval, source, checked),
        )


def gap_dates(interval: str, source: str, db_path: Path | None = None) -> set[tuple[str, str]]:
    with data.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT symbol, date FROM intraday_gaps WHERE interval = ? AND source = ?",
            (interval, source),
        ).fetchall()
    return {(r[0], r[1]) for r in rows}


def bar_coverage(symbols: Iterable[str], start: str, end: str, interval: str = "15m", db_path: Path | None = None) -> set[tuple[str, str]]:
    """(symbol, date) pairs that already have the 10:45 and 16:00 bars, i.e. morning plus the close."""
    symbols = list(symbols)
    if not symbols:
        return set()
    marks = tuple(f"{'?'}" for _ in symbols)
    sql = (
        "SELECT symbol, substr(ts, 1, 10) AS day FROM intraday_bars "
        f"WHERE interval = ? AND symbol IN ({','.join(marks)}) AND ts >= ? AND ts <= ? "
        "AND (substr(ts, 12, 5) = '10:45' OR substr(ts, 12, 5) = '16:00') "
        "GROUP BY symbol, day HAVING COUNT(DISTINCT substr(ts, 12, 5)) = 2"
    )
    with data.connect(db_path) as conn:
        rows = conn.execute(sql, (interval, *symbols, f"{start}T00:00:00", f"{end}T23:59:59")).fetchall()
    return {(r[0], r[1]) for r in rows}


def load_bars(
    symbols: Iterable[str],
    start: str,
    end: str,
    interval: str = "15m",
    db_path: Path | None = None,
):
    """symbol -> DataFrame indexed by naive US/Eastern bar-end timestamps, raw prices."""
    import pandas as pd

    symbols = list(dict.fromkeys(symbols))
    frames: dict[str, pd.DataFrame] = {}
    if not symbols:
        return frames
    marks = ",".join("?" for _ in symbols)
    with data.connect(db_path) as conn:
        df = pd.read_sql_query(
            "SELECT symbol, ts, open, high, low, close, volume FROM intraday_bars "
            f"WHERE interval = ? AND symbol IN ({marks}) AND ts >= ? AND ts <= ? ORDER BY symbol, ts",
            conn,
            params=(interval, *symbols, f"{start}T00:00:00", f"{end}T23:59:59"),
        )
    if df.empty:
        return frames
    df["ts"] = pd.to_datetime(df["ts"])
    for symbol, group in df.groupby("symbol", sort=False):
        frames[symbol] = group.drop(columns="symbol").set_index("ts")
    return frames


def replace_ranks(day: str, rows: Sequence[dict], db_path: Path | None = None) -> None:
    payload = [
        (
            day, r["window"], int(r["rank"]), r["symbol"], float(r["score"]),
            r.get("day_move"), r.get("vs_qqq"), r.get("or_position"),
            int(r.get("qualified", 1)), r.get("cross_time"),
        )
        for r in rows
    ]
    with data._write_lock, data.connect(db_path) as conn:
        conn.execute("DELETE FROM interval_ranks WHERE date = ?", (day,))
        conn.executemany(
            "INSERT INTO interval_ranks(date, window, rank, symbol, score, day_move, vs_qqq, or_position, qualified, cross_time) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            payload,
        )


def ranks_between(start: str, end: str, db_path: Path | None = None) -> list[dict]:
    with data.connect(db_path) as conn:
        return _rows(
            conn,
            "SELECT date, window, rank, symbol, score, day_move, vs_qqq, or_position, qualified, cross_time "
            "FROM interval_ranks WHERE date >= ? AND date <= ? ORDER BY date, window, rank",
            (start, end),
        )


def latest_bar_day(symbols: Iterable[str], interval: str, db_path: Path | None = None) -> dict[str, str]:
    """Newest stored session (YYYY-MM-DD) per symbol for one interval."""
    symbols = list(dict.fromkeys(symbols))
    if not symbols:
        return {}
    marks = ",".join("?" for _ in symbols)
    with data.connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT symbol, MAX(substr(ts, 1, 10)) FROM intraday_bars "
            f"WHERE interval = ? AND symbol IN ({marks}) GROUP BY symbol",
            (interval, *symbols),
        ).fetchall()
    return {symbol: day for symbol, day in rows if day}


def replace_results(day: str, rows: Sequence[dict], *, role: str, db_path: Path | None = None) -> None:
    payload = []
    for r in rows:
        payload.append(
            (
                day, r["symbol"], r["window"], float(r["entry_price"]), r.get("candle_low"),
                r.get("eod_ret"), r.get("d1_ret"), r.get("d2_ret"), r.get("d3_ret"), r.get("d4_ret"), r.get("d5_ret"),
                int(r.get("stopped") or 0), r.get("stop_day"), r.get("stop_ret"), r.get("mfe"), r.get("mae"),
                int(r.get("gapped") or 0), role,
            )
        )
    with data._write_lock, data.connect(db_path) as conn:
        conn.execute("DELETE FROM entry_results WHERE date = ? AND role = ?", (day, role))
        conn.executemany(
            "INSERT INTO entry_results(date, symbol, window, entry_price, candle_low, eod_ret, d1_ret, d2_ret, "
            "d3_ret, d4_ret, d5_ret, stopped, stop_day, stop_ret, mfe, mae, gapped, role) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            payload,
        )


def results_between(start: str, end: str, role: Optional[str] = None, db_path: Path | None = None) -> list[dict]:
    sql = (
        "SELECT date, symbol, window, entry_price, candle_low, eod_ret, d1_ret, d2_ret, d3_ret, d4_ret, d5_ret, "
        "stopped, stop_day, stop_ret, mfe, mae, gapped, role FROM entry_results WHERE date >= ? AND date <= ?"
    )
    params: list = [start, end]
    if role:
        sql += " AND role = ?"
        params.append(role)
    sql += " ORDER BY date, window, symbol"
    with data.connect(db_path) as conn:
        return _rows(conn, sql, tuple(params))


def all_results(role: Optional[str] = None, db_path: Path | None = None) -> list[dict]:
    sql = (
        "SELECT date, symbol, window, entry_price, candle_low, eod_ret, d1_ret, d2_ret, d3_ret, d4_ret, d5_ret, "
        "stopped, stop_day, stop_ret, mfe, mae, gapped, role FROM entry_results"
    )
    params: tuple = ()
    if role:
        sql += " WHERE role = ?"
        params = (role,)
    with data.connect(db_path) as conn:
        return _rows(conn, sql, params)


def result_dates(role: str = "leader", db_path: Path | None = None) -> set[str]:
    with data.connect(db_path) as conn:
        return {r[0] for r in conn.execute("SELECT DISTINCT date FROM entry_results WHERE role = ?", (role,))}


def incomplete_result_dates(calendar: Sequence[str], role: str = "leader", db_path: Path | None = None) -> set[str]:
    """Days whose +5 close was unknown last time and can now be filled, plus days with no results yet."""
    with data.connect(db_path) as conn:
        pending = {
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT date FROM entry_results WHERE role = ? AND d5_ret IS NULL",
                (role,),
            )
        }
        have = {r[0] for r in conn.execute("SELECT DISTINCT date FROM entry_results WHERE role = ?", (role,))}
    future = set(calendar)
    ready = set()
    ordered = list(calendar)
    index = {day: i for i, day in enumerate(ordered)}
    for day in pending:
        pos = index.get(day)
        if pos is None:
            continue
        if pos + 5 < len(ordered):
            ready.add(day)
    return ready | (future - have)


def replace_single_entries(day: str, rows: Sequence[dict], db_path: Path | None = None) -> None:
    """Replace one session of the low-of-day study and mark the session built, even with no fills."""
    payload = []
    for r in rows:
        payload.append(
            (
                day, r["symbol"], r["rule"], r["entry_time"], float(r["entry_price"]),
                r.get("stop_price"), r.get("stop_pct"),
                r.get("eod_pct"), r.get("d1_pct"), r.get("d2_pct"), r.get("d3_pct"), r.get("d4_pct"), r.get("d5_pct"),
                int(r.get("stopped") or 0), r.get("stop_day"), r.get("exit_pct"), int(r.get("gapped") or 0),
                r.get("mfe_pct"), r.get("rank"), r.get("cross_time"),
            )
        )
    with data._write_lock, data.connect(db_path) as conn:
        conn.execute("DELETE FROM single_entry WHERE date = ?", (day,))
        conn.executemany(
            "INSERT INTO single_entry(date, symbol, rule, entry_time, entry_price, stop_price, stop_pct, "
            "eod_pct, d1_pct, d2_pct, d3_pct, d4_pct, d5_pct, stopped, stop_day, exit_pct, gapped, mfe_pct, rank, cross_time) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            payload,
        )
        conn.execute("INSERT OR REPLACE INTO single_entry_day(date) VALUES (?)", (day,))


def single_entries_between(start: str, end: str, db_path: Path | None = None) -> list[dict]:
    with data.connect(db_path) as conn:
        return _rows(
            conn,
            "SELECT date, symbol, rule, entry_time, entry_price, stop_price, stop_pct, "
            "eod_pct, d1_pct, d2_pct, d3_pct, d4_pct, d5_pct, stopped, stop_day, exit_pct, gapped, mfe_pct, rank, cross_time "
            "FROM single_entry WHERE date >= ? AND date <= ? ORDER BY date, rule, rank, symbol",
            (start, end),
        )


def single_entry_days(db_path: Path | None = None) -> set[str]:
    with data.connect(db_path) as conn:
        return {r[0] for r in conn.execute("SELECT date FROM single_entry_day")}


def replace_strat_reversals(day: str, rows: Sequence[dict], db_path: Path | None = None) -> None:
    """Replace one session of the Strat reversal study and mark it built, even with no fills."""
    payload = []
    for r in rows:
        payload.append(
            (
                day, r["symbol"], int(r["timeframe"]), r["entry_time"], float(r["entry_price"]),
                r.get("stop_price"), r.get("stop_pct"),
                r.get("eod_pct"), r.get("d1_pct"), r.get("d2_pct"), r.get("d3_pct"), r.get("d4_pct"), r.get("d5_pct"),
                int(r.get("stopped") or 0), r.get("stop_day"), r.get("exit_pct"), int(r.get("gapped") or 0),
                r.get("mfe_pct"), r.get("pattern"), int(r.get("qualified") or 0), int(r.get("finished_2u") or 0),
            )
        )
    with data._write_lock, data.connect(db_path) as conn:
        conn.execute("DELETE FROM strat_reversal WHERE date = ?", (day,))
        conn.executemany(
            "INSERT INTO strat_reversal(date, symbol, timeframe, entry_time, entry_price, stop_price, stop_pct, "
            "eod_pct, d1_pct, d2_pct, d3_pct, d4_pct, d5_pct, stopped, stop_day, exit_pct, gapped, mfe_pct, "
            "pattern, qualified, finished_2u) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            payload,
        )
        conn.execute("INSERT OR REPLACE INTO strat_reversal_day(date) VALUES (?)", (day,))


def strat_reversals_between(start: str, end: str, db_path: Path | None = None) -> list[dict]:
    with data.connect(db_path) as conn:
        return _rows(
            conn,
            "SELECT date, symbol, timeframe, entry_time, entry_price, stop_price, stop_pct, "
            "eod_pct, d1_pct, d2_pct, d3_pct, d4_pct, d5_pct, stopped, stop_day, exit_pct, gapped, mfe_pct, "
            "pattern, qualified, finished_2u "
            "FROM strat_reversal WHERE date >= ? AND date <= ? ORDER BY date, timeframe, entry_time, symbol",
            (start, end),
        )


def strat_reversal_days(db_path: Path | None = None) -> set[str]:
    with data.connect(db_path) as conn:
        return {r[0] for r in conn.execute("SELECT date FROM strat_reversal_day")}


def replace_cross_triggers(
    day: str,
    rows: Sequence[dict],
    db_path: Path | None = None,
    *,
    had_tape: bool = True,
) -> None:
    """Replace one session of the cross-trigger study and mark it built, even with no fills.

    ``had_tape`` is false when the session has no 5-minute bars. Those days stay out of the
    trades-per-day denominator. A session with tape and zero triggers is stored with ``had_tape``.
    """
    payload = []
    for r in rows:
        payload.append(
            (
                day, r["symbol"], r["rule"], r["entry_time"], float(r["entry_price"]),
                r.get("stop_price"), r.get("stop_pct"),
                r.get("eod_pct"), r.get("d1_pct"), r.get("d2_pct"), r.get("d3_pct"), r.get("d4_pct"), r.get("d5_pct"),
                int(r.get("stopped") or 0), r.get("stop_day"), r.get("exit_pct"), int(r.get("gapped") or 0),
                r.get("mfe_pct"), int(r.get("opened_above") or 0),
            )
        )
    with data._write_lock, data.connect(db_path) as conn:
        conn.execute("DELETE FROM cross_trigger WHERE date = ?", (day,))
        conn.executemany(
            "INSERT INTO cross_trigger(date, symbol, rule, entry_time, entry_price, stop_price, stop_pct, "
            "eod_pct, d1_pct, d2_pct, d3_pct, d4_pct, d5_pct, stopped, stop_day, exit_pct, gapped, mfe_pct, "
            "opened_above) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            payload,
        )
        conn.execute(
            "INSERT OR REPLACE INTO cross_trigger_day(date, had_tape) VALUES (?, ?)",
            (day, 1 if had_tape else 0),
        )


def cross_triggers_between(start: str, end: str, db_path: Path | None = None) -> list[dict]:
    with data.connect(db_path) as conn:
        return _rows(
            conn,
            "SELECT date, symbol, rule, entry_time, entry_price, stop_price, stop_pct, "
            "eod_pct, d1_pct, d2_pct, d3_pct, d4_pct, d5_pct, stopped, stop_day, exit_pct, gapped, mfe_pct, "
            "opened_above "
            "FROM cross_trigger WHERE date >= ? AND date <= ? ORDER BY date, rule, entry_time, symbol",
            (start, end),
        )


def cross_trigger_days(db_path: Path | None = None) -> set[str]:
    with data.connect(db_path) as conn:
        return {r[0] for r in conn.execute("SELECT date FROM cross_trigger_day")}


def cross_trigger_tape_days(db_path: Path | None = None) -> list[str]:
    """Sessions that had 5-minute tape, including mornings where nobody triggered."""
    with data.connect(db_path) as conn:
        return [r[0] for r in conn.execute(
            "SELECT date FROM cross_trigger_day WHERE had_tape = 1 ORDER BY date"
        )]


def revision(db_path: Path | None = None) -> str:
    with data.connect(db_path) as conn:
        leaders = conn.execute("SELECT COUNT(*), MAX(date) FROM leader_snapshots").fetchone()
        results = conn.execute("SELECT COUNT(*), MAX(date) FROM entry_results").fetchone()
        ranks = conn.execute("SELECT COUNT(*), MAX(date) FROM interval_ranks").fetchone()
        single = conn.execute("SELECT COUNT(*), MAX(date) FROM single_entry").fetchone()
        strat = conn.execute("SELECT COUNT(*), MAX(date) FROM strat_reversal").fetchone()
        cross = conn.execute("SELECT COUNT(*), MAX(date) FROM cross_trigger").fetchone()
    return (
        f"{leaders[0]}:{leaders[1]}:{results[0]}:{results[1]}:{ranks[0]}:{ranks[1]}:"
        f"{single[0]}:{single[1]}:{strat[0]}:{strat[1]}:{cross[0]}:{cross[1]}"
    )


def _bar_span(conn, interval: str) -> tuple[int, Optional[str], Optional[str]]:
    row = conn.execute(
        "SELECT COUNT(*), MIN(ts), MAX(ts) FROM intraday_bars WHERE interval = ?",
        (interval,),
    ).fetchone()
    return int(row[0] or 0), row[1], row[2]


def counts(db_path: Path | None = None) -> dict:
    with data.connect(db_path) as conn:
        days = conn.execute("SELECT COUNT(DISTINCT date) FROM leader_snapshots").fetchone()[0]
        names = conn.execute("SELECT COUNT(*) FROM leader_snapshots").fetchone()[0]
        bars = conn.execute("SELECT COUNT(*), MIN(ts), MAX(ts) FROM intraday_bars").fetchone()
        five = _bar_span(conn, "5m")
        fifteen = _bar_span(conn, "15m")
        sources = conn.execute("SELECT source, COUNT(DISTINCT symbol) FROM intraday_bars GROUP BY source").fetchall()
        results = conn.execute(
            "SELECT COUNT(DISTINCT date) FROM entry_results WHERE role = 'leader'"
        ).fetchone()[0]
        single_days = conn.execute("SELECT COUNT(*) FROM single_entry_day").fetchone()[0]
        single_rows = conn.execute(
            "SELECT COUNT(*) FROM single_entry WHERE rule != 'qqq'"
        ).fetchone()[0]
        strat_days = conn.execute("SELECT COUNT(*) FROM strat_reversal_day").fetchone()[0]
        strat_rows = conn.execute(
            "SELECT COUNT(*) FROM strat_reversal WHERE timeframe != 0"
        ).fetchone()[0]
        cross_days = conn.execute("SELECT COUNT(*) FROM cross_trigger_day WHERE had_tape = 1").fetchone()[0]
        cross_rows = conn.execute(
            "SELECT COUNT(*) FROM cross_trigger WHERE rule != 'qqq'"
        ).fetchone()[0]
    return {
        "leader_days": int(days or 0),
        "leader_rows": int(names or 0),
        "bar_rows": int(bars[0] or 0),
        "bar_start": bars[1],
        "bar_end": bars[2],
        "bar_rows_5m": five[0],
        "bar_start_5m": five[1],
        "bar_end_5m": five[2],
        "bar_rows_15m": fifteen[0],
        "bar_start_15m": fifteen[1],
        "bar_end_15m": fifteen[2],
        "bar_sources": {src: int(n) for src, n in sources},
        "result_days": int(results or 0),
        "single_days": int(single_days or 0),
        "single_rows": int(single_rows or 0),
        "strat_days": int(strat_days or 0),
        "strat_rows": int(strat_rows or 0),
        "cross_days": int(cross_days or 0),
        "cross_rows": int(cross_rows or 0),
    }
