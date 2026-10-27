"""Move a closed session from the live alerts table into alerts_history."""

import sqlite3
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from strat import alerts_store, api, config, userdb
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
    assert moved == {"moved": 2, "through": "2026-10-23", "skipped": False}
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


def test_history_table_keeps_the_original_id_on_both_backends():
    assert "CREATE TABLE IF NOT EXISTS alerts_history" in userdb.SQLITE_SCHEMA
    assert "CREATE TABLE IF NOT EXISTS alerts_history" in userdb.PG_SCHEMA
    sqlite_history = userdb.SQLITE_SCHEMA.split("alerts_history", 1)[1].split("CREATE INDEX", 1)[0]
    pg_history = userdb.PG_SCHEMA.split("alerts_history", 1)[1].split("CREATE INDEX", 1)[0]
    assert "AUTOINCREMENT" not in sqlite_history
    assert "INTEGER PRIMARY KEY" in sqlite_history
    assert "BIGSERIAL" not in pg_history
    assert "BIGINT PRIMARY KEY" in pg_history
