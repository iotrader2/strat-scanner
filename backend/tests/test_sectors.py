import pandas as pd
import pytest

from strat.scanner import sector_entries

ETFS = [
    ("XLK", "Technology", "Information Technology", "spdr"),
    ("XLF", "Financials", "Financials", "spdr"),
    ("XLV", "Health Care", "Health Care", "spdr"),
    ("XLE", "Energy", "Energy", "spdr"),
    ("SMH", "Semis", "Information Technology", "industry"),
]
SCORES = {"XLK": 31.0, "XLF": 55.0, "XLV": 76.0, "XLE": 55.0, "SMH": 90.0}


def _daily(seed: float) -> pd.DataFrame:
    idx = pd.bdate_range("2025-01-01", periods=300)
    base = pd.Series(range(300), index=idx, dtype=float) * 0.1 + seed
    return pd.DataFrame(
        {"open": base, "high": base + 1, "low": base - 1, "close": base + 0.5, "volume": 1e6}, index=idx
    )


@pytest.fixture
def inputs():
    rows = {s: {"symbol": s, "score": sc} for s, sc in SCORES.items()}
    daily = {s: _daily(50 + i) for i, s in enumerate(SCORES)}
    return rows, daily


@pytest.mark.parametrize("tf", ["M", "W", "D"])
def test_sector_cards_sorted_by_score_descending(inputs, tf):
    rows, daily = inputs
    entries = sector_entries(ETFS, rows, daily, tf, 30)
    # ETFS lists XLK (31) first; the strongest must come first regardless of list order.
    assert [e["symbol"] for e in entries] == ["SMH", "XLV", "XLE", "XLF", "XLK"]
    scores = [e["row"]["score"] for e in entries]
    assert scores == sorted(scores, reverse=True)
    assert all(e["candles"] for e in entries)


def test_sorting_within_group_keeps_strongest_first(inputs):
    rows, daily = inputs
    spdr = [e["symbol"] for e in sector_entries(ETFS, rows, daily, "W", 30) if e["group"] == "spdr"]
    assert spdr[0] == "XLV" and spdr[-1] == "XLK"


def test_missing_data_is_skipped(inputs):
    rows, daily = inputs
    del daily["XLV"]
    assert "XLV" not in [e["symbol"] for e in sector_entries(ETFS, rows, daily, "D", 30)]


def test_universe_benchmarks_are_qqq_spy_iwm_only():
    from strat.universe import ETFS, MARKET_ETFS, SECTOR_ETFS, load_universe

    assert [e[0] for e in MARKET_ETFS] == ["QQQ", "SPY", "IWM"]
    assert all(e[3] != "benchmark" for e in SECTOR_ETFS)
    assert len(SECTOR_ETFS) == 24 and len(ETFS) == 27
    symbols = {m.symbol for m in load_universe()}
    assert "DIA" not in symbols and {"QQQ", "SPY", "IWM"} <= symbols


def test_etf_cards_keep_the_given_order(inputs):
    from strat.scanner import etf_cards

    rows, daily = inputs
    cards = etf_cards([("XLK", "T", "IT", "spdr"), ("SMH", "S", "IT", "industry"), ("ZZZ", "none", "-", "spdr")], rows, daily, "W", 20)
    assert [c["symbol"] for c in cards] == ["XLK", "SMH"]
    assert all(len(c["candles"]) == 20 for c in cards)


@pytest.fixture
def api_client(monkeypatch):
    from fastapi.testclient import TestClient

    from strat import api

    symbols = ["XLK", "XBI", "QQQ", "SPY", "IWM", "DIA"]
    scores = {"XLK": 40.0, "XBI": 70.0, "QQQ": 20.0, "SPY": 90.0, "IWM": 55.0, "DIA": 99.0}
    monkeypatch.setattr(api.State, "scan", [{"symbol": s, "score": scores[s]} for s in symbols])
    monkeypatch.setattr(api.State, "daily", {s: _daily(100 + i) for i, s in enumerate(symbols)})
    monkeypatch.setattr(api, "_ensure_scan", lambda force=False: api.State.scan)
    return TestClient(api.app)


def test_sectors_endpoint_has_no_benchmarks(api_client):
    etfs = api_client.get("/api/sectors?tf=W&bars=30").json()["etfs"]
    assert [e["symbol"] for e in etfs] == ["XBI", "XLK"]
    assert all(e["group"] != "benchmark" for e in etfs)


@pytest.mark.parametrize("tf", ["M", "W", "D"])
def test_market_endpoint_lists_qqq_spy_iwm_in_order(api_client, tf):
    body = api_client.get(f"/api/market?tf={tf}&bars=30").json()
    assert body["tf"] == tf
    assert [e["symbol"] for e in body["etfs"]] == ["QQQ", "SPY", "IWM"]
    assert all(e["group"] == "benchmark" and e["candles"] and e["row"]["score"] is not None for e in body["etfs"])


def test_market_endpoint_validates_timeframe(api_client):
    assert api_client.get("/api/market?tf=Y").status_code == 422
