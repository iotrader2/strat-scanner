import pandas as pd
import pytest
from fastapi.testclient import TestClient

from strat import api
from strat.scanner import etf_cards, scan_all, theme_cards
from strat.themes import parse_themes
from strat.universe import ETFS, MARKET_ETFS, SECTOR_ETFS, Member, load_universe

MAP = parse_themes(
    {
        "version": 1,
        "themes": {
            "fast": {"name": "Fast movers", "description": "Rising fast.", "members": "F1 F2 F3", "also": "S1"},
            "slow": {"name": "Slow movers", "description": "Drifting lower.", "members": "S1 S2 S3"},
            "ghost": {"name": "No data", "members": "G1 G2 G3"},
        },
    }
)


def _daily(drift, n=200):
    idx = pd.bdate_range(end="2026-10-15", periods=n)
    close = pd.Series([100 + i * drift + (i % 5) * 0.4 for i in range(n)], index=idx, dtype=float)
    return pd.DataFrame({"open": close - 0.3, "high": close + 1, "low": close - 1, "close": close, "volume": 2_000_000.0})


SYMBOLS = ["F1", "F2", "F3", "S1", "S2", "S3"]
MEMBERS = [Member(s, s, "Information Technology", "stock", "SP500") for s in SYMBOLS] + [
    Member(sym, name, sector, "etf", group) for sym, name, sector, group in MARKET_ETFS
]


@pytest.fixture
def history():
    out = {s: _daily(0.4 if s.startswith("F") else -0.1) for s in SYMBOLS}
    out.update({sym: _daily(0.2 + i * 0.05) for i, (sym, *_rest) in enumerate(MARKET_ETFS)})
    return out


@pytest.fixture
def result(history):
    return scan_all(MEMBERS, history, MAP)


@pytest.mark.parametrize("tf", ["M", "W", "D"])
def test_theme_cards_are_sorted_by_score_and_carry_candles(result, tf):
    rows = {r["symbol"]: r for r in result.rows}
    cards = theme_cards(result, rows, tf, 30)
    assert [c["id"] for c in cards] == ["fast", "slow"]  # "ghost" has no data
    assert [c["row"]["score"] for c in cards] == sorted((c["row"]["score"] for c in cards), reverse=True)
    assert all(0 < len(c["candles"]) <= 30 for c in cards)
    assert {"time", "open", "high", "low", "close", "volume", "strat", "hammer"} <= set(cards[0]["candles"][0])


def test_theme_card_members_and_secondary_chips(result):
    rows = {r["symbol"]: r for r in result.rows}
    fast, slow = theme_cards(result, rows, "W", 20)
    assert fast["name"] == "Fast movers" and fast["description"] == "Rising fast." and fast["count"] == 3
    assert {m["symbol"] for m in fast["members"]} == {"F1", "F2", "F3"}
    assert [m["symbol"] for m in fast["also"]] == ["S1"] and fast["also"][0]["also"] is True
    assert all(m["also"] is False for m in fast["members"])
    assert {"symbol", "name", "change_pct", "perf", "score", "mw_green", "has_setup", "also"} <= set(fast["members"][0])
    assert {m["symbol"] for m in slow["members"]} == {"S1", "S2", "S3"} and slow["also"] == []
    scores = [m["score"] for m in fast["members"]]
    assert scores == sorted(scores, reverse=True)


def test_theme_rows_have_performance_momentum_and_index_perf(result, history):
    rows = {r["symbol"]: r for r in result.rows}
    fast = next(c for c in theme_cards(result, rows, "W", 20) if c["id"] == "fast")["row"]
    assert set(fast["perf"]) == {"1m", "3m", "6m"} and all(v is not None for v in fast["perf"].values())
    assert fast["perf"]["1m"] > 0 > result.theme_rows["slow"]["perf"]["1m"]
    # Each member rises in a straight line, so the equal-weight index return equals the (identical) members' return.
    assert fast["perf"]["3m"] == pytest.approx(rows["F1"]["perf"]["3m"], abs=0.2)
    assert "momentum" in [c["key"] for c in fast["score_breakdown"]]


def test_rows_expose_one_three_and_six_month_performance(result):
    for row in result.rows:
        assert set(row["perf"]) == {"1m", "3m", "6m"}
    f1 = next(r for r in result.rows if r["symbol"] == "F1")
    assert f1["perf"]["6m"] > f1["perf"]["3m"] > f1["perf"]["1m"] > 0


def test_universe_benchmarks_are_qqq_spy_iwm_only():
    assert [e[0] for e in MARKET_ETFS] == ["QQQ", "SPY", "IWM"]
    assert all(e[3] != "benchmark" for e in SECTOR_ETFS)
    assert len(SECTOR_ETFS) == 24 and len(ETFS) == 27
    symbols = {m.symbol for m in load_universe()}
    assert "DIA" not in symbols and {"QQQ", "SPY", "IWM"} <= symbols


def test_etf_cards_keep_the_given_order(result, history):
    rows = {r["symbol"]: r for r in result.rows}
    cards = etf_cards([("SPY", "S", "-", "benchmark"), ("QQQ", "Q", "-", "benchmark"), ("ZZZ", "none", "-", "x")], rows, history, "W", 20)
    assert [c["symbol"] for c in cards] == ["SPY", "QQQ"]
    assert all(len(c["candles"]) == 20 and "perf" in c["row"] for c in cards)


@pytest.fixture
def api_client(monkeypatch, result, history):
    monkeypatch.setattr(api.State, "scan", result.rows)
    monkeypatch.setattr(api.State, "result", result)
    monkeypatch.setattr(api.State, "daily", history)
    monkeypatch.setattr(api.State, "theme_map", MAP)
    monkeypatch.setattr(api, "_ensure_scan", lambda force=False: api.State.scan)
    return TestClient(api.app)


def test_themes_endpoint(api_client):
    body = api_client.get("/api/themes?tf=W&bars=30").json()
    assert body["tf"] == "W"
    assert [t["id"] for t in body["themes"]] == ["fast", "slow"]
    assert all(t["row"]["kind"] == "theme" and t["candles"] for t in body["themes"])


def test_themes_endpoint_validates_timeframe(api_client):
    assert api_client.get("/api/themes?tf=Y").status_code == 422


def test_sectors_endpoint_is_gone(api_client):
    assert api_client.get("/api/sectors").status_code == 404


@pytest.mark.parametrize("tf", ["M", "W", "D"])
def test_market_endpoint_lists_qqq_spy_iwm_in_order(api_client, tf):
    body = api_client.get(f"/api/market?tf={tf}&bars=30").json()
    assert body["tf"] == tf
    assert [e["symbol"] for e in body["etfs"]] == ["QQQ", "SPY", "IWM"]
    assert all(e["group"] == "benchmark" and e["candles"] and e["row"]["perf"]["1m"] is not None for e in body["etfs"])
    assert body["trend"]["call"] == "on"
    assert [i["symbol"] for i in body["trend"]["indexes"]] == ["QQQ", "SPY", "IWM"]


def test_market_endpoint_validates_timeframe(api_client):
    assert api_client.get("/api/market?tf=Y").status_code == 422


def test_breadth_endpoint(api_client, monkeypatch):
    payload = {"nasi": None, "fear_greed": None, "issues": None}
    monkeypatch.setattr(api, "fetch_breadth", lambda: payload)
    assert api_client.get("/api/breadth").json() == payload


def test_config_lists_themes_for_the_scanner_filter(api_client):
    themes = api_client.get("/api/config").json()["themes"]
    assert themes == [
        {"id": "fast", "name": "Fast movers", "count": 4},  # count includes secondary members
        {"id": "ghost", "name": "No data", "count": 3},
        {"id": "slow", "name": "Slow movers", "count": 3},
    ]


def test_scan_rows_carry_theme_fields_and_exclude_theme_indexes(api_client):
    rows = api_client.get("/api/scan?min_price=0&min_dollar_volume=0").json()["rows"]
    assert all(r["kind"] in ("stock", "etf") for r in rows)
    for r in rows:
        assert {"perf", "theme", "theme_name", "secondary_themes", "theme_strength"} <= set(r)
