import sqlite3

import pytest
from fastapi.testclient import TestClient

from strat import api, config, data, trims
from test_watchlist import client  # noqa: F401  (shared fixture: temp SQLite, fake universe, stubbed yfinance)


def _open(c, symbol="AAPL", price=100, shares=100, entry_date="2026-10-01"):
    res = c.post("/api/positions", json={"symbol": symbol, "entry_price": price, "shares": shares, "entry_date": entry_date})
    assert res.status_code == 200
    return res


def _pos(c, symbol="AAPL"):
    return next(p for p in c.get("/api/positions").json()["positions"] if p["symbol"] == symbol)


def test_break_even_with_no_trims_is_the_buy_price():
    assert trims.break_even(100, 50, []) == 50
    assert trims.realized_pnl(50, []) == 0
    assert trims.remaining_shares(100, []) == 100


def test_single_trim_reduces_cost_basis_and_books_realized_pnl():
    sold = [{"shares": 25, "price": 60}]
    # (100 * 50 - 25 * 60) / 75 = 46.666...
    assert trims.break_even(100, 50, sold) == pytest.approx(3500 / 75)
    assert trims.realized_pnl(50, sold) == 250
    assert trims.remaining_shares(100, sold) == 75


def test_multiple_trims_stack():
    sold = [{"shares": 20, "price": 12}, {"shares": 30, "price": 15}]
    # (100 * 10 - 20 * 12 - 30 * 15) / 50 = 6.2
    assert trims.break_even(100, 10, sold) == pytest.approx(6.2)
    assert trims.realized_pnl(10, sold) == pytest.approx(190)
    assert trims.remaining_shares(100, sold) == 50


def test_free_trade_can_be_zero_or_negative():
    covered = [{"shares": 50, "price": 20}]
    assert trims.break_even(100, 10, covered) == 0
    assert trims.realized_pnl(10, covered) == 500
    credit = [{"shares": 40, "price": 30}]
    # (100 * 10 - 40 * 30) / 60 = -200 / 60
    assert trims.break_even(100, 10, credit) == pytest.approx(-200 / 60)
    assert trims.realized_pnl(10, credit) == 800


def test_trim_endpoint_single_and_multiple(client):
    _open(client, price=50, shares=100)
    first = client.post("/api/positions/AAPL/trims", json={"shares": 25, "price": 60})
    assert first.status_code == 200
    pos = first.json()["positions"][0]
    assert pos["shares"] == 100
    assert pos["remaining_shares"] == 75
    assert pos["break_even"] == pytest.approx(3500 / 75)
    assert pos["realized_pnl"] == 250
    assert len(pos["trims"]) == 1
    assert pos["trims"][0]["shares"] == 25 and pos["trims"][0]["price"] == 60
    assert pos["trims"][0]["trimmed_at"]

    second = client.post("/api/positions/AAPL/trims", json={"shares": 25, "price": 80})
    pos = second.json()["positions"][0]
    assert pos["remaining_shares"] == 50
    # (100 * 50 - 25 * 60 - 25 * 80) / 50 = 30
    assert pos["break_even"] == pytest.approx(30)
    assert pos["realized_pnl"] == pytest.approx(25 * (60 - 50) + 25 * (80 - 50))
    assert [t["price"] for t in pos["trims"]] == [60, 80]


def test_trim_validation(client):
    _open(client, shares=10)
    assert client.post("/api/positions/AAPL/trims", json={"shares": 0, "price": 5}).status_code == 422
    assert client.post("/api/positions/AAPL/trims", json={"shares": 1, "price": 0}).status_code == 422
    assert client.post("/api/positions/AAPL/trims", json={"shares": -1, "price": 5}).status_code == 422
    full = client.post("/api/positions/AAPL/trims", json={"shares": 10, "price": 5})
    assert full.status_code == 422 and "Close position" in full.json()["detail"]
    over = client.post("/api/positions/AAPL/trims", json={"shares": 11, "price": 5})
    assert over.status_code == 422 and "Close position" in over.json()["detail"]
    assert client.post("/api/positions/NOPE/trims", json={"shares": 1, "price": 5}).status_code == 404
    assert _pos(client)["trims"] == [] and _pos(client)["remaining_shares"] == 10

    client.post("/api/positions", json={"symbol": "TDY", "entry_price": 20, "entry_date": "2026-10-01"})
    missing = client.post("/api/positions/TDY/trims", json={"shares": 1, "price": 21})
    assert missing.status_code == 422 and "share count" in missing.json()["detail"]


def test_partial_then_the_rest_is_refused(client):
    _open(client, shares=10)
    assert client.post("/api/positions/AAPL/trims", json={"shares": 4, "price": 12}).status_code == 200
    rest = client.post("/api/positions/AAPL/trims", json={"shares": 6, "price": 13})
    assert rest.status_code == 422 and "Close position" in rest.json()["detail"]
    assert _pos(client)["remaining_shares"] == 6


def test_undo_restores_the_basis(client):
    _open(client, price=10, shares=100)
    client.post("/api/positions/AAPL/trims", json={"shares": 20, "price": 12})
    body = client.post("/api/positions/AAPL/trims", json={"shares": 30, "price": 15}).json()
    first_id, second_id = (t["id"] for t in body["positions"][0]["trims"])
    undone = client.delete(f"/api/positions/AAPL/trims/{first_id}")
    assert undone.status_code == 200
    pos = undone.json()["positions"][0]
    assert [t["id"] for t in pos["trims"]] == [second_id]
    assert pos["remaining_shares"] == 70
    assert pos["break_even"] == pytest.approx((100 * 10 - 30 * 15) / 70)
    assert pos["realized_pnl"] == pytest.approx(30 * (15 - 10))
    assert client.delete(f"/api/positions/AAPL/trims/{first_id}").status_code == 404
    assert client.delete("/api/positions/NOPE/trims/1").status_code == 404


def test_edit_cannot_shrink_below_trimmed_shares_and_recomputes_basis(client):
    _open(client, price=10, shares=100)
    client.post("/api/positions/AAPL/trims", json={"shares": 40, "price": 30})
    shrunk = client.put("/api/positions/AAPL", json={"entry_price": 10, "shares": 40, "entry_date": "2026-10-01"})
    assert shrunk.status_code == 422
    cleared = client.put("/api/positions/AAPL", json={"entry_price": 10, "shares": None, "entry_date": "2026-10-01"})
    assert cleared.status_code == 422
    edited = client.put("/api/positions/AAPL", json={"entry_price": 8, "shares": 100, "entry_date": "2026-10-01"})
    pos = edited.json()["positions"][0]
    assert pos["entry_price"] == 8
    assert pos["break_even"] == pytest.approx((100 * 8 - 40 * 30) / 60)
    assert pos["realized_pnl"] == pytest.approx(40 * (30 - 8))


def test_close_and_move_drop_trims(client, tmp_path):
    _open(client)
    client.post("/api/positions/AAPL/trims", json={"shares": 10, "price": 110})
    client.delete("/api/positions/AAPL")
    assert data.trims_by_symbol(tmp_path / "cache.sqlite3") == {}

    _open(client, symbol="TDY")
    client.post("/api/positions/TDY/trims", json={"shares": 10, "price": 110})
    client.post("/api/positions/TDY/watchlist")
    assert data.trims_by_symbol(tmp_path / "cache.sqlite3") == {}


def test_trims_survive_restart_and_an_old_database_gains_the_table(client, tmp_path):
    _open(client, price=50, shares=100)
    client.post("/api/positions/AAPL/trims", json={"shares": 25, "price": 60})
    client.post("/api/positions/AAPL/trims", json={"shares": 10, "price": 70})
    path = tmp_path / "cache.sqlite3"
    stored = data.trims_by_symbol(path)["AAPL"]
    assert [(t["shares"], t["price"]) for t in stored] == [(25, 60), (10, 70)]
    again = TestClient(api.app).get("/api/positions").json()["positions"][0]
    assert again["remaining_shares"] == 65
    assert again["break_even"] == pytest.approx((100 * 50 - 25 * 60 - 10 * 70) / 65)
    assert len(again["trims"]) == 2

    old = tmp_path / "old.sqlite3"
    conn = sqlite3.connect(old)
    conn.execute(
        "CREATE TABLE positions (symbol TEXT PRIMARY KEY, entry_price REAL NOT NULL, "
        "shares REAL, entry_date TEXT NOT NULL, added_at TEXT NOT NULL)"
    )
    conn.execute("INSERT INTO positions VALUES ('MSFT', 100, 10, '2026-09-01', '2026-09-01T00:00:00')")
    conn.commit()
    conn.close()
    assert data.positions(old)[0]["symbol"] == "MSFT"
    data.add_trim("MSFT", 2, 120, old)
    assert data.trims_by_symbol(old)["MSFT"][0]["price"] == 120
    # Re-open the same file: the trim is still there after a fresh connection.
    assert data.trims_by_symbol(old)["MSFT"][0]["shares"] == 2


def test_trim_publishes_a_small_positions_message(client, monkeypatch):
    published = []
    monkeypatch.setattr(api.hub, "publish", published.append)
    _open(client, shares=10)
    client.post("/api/positions/AAPL/trims", json={"shares": 2, "price": 11})
    trim_id = _pos(client)["trims"][0]["id"]
    client.delete(f"/api/positions/AAPL/trims/{trim_id}")
    assert published == [{"type": "positions"}, {"type": "positions"}]
    assert all(set(message) == {"type"} for message in published)
