"""User data storage: SQLite fallback, the Postgres path (only with TEST_DATABASE_URL), and the import tool."""

import json
import os
import uuid

import pytest

from strat import alerts_store, config, data, userdb, userdb_import


@pytest.fixture
def sqlite_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "cache.sqlite3")
    monkeypatch.delenv("DATABASE_URL", raising=False)


def _exercise():
    data.add_to_watchlist("AAPL")
    data.add_to_watchlist("MU")
    data.add_to_watchlist("AAPL")  # duplicate ignored
    assert data.watchlist() == ["AAPL", "MU"]
    data.save_position("TEAM", 223.32, 200, "2026-10-23")
    data.save_position("TEAM", 224.0, 200, "2026-10-23")  # update keeps one row
    trim = data.add_trim("TEAM", 50, 230.0)
    assert trim["id"] > 0
    assert data.trimmed_shares("TEAM") == 50
    assert data.positions() == [{"symbol": "TEAM", "entry_price": 224.0, "shares": 200, "entry_date": "2026-10-23"}]
    data.delete_trim("TEAM", trim["id"])
    data.save_extra_symbol("XYZ", "Xyz Inc", "Tech", "stock", "")
    data.save_extra_symbol("XYZ", "Xyz Inc", "Tech", "stock", "Software")
    assert data.extra_symbols()[0]["industry"] == "Software"
    data.remove_from_watchlist("MU")
    data.remove_position("TEAM")
    assert data.watchlist() == ["AAPL"] and data.positions() == []


def test_sqlite_fallback(sqlite_db):
    assert userdb.backend() == "sqlite"
    _exercise()


def test_import_from_stage_backups(sqlite_db, tmp_path):
    positions = {
        "symbols": ["TEAM", "TSLA"],
        "positions": [
            {"symbol": "TEAM", "entry_price": 223.32, "shares": 200, "entry_date": "2026-10-23", "trims": []},
            {"symbol": "TSLA", "entry_price": 375.48, "shares": 100, "entry_date": "2026-10-23",
             "trims": [{"id": 9, "shares": 10, "price": 380.0, "trimmed_at": "2026-10-23T15:00:00+00:00"}]},
        ],
    }
    watchlist = {"symbols": ["SNDK", "AAPL", "QQQ"], "rows": [{"symbol": "ZZZQ", "name": "Off list", "sector": "X", "kind": "stock"}]}
    (tmp_path / "p.json").write_text(json.dumps(positions))
    (tmp_path / "w.json").write_text(json.dumps(watchlist))
    assert userdb_import.main(["--positions", str(tmp_path / "p.json"), "--watchlist", str(tmp_path / "w.json")]) == 0
    assert data.watchlist() == ["SNDK", "AAPL", "QQQ"]  # order kept
    assert [p["symbol"] for p in data.positions()] == ["TEAM", "TSLA"]
    assert data.trims_by_symbol()["TSLA"][0]["trimmed_at"] == "2026-10-23T15:00:00+00:00"
    assert [e["symbol"] for e in data.extra_symbols()] == ["ZZZQ"]
    with pytest.raises(SystemExit):  # refuses to write over existing rows
        userdb_import.main(["--positions", str(tmp_path / "p.json"), "--watchlist", str(tmp_path / "w.json")])
    assert userdb_import.main(["--positions", str(tmp_path / "p.json"), "--watchlist", str(tmp_path / "w.json"), "--replace"]) == 0
    assert data.watchlist() == ["SNDK", "AAPL", "QQQ"]


PG_URL = os.environ.get("TEST_DATABASE_URL", "").strip()


@pytest.mark.skipif(not PG_URL, reason="TEST_DATABASE_URL not set")
def test_postgres_path(monkeypatch, tmp_path):
    schema = "test_" + uuid.uuid4().hex[:10]
    monkeypatch.setenv("DATABASE_URL", PG_URL)
    monkeypatch.setenv("STRAT_PG_SCHEMA", schema)
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "cache.sqlite3")
    userdb.close()
    try:
        assert userdb.backend() == "postgres"
        _exercise()
        from datetime import datetime, timedelta, timezone

        from strat.alerts import Context, simulate

        t0 = datetime(2026, 10, 23, 13, 30, tzinfo=timezone.utc)
        found = simulate("AAA", "2026-10-23", [{"t": t0, "o": 100, "h": 101, "l": 99.9, "c": 100.9, "v": 1}], Context(warm_closes=[100.0] * 60))
        saved = alerts_store.save_session("2026-10-23", found, now=t0 + timedelta(minutes=6))
        assert len(saved["inserted"]) == 1
        assert alerts_store.list_alerts()[0]["top"] is True
        alerts_store.save_settings({"top_names": 5})
        assert alerts_store.load_settings().top_names == 5
        # A dropped connection is reopened on the next call.
        userdb._pg_conn.close()
        assert data.watchlist() == ["AAPL"]
        assert not (tmp_path / "cache.sqlite3").exists()  # nothing went to SQLite
    finally:
        with userdb.connect() as conn:
            conn.execute(f'DROP SCHEMA "{schema}" CASCADE')
        userdb.close()
        userdb._pg_ready.discard(schema)
