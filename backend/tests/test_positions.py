from fastapi.testclient import TestClient

from strat import api, data, earnings
from test_watchlist import client  # noqa: F401  (shared fixture: temp SQLite, fake universe, stubbed yfinance)


def _positions(c):
    return c.get("/api/positions").json()["positions"]


def test_starts_empty(client):
    assert client.get("/api/positions").json() == {"symbols": [], "positions": [], "intraday": {}}


def test_move_from_watchlist_defaults_to_last_price_and_today(client, monkeypatch):
    monkeypatch.setattr(earnings, "today_et", lambda: __import__("datetime").date(2026, 10, 15))
    client.post("/api/watchlist", json={"symbol": "AAPL"})
    body = client.post("/api/positions", json={"symbol": "AAPL"}).json()
    (pos,) = body["positions"]
    assert {k: pos[k] for k in ("symbol", "entry_price", "shares", "entry_date")} == {
        "symbol": "AAPL", "entry_price": 250.5, "shares": None, "entry_date": "2026-10-15"}
    assert pos["row"]["symbol"] == "AAPL" and "earnings" in pos["row"]
    assert client.get("/api/watchlist").json()["symbols"] == []


def test_explicit_entry_shares_and_date(client):
    client.post("/api/positions", json={"symbol": "tdy", "entry_price": 600.25, "shares": 15, "entry_date": "2026-09-30"})
    (pos,) = _positions(client)
    assert (pos["symbol"], pos["entry_price"], pos["shares"], pos["entry_date"]) == ("TDY", 600.25, 15, "2026-09-30")


def test_any_ticker_can_be_added_directly(client):
    body = client.post("/api/positions", json={"symbol": "MRNA", "entry_price": 21.5}).json()
    (pos,) = body["positions"]
    assert pos["row"]["in_universe"] is False and pos["row"]["name"] == "Moderna, Inc."
    assert "MRNA" in [m.symbol for m in api._universe()]


def test_off_universe_default_entry_is_the_last_close(client):
    (pos,) = client.post("/api/positions", json={"symbol": "MRNA"}).json()["positions"]
    assert pos["entry_price"] == round(float(data.load_daily("MRNA").close.iloc[-1]), 2)


def test_rejects_bad_input(client):
    assert client.post("/api/positions", json={"symbol": "ZZZZQX"}).status_code == 404
    assert client.post("/api/positions", json={"symbol": "AAPL", "entry_price": 0}).status_code == 422
    assert client.post("/api/positions", json={"symbol": "AAPL", "shares": -5}).status_code == 422
    assert client.post("/api/positions", json={"symbol": "AAPL", "entry_date": "2999-01-01"}).status_code == 422
    assert _positions(client) == []


def test_duplicate_positions_conflict(client):
    client.post("/api/positions", json={"symbol": "AAPL"})
    assert client.post("/api/positions", json={"symbol": "AAPL"}).status_code == 409


def test_edit_keeps_order(client):
    client.post("/api/positions", json={"symbol": "TDY", "entry_price": 600})
    client.post("/api/positions", json={"symbol": "AAPL", "entry_price": 240})
    res = client.put("/api/positions/TDY", json={"entry_price": 605.5, "shares": 10, "entry_date": "2026-10-01"})
    assert res.status_code == 200
    assert [(p["symbol"], p["entry_price"], p["shares"]) for p in res.json()["positions"]] == [
        ("TDY", 605.5, 10), ("AAPL", 240, None)]
    assert client.put("/api/positions/NOPE", json={"entry_price": 1, "entry_date": "2026-10-01"}).status_code == 404


def test_close_removes_the_position(client):
    client.post("/api/positions", json={"symbol": "AAPL"})
    assert client.delete("/api/positions/AAPL").json()["positions"] == []


def test_move_back_to_watchlist(client):
    client.post("/api/positions", json={"symbol": "AAPL"})
    assert client.post("/api/positions/AAPL/watchlist").json()["positions"] == []
    assert client.get("/api/watchlist").json()["symbols"] == ["AAPL"]
    assert client.post("/api/positions/AAPL/watchlist").status_code == 404


def test_off_universe_symbol_stays_scanned_while_watched_or_held(client):
    client.post("/api/watchlist", json={"symbol": "MRNA"})
    client.post("/api/positions", json={"symbol": "MRNA"})
    assert "MRNA" in [m.symbol for m in api._universe()]
    assert any(r["symbol"] == "MRNA" for r in api.State.scan)
    client.post("/api/positions/MRNA/watchlist")
    assert any(r["symbol"] == "MRNA" for r in api.State.scan)
    client.delete("/api/watchlist/MRNA")
    assert "MRNA" not in [m.symbol for m in api._universe()]
    assert all(r["symbol"] != "MRNA" for r in api.State.scan)


def test_positions_survive_restarts(client, tmp_path):
    client.post("/api/positions", json={"symbol": "AAPL", "entry_price": 240, "shares": 3})
    assert data.positions(tmp_path / "cache.sqlite3")[0]["shares"] == 3
    assert TestClient(api.app).get("/api/positions").json()["symbols"] == ["AAPL"]


# --- short positions ---------------------------------------------------------------------------------------------


def test_short_position_is_stored_and_defaults_to_long(client):
    client.post("/api/positions", json={"symbol": "TDY", "entry_price": 600, "shares": 10, "entry_date": "2026-09-30"})
    client.post(
        "/api/positions", json={"symbol": "AAPL", "entry_price": 250, "shares": 20, "entry_date": "2026-09-30", "side": "short"}
    )
    sides = {p["symbol"]: p["side"] for p in _positions(client)}
    assert sides == {"TDY": "long", "AAPL": "short"}
    assert client.post("/api/positions", json={"symbol": "MSFT", "side": "sideways"}).status_code == 422


def test_short_trims_are_buy_to_cover(client):
    client.post(
        "/api/positions", json={"symbol": "AAPL", "entry_price": 250, "shares": 20, "entry_date": "2026-09-30", "side": "short"}
    )
    client.post("/api/positions/AAPL/trims", json={"shares": 5, "price": 230})  # covered 5 at 230: +$100
    (pos,) = _positions(client)
    assert pos["realized_pnl"] == 100
    assert pos["remaining_shares"] == 15
    assert pos["break_even"] == (20 * 250 - 5 * 230) / 15  # ~256.67: the cover profit raises the short's break-even
    res = client.post("/api/positions/AAPL/trims", json={"shares": 15, "price": 230})
    assert res.status_code == 422 and "Covering all" in res.json()["detail"]


def test_edit_keeps_side_unless_given_and_refuses_a_flip_after_trims(client):
    client.post(
        "/api/positions", json={"symbol": "AAPL", "entry_price": 250, "shares": 20, "entry_date": "2026-09-30", "side": "short"}
    )
    client.put("/api/positions/AAPL", json={"entry_price": 251, "shares": 20, "entry_date": "2026-09-30"})
    assert _positions(client)[0]["side"] == "short"
    client.put("/api/positions/AAPL", json={"entry_price": 251, "shares": 20, "entry_date": "2026-09-30", "side": "long"})
    assert _positions(client)[0]["side"] == "long"
    client.post("/api/positions/AAPL/trims", json={"shares": 5, "price": 260})
    res = client.put("/api/positions/AAPL", json={"entry_price": 251, "shares": 20, "entry_date": "2026-09-30", "side": "short"})
    assert res.status_code == 422


def test_old_cache_without_side_is_migrated_to_long(tmp_path):
    import sqlite3

    from strat import userdb

    path = tmp_path / "old.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE positions (symbol TEXT PRIMARY KEY, entry_price REAL NOT NULL, shares REAL, "
        "entry_date TEXT NOT NULL, added_at TEXT NOT NULL)"
    )
    conn.execute("INSERT INTO positions VALUES ('AAPL', 250, 10, '2026-09-30', '2026-09-30T00:00:00')")
    conn.commit()
    conn.close()
    userdb.bump()
    assert data.positions(db_path=path) == [
        {"symbol": "AAPL", "entry_price": 250, "shares": 10, "entry_date": "2026-09-30", "side": "long"}
    ]
