import sqlite3

import pandas as pd
import pytest

from strat import api, config, data
from strat.members import backfill_industries, extra_members
from strat.scanner import scan_all, sector_strengths
from strat.scoring import SECTOR_STRENGTH_POINTS, SectorStrength, sector_strength_points
from strat.universe import ETFS, Member, load_universe, normalize_industry, strength_etf

from test_watchlist import client  # noqa: F401  (shared fixture: temp SQLite, fake universe, stubbed yfinance)


def _daily(n=120, drift=0.1):
    idx = pd.bdate_range("2026-03-02", periods=n)
    close = pd.Series([100 + i * drift + (i % 5) * 0.4 for i in range(n)], index=idx, dtype=float)
    return pd.DataFrame(
        {"open": close - 0.3, "high": close + 1, "low": close - 1, "close": close, "volume": 2_000_000.0}
    )


def _strength(etf, score, rank=2, top="XLK", top_score=80.0):
    return SectorStrength(etf, etf, score, rank, 24, top, top_score)


class TestMapping:
    def test_industry_etf_wins_where_it_is_a_clear_fit(self):
        assert strength_etf("Health Care", "Biotechnology") == "XBI"
        assert strength_etf("Information Technology", "Semiconductors") == "SMH"
        assert strength_etf("Information Technology", "Systems Software") == "IGV"
        assert strength_etf("Financials", "Regional Banks") == "KRE"
        assert strength_etf("Energy", "Oil & Gas Exploration & Production") == "XOP"

    def test_everything_else_uses_the_spdr_sector_etf(self):
        assert strength_etf("Health Care", "Pharmaceuticals") == "XLV"
        assert strength_etf("Consumer Discretionary", "Broadline Retail") == "XLY"
        assert strength_etf("Information Technology", "Technology Hardware, Storage & Peripherals") == "XLK"
        assert strength_etf("Health Care") == "XLV"
        assert strength_etf("Other", "") == ""

    def test_yahoo_industry_names_map_too(self):
        assert normalize_industry("Software—Infrastructure") == "Software - Infrastructure"
        assert strength_etf("Information Technology", "Software—Infrastructure") == "IGV"
        assert strength_etf("Health Care", "Biotechnology") == "XBI"
        assert strength_etf("Financials", "Credit Services") == "XLF"

    def test_every_mapped_etf_is_on_the_sectors_page(self):
        from strat.universe import INDUSTRY_ETF

        industry = {sym for sym, _, _, group in ETFS if group == "industry"}
        assert set(INDUSTRY_ETF.values()) <= industry

    def test_etfs_have_no_strength_etf(self):
        assert Member("XBI", "SPDR S&P Biotech", "Health Care", "etf", "industry").strength_etf == ""

    def test_universe_snapshot_has_industries(self):
        stocks = [m for m in load_universe() if m.kind == "stock"]
        assert stocks and all(m.industry for m in stocks)
        by = {m.symbol: m for m in stocks}
        assert by["MRNA"].strength_etf == "XBI"
        assert by["NVDA"].strength_etf == "SMH"
        assert by["AAPL"].strength_etf == "XLK"


class TestPoints:
    def test_top_ranked_sector_gets_full_points(self):
        assert sector_strength_points(_strength("XLK", 80.0, rank=1)) == SECTOR_STRENGTH_POINTS == 15

    def test_points_scale_with_the_etf_score_relative_to_the_top(self):
        assert sector_strength_points(_strength("XLV", 40.0)) == pytest.approx(7.5)
        assert sector_strength_points(_strength("XLU", 20.0)) == pytest.approx(3.75)
        assert sector_strength_points(_strength("XLE", 0.0)) == 0

    def test_missing_or_degenerate_rankings_give_zero(self):
        assert sector_strength_points(None) == 0
        assert sector_strength_points(_strength("XLK", 0.0, top_score=0.0)) == 0

    def test_ranking_follows_the_sectors_page_without_benchmarks(self):
        rows = [
            {"symbol": "XBI", "score": 60.0},
            {"symbol": "XLK", "score": 75.0},
            {"symbol": "SPY", "score": 99.0},
            {"symbol": "XLV", "score": 60.0},
            {"symbol": "AAPL", "score": 100.0},
        ]
        s = sector_strengths(rows)
        assert list(s) == ["XLK", "XBI", "XLV"]
        assert [s[k].rank for k in s] == [1, 2, 3]
        assert s["XBI"].total == 3 and s["XBI"].top_etf == "XLK" and s["XBI"].top_score == 75.0
        assert s["XBI"].name == "SPDR S&P Biotech"
        assert sector_strengths([{"symbol": "AAPL", "score": 90.0}]) == {}


class TestScan:
    def test_stocks_get_points_from_their_etf_scored_in_the_same_scan(self):
        members = [
            Member("MRNA", "Moderna", "Health Care", "stock", "SP500", industry="Biotechnology"),
            Member("PFE", "Pfizer", "Health Care", "stock", "SP500", industry="Pharmaceuticals"),
            Member("XBI", "SPDR S&P Biotech", "Health Care", "etf", "industry"),
            Member("XLV", "Health Care Select Sector SPDR", "Health Care", "etf", "spdr"),
        ]
        daily = {"MRNA": _daily(), "PFE": _daily(), "XBI": _daily(drift=0.3), "XLV": _daily(drift=-0.2)}
        rows = {r["symbol"]: r for r in scan_all(members, daily)}
        ranking = sector_strengths(list(rows.values()))

        mrna = rows["MRNA"]
        comp = next(c for c in mrna["score_breakdown"] if c["key"] == "sector_strength")
        assert mrna["strength_etf"] == "XBI"
        assert mrna["sector_strength"]["etf"] == "XBI"
        assert mrna["sector_strength"]["score"] == rows["XBI"]["score"]
        assert comp["points"] == pytest.approx(sector_strength_points(ranking["XBI"]), abs=0.01)
        assert comp["max_points"] == 15 and "XBI" in comp["label"] and "XBI" in comp["detail"]
        assert mrna["score_max_raw"] == 123
        assert mrna["score"] == pytest.approx(min(100, mrna["score_raw"] * 100 / 123), abs=0.06)

        assert rows["PFE"]["strength_etf"] == "XLV"
        etf_keys = [c["key"] for c in rows["XBI"]["score_breakdown"]]
        assert "sector_strength" not in etf_keys and rows["XBI"]["score_max_raw"] == 108
        assert rows["XBI"]["sector_strength"] is None

    def test_stock_without_etf_data_scores_zero_for_the_component(self):
        rows = scan_all([Member("MRNA", "Moderna", "Health Care", "stock", "SP500", industry="Biotechnology")], {"MRNA": _daily()})
        comp = next(c for c in rows[0]["score_breakdown"] if c["key"] == "sector_strength")
        assert comp["points"] == 0 and comp["max_points"] == 15
        assert "XBI" in comp["detail"]
        assert rows[0]["sector_strength"] is None


class TestOffUniverse:
    def test_added_symbol_gets_sector_strength_from_its_yahoo_industry(self, client):  # noqa: F811
        api.State.scan.append({"symbol": "XBI", "kind": "etf", "has_setup": False, "score": 50.0, "price": 90.0})
        api.State.scan.append({"symbol": "XLK", "kind": "etf", "has_setup": False, "score": 80.0, "price": 250.0})
        client.post("/api/watchlist", json={"symbol": "MRNA"})
        row = next(r for r in client.get("/api/watchlist").json()["rows"] if r["symbol"] == "MRNA")
        assert row["in_universe"] is False and row["industry"] == "Biotechnology"
        assert row["sector_strength"] == {
            "etf": "XBI", "name": "SPDR S&P Biotech", "score": 50.0, "rank": 2, "total": 2, "points": 9.38,
        }
        comp = next(c for c in row["score_breakdown"] if c["key"] == "sector_strength")
        assert comp["points"] == pytest.approx(15 * 50 / 80, abs=0.01)
        assert client.get("/api/symbol/MRNA").json()["row"]["sector_strength"]["etf"] == "XBI"

    def test_positions_rows_carry_it_too(self, client):  # noqa: F811
        api.State.scan.append({"symbol": "XBI", "kind": "etf", "has_setup": False, "score": 50.0, "price": 90.0})
        body = client.post("/api/positions", json={"symbol": "MRNA"}).json()
        assert body["positions"][0]["row"]["sector_strength"]["etf"] == "XBI"

    def test_industry_is_backfilled_for_symbols_saved_without_one(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "CACHE_DB", tmp_path / "cache.sqlite3")
        data.save_extra_symbol("SOFI", "SoFi", "Financials", "stock")
        data.save_extra_symbol("ARKK", "ARK Innovation", "Other", "etf")
        data.add_to_watchlist("SOFI")
        members = extra_members(only_tracked=False, base=[])
        calls = []
        assert backfill_industries(members, fetch=lambda s: calls.append(s) or "Credit Services") == 1
        assert calls == ["SOFI"]
        assert {e["symbol"]: e["industry"] for e in data.extra_symbols()} == {"ARKK": "", "SOFI": "Credit Services"}

    def test_backfill_survives_lookup_errors(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "CACHE_DB", tmp_path / "cache.sqlite3")
        data.save_extra_symbol("SOFI", "SoFi", "Financials", "stock")

        def boom(symbol):
            raise RuntimeError("rate limited")

        assert backfill_industries(extra_members(only_tracked=False, base=[]), fetch=boom) == 0

    def test_old_cache_files_gain_the_industry_column(self, tmp_path, monkeypatch):
        db = tmp_path / "old.sqlite3"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE extra_symbols (symbol TEXT PRIMARY KEY, name TEXT NOT NULL, sector TEXT NOT NULL, kind TEXT NOT NULL)")
        conn.execute("INSERT INTO extra_symbols VALUES ('SOFI', 'SoFi', 'Financials', 'stock')")
        conn.commit()
        conn.close()
        monkeypatch.setattr(config, "CACHE_DB", db)
        assert data.extra_symbols() == [
            {"symbol": "SOFI", "name": "SoFi", "sector": "Financials", "kind": "stock", "industry": ""}
        ]
