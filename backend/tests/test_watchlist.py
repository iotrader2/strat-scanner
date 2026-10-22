import pandas as pd
import pytest
from fastapi.testclient import TestClient

from strat import api, config, data, earnings
from strat.universe import Member

UNIVERSE = [
    Member("AAPL", "Apple", "Information Technology", "stock", "SP500"),
    Member("TDY", "Teledyne", "Industrials", "stock", "SP500"),
    Member("BRK-B", "Berkshire Hathaway", "Financials", "stock", "SP500"),
    Member("XLE", "Energy Select", "Energy", "etf", ""),
]
LEADER = {"rs": 0.95, "leadership": {"breakdown": "none"}}
SCAN = [
    {"symbol": "AAPL", "kind": "stock", "has_setup": True, "setup": "Inside week", "score": 80.0, "price": 250.5, **LEADER},
    {"symbol": "TDY", "kind": "stock", "has_setup": False, "setup": None, "score": 40.0, "price": 619.0, **LEADER},
]


def _bars(n=300, start=20.0):
    idx = pd.bdate_range("2025-06-02", periods=n)
    close = pd.Series([start + (i % 9) * 0.5 + i * 0.02 for i in range(n)], index=idx)
    return pd.DataFrame(
        {"Open": close - 0.3, "High": close + 0.8, "Low": close - 0.8, "Close": close, "Volume": 9_000_000.0}
    )


YAHOO = {"MRNA": (_bars(), {"name": "Moderna, Inc.", "sector": "Health Care", "kind": "stock", "industry": "Biotechnology"})}


def fake_lookup(symbol):
    if symbol == "FLAKY":
        raise data.LookupFailed("FLAKY: connection reset")
    if symbol not in YAHOO:
        raise data.SymbolNotFound(symbol)
    return YAHOO[symbol]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "cache.sqlite3")
    monkeypatch.setattr(api, "load_universe", lambda: UNIVERSE)
    monkeypatch.setattr(api.State, "scan", [dict(r) for r in SCAN])
    monkeypatch.setattr(api.State, "daily", {})
    monkeypatch.setattr(api, "_ensure_scan", lambda force=False: api.State.scan)
    monkeypatch.setattr(data, "lookup_symbol", fake_lookup)
    monkeypatch.setattr(data, "fetch_industry", lambda s: pytest.fail(f"unexpected industry lookup for {s}"))
    monkeypatch.setattr(earnings, "fetch_earnings", lambda s: {"symbol": s, "date": None, "date_end": None, "timing": None})
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


def test_class_shares_typed_with_a_dot_map_to_the_universe_symbol(client):
    assert client.post("/api/watchlist", json={"symbol": "brk.b"}).json()["symbols"] == ["BRK-B"]


def test_removing_an_unwatched_symbol_is_a_no_op(client):
    assert client.delete("/api/watchlist/AAPL").status_code == 200


def test_persists_in_sqlite_across_restarts(client, tmp_path):
    client.post("/api/watchlist", json={"symbol": "AAPL"})
    assert data.watchlist(tmp_path / "cache.sqlite3") == ["AAPL"]
    assert TestClient(api.app).get("/api/watchlist").json()["symbols"] == ["AAPL"]


# Symbols outside the S&P 500 / Nasdaq-100 / ETF universe


def test_adds_any_existing_ticker_with_a_computed_row(client):
    body = client.post("/api/watchlist", json={"symbol": " mrna "}).json()
    assert body["symbols"] == ["MRNA"] and body["missing"] == []
    (row,) = body["rows"]
    assert row["symbol"] == "MRNA" and row["name"] == "Moderna, Inc." and row["sector"] == "Health Care"
    assert row["in_universe"] is False
    assert 0 <= row["score"] <= 100 and row["score_breakdown"]
    assert set(row["tf"]) == {"M", "W", "D"} and all(row["tf"].values())
    assert {"trigger", "setup", "has_setup", "reason"} <= set(row)
    assert data.load_daily("MRNA").shape[0] == 300


def test_unknown_tickers_are_rejected_with_404_and_not_saved(client):
    res = client.post("/api/watchlist", json={"symbol": "ZZZZQX"})
    assert res.status_code == 404 and "not found" in res.json()["detail"]
    assert client.get("/api/watchlist").json()["symbols"] == []
    assert data.extra_symbols() == []


def test_malformed_symbols_are_rejected_without_a_lookup(client, monkeypatch):
    monkeypatch.setattr(data, "lookup_symbol", lambda s: pytest.fail("should not look up"))
    for bad in ["", "AA PL", "$$$", "A" * 20]:
        assert client.post("/api/watchlist", json={"symbol": bad}).status_code == 404


def test_lookup_failures_are_not_reported_as_missing_symbols(client):
    res = client.post("/api/watchlist", json={"symbol": "FLAKY"})
    assert res.status_code == 502
    assert client.get("/api/watchlist").json()["symbols"] == []


def test_off_universe_detail_page_and_charts_work(client):
    client.post("/api/watchlist", json={"symbol": "MRNA"})
    body = client.get("/api/symbol/MRNA").json()
    assert body["row"]["symbol"] == "MRNA"
    assert all(len(body["charts"][tf]) > 0 for tf in "MWD")


def test_off_universe_symbols_are_refreshed_and_scanned_only_while_watched(client, monkeypatch):
    client.post("/api/watchlist", json={"symbol": "MRNA"})
    assert "MRNA" in [m.symbol for m in api._universe()]

    refreshed = []
    monkeypatch.setattr(data, "refresh", lambda symbols, **kw: refreshed.extend(symbols))
    api._run_refresh(False)
    assert "MRNA" in refreshed and "AAPL" in refreshed

    client.delete("/api/watchlist/MRNA")
    assert "MRNA" not in [m.symbol for m in api._universe()]
    assert all(r["symbol"] != "MRNA" for r in api.State.scan)
    assert client.get("/api/symbol/MRNA").status_code == 200


def test_off_universe_rows_reach_the_scanner_only_through_its_filters(client):
    api.State.scan.append(
        {"symbol": "PENNY", "kind": "stock", "has_setup": True, "price": 4.0, "avg_dollar_volume": 2e6, "score": 75.0, **LEADER}
    )
    api.State.scan.append(
        {"symbol": "NOSETUP", "kind": "stock", "has_setup": False, "price": 50.0, "avg_dollar_volume": 9e8, "score": 75.0, **LEADER}
    )
    api.State.scan.append(
        {"symbol": "LAGGARD", "kind": "stock", "has_setup": True, "price": 50.0, "avg_dollar_volume": 9e8, "score": 80.0,
         "rs": 0.4, "leadership": {"breakdown": "none"}}
    )
    api.State.scan.append(
        {"symbol": "BROKEN", "kind": "stock", "has_setup": True, "price": 50.0, "avg_dollar_volume": 9e8, "score": 60.0,
         "rs": 0.97, "leadership": {"breakdown": "broken"}}
    )
    for r in api.State.scan[:2]:
        r.update(price=100.0, avg_dollar_volume=1e9, kind="stock")
    default = [r["symbol"] for r in client.get("/api/scan").json()["rows"]]
    loose = [r["symbol"] for r in client.get("/api/scan?min_price=1&min_dollar_volume=1000000").json()["rows"]]
    assert "PENNY" not in default and "PENNY" in loose
    assert "NOSETUP" in loose  # a leader needs no weekly setup
    assert "LAGGARD" not in default and "BROKEN" not in default
    everyone = [r["symbol"] for r in client.get("/api/scan?leaders_only=false").json()["rows"]]
    assert {"LAGGARD", "BROKEN"} <= set(everyone)
    loose_rs = [r["symbol"] for r in client.get("/api/scan?min_rs=0.3").json()["rows"]]
    assert "LAGGARD" in loose_rs and "BROKEN" not in loose_rs


def test_leaders_scan_needs_a_score_strictly_above_70(client):
    for r in api.State.scan:
        r.update(price=100.0, avg_dollar_volume=1e9, kind="stock")
    for symbol, score in (("AT70", 70.0), ("OVER70", 70.1)):
        api.State.scan.append(
            {"symbol": symbol, "kind": "stock", "has_setup": False, "price": 50.0, "avg_dollar_volume": 9e8, "score": score, **LEADER}
        )
    leaders = [r["symbol"] for r in client.get("/api/scan").json()["rows"]]
    assert "OVER70" in leaders and "AT70" not in leaders
    everyone = [r["symbol"] for r in client.get("/api/scan?leaders_only=false").json()["rows"]]
    assert {"AT70", "OVER70"} <= set(everyone)
    assert client.get("/api/config").json()["leaders_min_score"] == 70.0


def test_status_counts_only_symbols_in_the_current_universe(client):
    client.post("/api/watchlist", json={"symbol": "MRNA"})
    assert client.get("/api/status").json()["universe_size"] == len(UNIVERSE) + 1
    client.delete("/api/watchlist/MRNA")
    status = client.get("/api/status").json()
    assert status["universe_size"] == len(UNIVERSE)
    assert status["symbols_cached"] <= status["universe_size"]
