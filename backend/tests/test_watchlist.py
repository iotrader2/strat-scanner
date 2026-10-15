import pytest
from fastapi.testclient import TestClient

from strat import api, config, data
from strat.universe import Member

UNIVERSE = [
    Member("AAPL", "Apple", "Information Technology", "stock", "SP500"),
    Member("TDY", "Teledyne", "Industrials", "stock", "SP500"),
    Member("XLE", "Energy Select", "Energy", "etf", ""),
]
SCAN = [
    {"symbol": "AAPL", "has_setup": True, "setup": "Inside week", "score": 80.0},
    {"symbol": "TDY", "has_setup": False, "setup": None, "score": 40.0},
]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "cache.sqlite3")
    monkeypatch.setattr(api, "_universe", lambda: UNIVERSE)
    monkeypatch.setattr(api, "_ensure_scan", lambda force=False: SCAN)
    return TestClient(api.app)


def test_starts_empty(client):
    assert client.get("/api/watchlist").json() == {"symbols": [], "rows": [], "missing": []}


def test_add_remove_round_trip(client):
    client.post("/api/watchlist", json={"symbol": "aapl"})
    body = client.post("/api/watchlist", json={"symbol": "TDY"}).json()
    assert body["symbols"] == ["AAPL", "TDY"]
    body = client.delete("/api/watchlist/AAPL").json()
    assert body["symbols"] == ["TDY"]
    assert client.get("/api/watchlist").json()["symbols"] == ["TDY"]


def test_adding_twice_keeps_one_entry_and_original_order(client):
    client.post("/api/watchlist", json={"symbol": "TDY"})
    client.post("/api/watchlist", json={"symbol": "AAPL"})
    client.post("/api/watchlist", json={"symbol": "TDY"})
    assert client.get("/api/watchlist").json()["symbols"] == ["TDY", "AAPL"]


def test_keeps_names_without_an_active_setup(client):
    client.post("/api/watchlist", json={"symbol": "TDY"})
    rows = client.get("/api/watchlist").json()["rows"]
    assert [r["symbol"] for r in rows] == ["TDY"]
    assert rows[0]["has_setup"] is False and rows[0]["setup"] is None


def test_reports_watched_names_with_no_cached_data(client):
    client.post("/api/watchlist", json={"symbol": "XLE"})
    body = client.get("/api/watchlist").json()
    assert body["rows"] == [] and body["missing"] == ["XLE"]


def test_rejects_symbols_outside_the_universe(client):
    assert client.post("/api/watchlist", json={"symbol": "NOPE"}).status_code == 404
    assert client.get("/api/watchlist").json()["symbols"] == []


def test_removing_an_unwatched_symbol_is_a_no_op(client):
    assert client.delete("/api/watchlist/AAPL").status_code == 200


def test_persists_in_sqlite_across_restarts(client, tmp_path):
    client.post("/api/watchlist", json={"symbol": "AAPL"})
    assert data.watchlist(tmp_path / "cache.sqlite3") == ["AAPL"]
    assert TestClient(api.app).get("/api/watchlist").json()["symbols"] == ["AAPL"]
