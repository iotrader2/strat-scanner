"""Move a closed session from the live alerts table into alerts_history."""

import logging
import sqlite3
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from strat import alerts_live, alerts_store, api, config, userdb
from strat.alerts import Context, simulate

OPEN = datetime(2026, 10, 23, 13, 30, tzinfo=timezone.utc)  # 09:30 EDT, Friday
A_ROWS = [(100, 101, 99.9, 100.9)]
LIVE_KEYS = ["session", "alerts", "sessions", "unread", "last_run", "watchlist", "setups", "ema5m"]


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "cache.sqlite3")
    return None


def _bars(rows, start=OPEN):
    return [
        {"t": start + timedelta(minutes=5 * i), "o": o, "h": h, "l": l, "c": c, "v": 1000.0}
        for i, (o, h, l, c) in enumerate(rows)
    ]


def _save(symbol, session, when=None, start=OPEN):
    found = simulate(symbol, session, _bars(A_ROWS, start), Context(warm_closes=[100.0] * 60))
    return alerts_store.save_session(session, found, now=when or (OPEN + timedelta(minutes=6)))


def _ids(rows):
    return [r["id"] for r in rows]


def test_archive_is_idempotent_and_keeps_ids(db):
    first = _save("AAA", "2026-10-23")
    second = _save("BBB", "2026-10-23")
    live = alerts_store.list_alerts(session="2026-10-23")
    assert _ids(live) == [second["inserted"][0]["id"], first["inserted"][0]["id"]]
    original = {r["id"]: r for r in live}

    moved = alerts_store.archive_if_due(datetime(2026, 10, 23, 20, 5, tzinfo=timezone.utc))  # 16:05 EDT
    assert moved == {"moved": 2, "dropped": 0, "through": "2026-10-23", "skipped": False}
    assert alerts_store.list_alerts(session="2026-10-23") == []
    history = alerts_store.list_history("2026-10-23")
    assert _ids(history) == _ids(live)
    for row in history:
        before = original[row["id"]]
        for key, value in before.items():
            assert row[key] == value
        assert row["trading_date"] == "2026-10-23"
        assert row["archived_at"] == "2026-10-23T20:05:00Z"

    again = alerts_store.archive_if_due(datetime(2026, 10, 23, 20, 6, tzinfo=timezone.utc))
    assert again["moved"] == 0
    assert alerts_store.list_history("2026-10-23") == history

    # The next live alert must not reuse an archived id. The local app uses the id as clientOrderId.
    monday = datetime(2026, 10, 26, 13, 30, tzinfo=timezone.utc)
    new = _save("CCC", "2026-10-26", when=monday + timedelta(minutes=6), start=monday)
    assert new["inserted"][0]["id"] not in original
    assert set(_ids(alerts_store.list_alerts())).isdisjoint(_ids(alerts_store.list_history()))


def test_the_close_boundary_keeps_today_until_1605_and_follows_dst(db):
    _save("AAA", "2026-07-14", start=datetime(2026, 7, 14, 13, 30, tzinfo=timezone.utc))
    _save("BBB", "2026-07-15", start=datetime(2026, 7, 15, 13, 30, tzinfo=timezone.utc))

    early = alerts_store.archive_if_due(datetime(2026, 7, 15, 20, 4, tzinfo=timezone.utc))  # 16:04 EDT
    assert early["through"] == "2026-07-14" and early["moved"] == 1
    assert [r["symbol"] for r in alerts_store.list_alerts()] == ["BBB"]
    assert [r["symbol"] for r in alerts_store.list_history("2026-07-14")] == ["AAA"]

    due = alerts_store.archive_if_due(datetime(2026, 7, 15, 20, 5, tzinfo=timezone.utc))  # 16:05 EDT
    assert due["moved"] == 1 and due["through"] == "2026-07-15"
    assert alerts_store.list_alerts() == []

    # The same UTC minute is still the regular session in January (EST, UTC-5).
    _save("CCC", "2026-01-15", start=datetime(2026, 1, 15, 14, 30, tzinfo=timezone.utc))
    winter_early = alerts_store.archive_if_due(datetime(2026, 1, 15, 20, 5, tzinfo=timezone.utc))  # 15:05 EST
    assert winter_early["through"] == "2026-01-14"
    assert [r["symbol"] for r in alerts_store.list_alerts()] == ["CCC"]
    winter_due = alerts_store.archive_if_due(datetime(2026, 1, 15, 21, 5, tzinfo=timezone.utc))  # 16:05 EST
    assert winter_due["moved"] == 1 and winter_due["through"] == "2026-01-15"
    assert alerts_store.list_history("2026-01-15")[0]["symbol"] == "CCC"


def test_a_restart_after_the_close_catches_up_once(db):
    api._reset_archive_retry()
    saved = _save("AAA", "2026-10-23")
    saturday = datetime(2026, 10, 24, 14, 0, tzinfo=timezone.utc)  # 10:00 EDT
    first = api._catch_up_alert_archive(None, saturday)
    assert first == date(2026, 10, 23)
    assert alerts_store.list_alerts() == []
    assert alerts_store.list_history("2026-10-23")[0]["id"] == saved["inserted"][0]["id"]

    calls = []
    monkey_target = alerts_store.archive_if_due

    def wrapped(now=None, db_path=None):
        calls.append(now)
        return monkey_target(now, db_path)

    alerts_store.archive_if_due = wrapped
    try:
        second = api._catch_up_alert_archive(first, saturday)
    finally:
        alerts_store.archive_if_due = monkey_target
    assert second == first and calls == []


def test_archive_off_leaves_the_live_table(db):
    _save("AAA", "2026-10-23")
    alerts_store.save_settings({"auto_archive": 0})
    skipped = alerts_store.archive_if_due(datetime(2026, 10, 23, 20, 5, tzinfo=timezone.utc))
    assert skipped["skipped"] is True and skipped["moved"] == 0
    assert len(alerts_store.list_alerts(session="2026-10-23")) == 1
    assert alerts_store.history_dates() == []
    # Out of range is rejected; the default is on.
    with pytest.raises(alerts_store.SettingsError):
        alerts_store.save_settings({"auto_archive": 2})
    alerts_store.reset_settings()
    assert alerts_store.load_settings().auto_archive == 1


def test_a_failed_delete_rolls_the_insert_back(db):
    """Insert and delete share one transaction, so a restart mid-delete leaves both tables unchanged."""
    _save("AAA", "2026-10-23")
    _save("BBB", "2026-10-23")
    with userdb.connect() as conn:
        conn.execute(
            "CREATE TRIGGER abort_delete BEFORE DELETE ON alerts "
            "BEGIN SELECT RAISE(ABORT, 'dyno restarted'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="dyno restarted"):
        alerts_store.archive_alerts(date(2026, 10, 23), now=datetime(2026, 10, 23, 20, 5, tzinfo=timezone.utc))
    assert {r["symbol"] for r in alerts_store.list_alerts(session="2026-10-23")} == {"AAA", "BBB"}
    assert alerts_store.history_dates() == []


def test_history_endpoint_is_read_only_and_live_shape_stays(db):
    friday = _save("AAA", "2026-10-23")
    _save("BBB", "2026-10-22", start=datetime(2026, 10, 22, 13, 30, tzinfo=timezone.utc))
    alerts_store.archive_if_due(datetime(2026, 10, 24, 14, 0, tzinfo=timezone.utc))  # Saturday, both closed

    c = TestClient(api.app)
    api.State.scan = [{
        "symbol": "AAA", "score": 88.4, "score_raw": 60.0, "score_max_raw": 72,
        "score_breakdown": [{"key": "rs", "label": "Relative strength", "points": 18, "max_points": 24,
                             "weight_pct": 33, "detail": "Top decile", "sub_weights": []}],
    }]
    try:
        live = c.get("/api/alerts", params={"session": "2026-10-23"}).json()
        default = c.get("/api/alerts/history").json()
        older = c.get("/api/alerts/history", params={"date": "2026-10-22"}).json()
        empty = c.get("/api/alerts/history", params={"date": "2026-10-21"}).json()
        metrics = c.get("/api/alerts/metrics", params={"start": "2026-10-01", "end": "2026-10-31"}).json()
    finally:
        api.State.scan = []

    assert list(live) == LIVE_KEYS
    assert live["alerts"] == []
    assert live["sessions"] == []
    assert default["date"] == "2026-10-23"
    assert default["dates"] == ["2026-10-23", "2026-10-22"]
    assert default["alerts"][0]["id"] == friday["inserted"][0]["id"]
    assert default["alerts"][0]["symbol"] == "AAA"
    assert default["alerts"][0]["trading_date"] == "2026-10-23"
    assert default["alerts"][0]["score"] == 88.4
    assert "archived_at" in default["alerts"][0]
    assert older["alerts"][0]["symbol"] == "BBB" and older["alerts"][0]["id"] != default["alerts"][0]["id"]
    assert empty["date"] == "2026-10-21" and empty["alerts"] == []
    assert c.get("/api/alerts/history", params={"date": "Friday"}).status_code == 422
    assert {r["setup"]: r["count"] for r in metrics["rows"]}["A"] == 2
    assert metrics["symbols"] == ["AAA", "BBB"]


def _history_table(schema: str) -> str:
    """Column list of ``alerts_history``, not the earlier comment that names the table.

    The live ``alerts`` table is ``INTEGER PRIMARY KEY AUTOINCREMENT`` / ``BIGSERIAL``.
    History copies that id, so its own primary key must not be a second sequence.
    """
    marker = "CREATE TABLE IF NOT EXISTS alerts_history"
    start = schema.index(marker) + len(marker)
    return schema[start:].split("CREATE INDEX", 1)[0]


def _copy_history_to_live(session: str, symbol: str) -> int:
    """Put an archived alert back on the live table under a new id, the way the stage bug left it."""
    cols = [c for c in alerts_store.COLUMNS if c != "id"]
    listed = ", ".join(cols)
    with userdb.connect() as conn:
        row = conn.execute(
            f"SELECT {listed} FROM alerts_history WHERE session = ? AND symbol = ?",
            (session, symbol),
        ).fetchone()
        assert row is not None
        return userdb.insert_returning_id(
            conn,
            f"INSERT INTO alerts({listed}) VALUES ({', '.join('?' * len(cols))})",
            tuple(row),
        )


def test_a_live_duplicate_key_is_dropped_and_history_keeps_the_original(db):
    """The old insert named ON CONFLICT (id) only, so a repeated key aborted the transaction."""
    wed = datetime(2026, 10, 28, 13, 30, tzinfo=timezone.utc)
    saved = _save("TEAM", "2026-10-28", start=wed)
    original = saved["inserted"][0]["id"]
    stamp = datetime(2026, 10, 28, 20, 5, tzinfo=timezone.utc)
    assert alerts_store.archive_alerts(date(2026, 10, 28), now=stamp)["moved"] == 1
    history = alerts_store.list_history("2026-10-28")
    duplicate = _copy_history_to_live("2026-10-28", "TEAM")
    assert duplicate != original
    assert alerts_store.list_alerts()[0]["key"] == history[0]["key"]

    live_cols = ", ".join(alerts_store.COLUMNS)
    hist_cols = ", ".join((*alerts_store.COLUMNS, *alerts_store.HISTORY_EXTRA))
    old_insert = (
        f"INSERT INTO alerts_history ({hist_cols}) "
        f"SELECT {live_cols}, session, ? FROM alerts WHERE session <= ? "
        "ON CONFLICT (id) DO NOTHING"
    )
    with pytest.raises(sqlite3.IntegrityError, match="alerts_history.key"):
        with userdb.connect() as conn:
            conn.execute(old_insert, ("2026-10-28T20:06:00Z", "2026-10-28"))

    result = alerts_store.archive_alerts(date(2026, 10, 28), now=stamp + timedelta(minutes=1))
    assert result == {"moved": 0, "dropped": 1, "through": "2026-10-28", "skipped": False}
    assert alerts_store.list_alerts() == []
    kept = alerts_store.list_history("2026-10-28")
    assert kept == history
    assert [r["id"] for r in kept] == [original]
    second = alerts_store.archive_alerts(date(2026, 10, 28), now=stamp + timedelta(minutes=2))
    assert second["moved"] == 0 and second["dropped"] == 0
    assert alerts_store.list_history("2026-10-28") == kept


def test_one_duplicate_does_not_block_the_clean_alerts_in_the_same_run(db):
    """Stage shape: 10-28 rows recreated with new ids, plus later alerts that still need archiving.

    Live 30 TEAM / 31 WDAY were that recreation; 33 and 34 were the clean 10-29 rows the
    key collision rolled back. One run drops the duplicates and moves the clean rows.
    """
    wed = datetime(2026, 10, 28, 13, 30, tzinfo=timezone.utc)
    team = _save("TEAM", "2026-10-28", start=wed)
    wday = _save("WDAY", "2026-10-28", start=wed)
    team_id, wday_id = team["inserted"][0]["id"], wday["inserted"][0]["id"]
    alerts_store.archive_alerts(date(2026, 10, 28), now=datetime(2026, 10, 28, 20, 5, tzinfo=timezone.utc))
    # Same session, never archived, then the two re-creations, then the next session's clean alerts.
    msft = _save("MSFT", "2026-10-28", start=wed)
    msft_id = msft["inserted"][0]["id"]
    dup_team = _copy_history_to_live("2026-10-28", "TEAM")
    dup_wday = _copy_history_to_live("2026-10-28", "WDAY")
    thu = datetime(2026, 10, 29, 13, 30, tzinfo=timezone.utc)
    first = _save("AAA", "2026-10-29", start=thu, when=thu + timedelta(minutes=6))
    second = _save("BBB", "2026-10-29", start=thu, when=thu + timedelta(minutes=6))
    first_id, second_id = first["inserted"][0]["id"], second["inserted"][0]["id"]
    assert {dup_team, dup_wday}.isdisjoint({team_id, wday_id, msft_id, first_id, second_id})

    result = alerts_store.archive_alerts(date(2026, 10, 29), now=datetime(2026, 10, 29, 20, 5, tzinfo=timezone.utc))
    assert result["dropped"] == 2 and result["moved"] == 3
    assert alerts_store.list_alerts() == []
    assert {r["symbol"]: r["id"] for r in alerts_store.list_history("2026-10-28")} == {
        "TEAM": team_id, "WDAY": wday_id, "MSFT": msft_id,
    }
    assert {r["symbol"]: r["id"] for r in alerts_store.list_history("2026-10-29")} == {
        "AAA": first_id, "BBB": second_id,
    }
    again = alerts_store.archive_alerts(date(2026, 10, 29), now=datetime(2026, 10, 29, 20, 6, tzinfo=timezone.utc))
    assert again["moved"] == 0 and again["dropped"] == 0


def test_an_archived_key_is_not_recreated_by_a_later_pass(db):
    """After 16:05 the alert poll is still due until 16:15, and a restart warm-up runs it.

    ``save_session`` used to notice the key was gone from the live table and insert a new id.
    The order app uses that id as clientOrderId. ``alerts_replay`` does not write; this pass does.
    """
    saved = _save("AAA", "2026-10-23")
    original = saved["inserted"][0]["id"]
    key = alerts_store.list_alerts()[0]["key"]
    later = datetime(2026, 10, 23, 20, 10, tzinfo=timezone.utc)  # 16:10 EDT
    assert alerts_live.due(later)
    assert alerts_store.archive_if_due(later)["moved"] == 1

    found = simulate("AAA", "2026-10-23", _bars(A_ROWS), Context(warm_closes=[100.0] * 60))
    assert any(a.key == key for a in found)
    again = alerts_store.save_session("2026-10-23", found, now=later)
    assert again["inserted"] == [] and again["removed"] == 0
    assert alerts_store.list_alerts() == []
    assert [r["id"] for r in alerts_store.list_history("2026-10-23")] == [original]

    # A duplicate already sitting on the live table is removed, not given another id.
    duplicate = _copy_history_to_live("2026-10-23", "AAA")
    cleaned = alerts_store.save_session("2026-10-23", found, now=later)
    assert cleaned["inserted"] == [] and cleaned["removed"] == 1
    assert alerts_store.list_alerts() == []
    assert [r["id"] for r in alerts_store.list_history("2026-10-23")] == [original]
    assert duplicate != original


def _raw(t, o, h, l, c, v):
    return {"t": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "o": o, "h": h, "l": l, "c": c, "v": v}


class _Bars:
    def __init__(self, sip, iex):
        self.sip, self.iex = sip, iex
        self.requests = 0

    def bars(self, symbols, tf, start, end=None, feed=None, adjustment="raw"):
        self.requests += 1
        src = self.iex if feed == "iex" else self.sip
        out = {}
        for symbol in symbols:
            rows = []
            for bar in src.get(symbol, []):
                t = datetime.fromisoformat(bar["t"].replace("Z", "+00:00"))
                if start <= t <= (end or start + timedelta(days=99)):
                    rows.append(bar)
            out[symbol] = rows
        return out, []


def test_a_restart_poll_after_the_archive_does_not_recreate_the_alert(db):
    """The boot catch-up archives, then the warm-up poll re-runs today. That must not mint an id."""
    alerts_live.clear()
    prior = OPEN - timedelta(days=1)
    today = _raw(OPEN, 100, 101, 99.9, 100.9, 1000)
    # After 16:05 the SIP cutoff covers the open, so today's candle must be on SIP (as on stage).
    sip = {
        "AAA": [_raw(prior + timedelta(minutes=15 * k), 100, 100, 100, 100, 1) for k in range(26)] + [today]
    }
    iex = {
        "AAA": [today]
        + [_raw(prior + timedelta(minutes=15 * k), 100, 100, 100, 100, 1000) for k in range(26)]
    }
    client = _Bars(sip, iex)
    try:
        first = alerts_live.refresh(["AAA"], lambda s, d: 100.0, now=OPEN + timedelta(minutes=16), client=client)
        assert len(first["inserted"]) == 1
        original = first["inserted"][0]["id"]
        later = datetime(2026, 10, 23, 20, 10, tzinfo=timezone.utc)  # 16:10 EDT, still inside RUN_UNTIL
        assert alerts_live.due(later)
        assert alerts_store.archive_if_due(later)["moved"] == 1
        second = alerts_live.refresh(["AAA"], lambda s, d: 100.0, now=later, client=client)
        assert not second.get("skipped")
        assert second["alerts"] >= 1 and second["inserted"] == []
        assert alerts_store.list_alerts() == []
        assert alerts_store.list_history("2026-10-23")[0]["id"] == original
    finally:
        alerts_live.clear()


def test_archive_failure_is_logged_once_and_backs_off(db, monkeypatch, caplog):
    api._reset_archive_retry()
    _save("AAA", "2026-10-23")
    when = datetime(2026, 10, 23, 20, 5, tzinfo=timezone.utc)
    clock = {"t": 1_000_000.0}
    monkeypatch.setattr(api.time, "monotonic", lambda: clock["t"])
    calls = {"n": 0}

    def flaky(now=None, db_path=None):
        calls["n"] += 1
        if calls["n"] != 3:
            raise sqlite3.OperationalError("database is locked")
        return {"moved": 1, "dropped": 0, "skipped": False, "through": "2026-10-23"}

    monkeypatch.setattr(alerts_store, "archive_if_due", flaky)
    try:
        with caplog.at_level(logging.ERROR, logger="strat.api"):
            assert api._catch_up_alert_archive(None, when) is None
            clock["t"] += 20  # the scheduler tick, still inside the first minute
            assert api._catch_up_alert_archive(None, when) is None
            assert calls["n"] == 1
            clock["t"] += 40  # the first backoff (60s) has elapsed
            assert api._catch_up_alert_archive(None, when) is None
            assert calls["n"] == 2
            failed = [r for r in caplog.records if r.levelno >= logging.ERROR]
            assert len(failed) == 1 and "next try in 60s" in failed[0].message
            clock["t"] += 120  # the second wait was 120s; this attempt recovers
            assert api._catch_up_alert_archive(None, when) == date(2026, 10, 23)
            assert calls["n"] == 3
            clock["t"] += 1
            assert api._catch_up_alert_archive(None, when) is None
            assert calls["n"] == 4
            failed = [r for r in caplog.records if r.levelno >= logging.ERROR]
            assert len(failed) == 2
    finally:
        api._reset_archive_retry()
    assert len(alerts_store.list_alerts(session="2026-10-23")) == 1


def test_history_table_keeps_the_original_id_on_both_backends():
    assert "CREATE TABLE IF NOT EXISTS alerts_history" in userdb.SQLITE_SCHEMA
    assert "CREATE TABLE IF NOT EXISTS alerts_history" in userdb.PG_SCHEMA
    sqlite_history = _history_table(userdb.SQLITE_SCHEMA)
    pg_history = _history_table(userdb.PG_SCHEMA)
    assert "AUTOINCREMENT" not in sqlite_history
    assert "INTEGER PRIMARY KEY" in sqlite_history
    assert "BIGSERIAL" not in pg_history
    assert "BIGINT PRIMARY KEY" in pg_history
