import sqlite3

import pandas as pd
import pytest

from strat import api, config, data
from strat.members import backfill_industries, extra_members
from strat.scanner import scan_all, scan_symbol, theme_strengths
from strat.scoring import THEME_POINTS, ThemeStrength, theme_strength_points
from strat.themes import parse_themes
from strat.universe import Member

from test_watchlist import client  # noqa: F401  (shared fixture: temp SQLite, fake universe, stubbed yfinance)


def _daily(n=160, drift=0.1, end="2026-10-15"):
    idx = pd.bdate_range(end=end, periods=n)
    close = pd.Series([100 + i * drift + (i % 5) * 0.4 for i in range(n)], index=idx, dtype=float)
    return pd.DataFrame(
        {"open": close - 0.3, "high": close + 1, "low": close - 1, "close": close, "volume": 2_000_000.0}
    )


def _strength(theme, score, rank=2, top="memory", top_score=80.0):
    return ThemeStrength(theme, theme.title(), score, rank, 82, top, top_score, top.title())


class TestPoints:
    def test_top_ranked_theme_gets_full_points(self):
        assert theme_strength_points(_strength("memory", 80.0, rank=1)) == THEME_POINTS == 10

    def test_points_fall_with_the_rank_among_all_themes(self):
        assert theme_strength_points(_strength("a", 40.0, rank=2)) == pytest.approx(10 * 81 / 82)
        assert theme_strength_points(_strength("b", 20.0, rank=41)) == pytest.approx(10 * 42 / 82)
        assert theme_strength_points(_strength("c", 0.0, rank=82)) == pytest.approx(10 / 82)

    def test_missing_or_degenerate_rankings_give_zero(self):
        assert theme_strength_points(None) == 0
        assert theme_strength_points(ThemeStrength("a", "A", 1.0, 1, 0, "a", 1.0, "A")) == 0

    def test_ranking_follows_the_themes_page(self):
        themes = parse_themes(
            {
                "version": 1,
                "themes": {
                    "a": {"name": "Alpha", "members": "A1 A2 A3"},
                    "b": {"name": "Beta", "members": "B1 B2 B3"},
                    "c": {"name": "Gamma", "members": "C1 C2 C3"},
                },
            }
        )
        rows = {
            "a": {"symbol": "a", "name": "Alpha", "score": 60.0},
            "b": {"symbol": "b", "name": "Beta", "score": 75.0},
            "c": {"symbol": "c", "name": "Gamma", "score": 60.0},
        }
        s = theme_strengths(rows, themes)
        assert list(s) == ["b", "a", "c"]  # ties by name
        assert [s[k].rank for k in s] == [1, 2, 3]
        assert s["a"].total == 3 and s["a"].top_theme == "b" and s["a"].top_score == 75.0 and s["a"].top_name == "Beta"
        assert theme_strengths({}, themes) == {}


MAP = parse_themes(
    {
        "version": 1,
        "themes": {
            "fast": {"name": "Fast movers", "members": "F1 F2 F3", "also": "S1"},
            "slow": {"name": "Slow movers", "members": "S1 S2 S3"},
        },
    }
)


def _members():
    return [
        Member(s, s, "Information Technology", "stock", "SP500") for s in ("F1", "F2", "F3", "S1", "S2", "S3", "LONE")
    ] + [Member("XLK", "Technology SPDR", "Information Technology", "etf", "spdr")]


def _history():
    fast, slow = _daily(drift=0.4), _daily(drift=-0.1)
    return {
        **{s: fast for s in ("F1", "F2", "F3")},
        **{s: slow for s in ("S1", "S2", "S3")},
        "LONE": _daily(drift=0.2),
        "XLK": _daily(drift=0.3),
    }


class TestScan:
    def test_stocks_take_their_primary_themes_rank_from_the_same_scan(self):
        result = scan_all(_members(), _history(), MAP)
        rows = {r["symbol"]: r for r in result.rows}
        assert set(result.theme_rows) == {"fast", "slow"}
        assert "fast" not in rows and "slow" not in rows  # theme indexes are not stock/ETF rows

        f1 = rows["F1"]
        comp = next(c for c in f1["score_breakdown"] if c["key"] == "theme_strength")
        assert f1["theme"] == "fast" and f1["theme_name"] == "Fast movers"
        assert f1["theme_strength"]["theme"] == "fast"
        assert f1["theme_strength"]["score"] == result.theme_rows["fast"]["score"]
        assert comp["points"] == pytest.approx(theme_strength_points(result.strengths["fast"]), abs=0.01)
        assert comp["max_points"] == 10 and "Fast movers" in comp["label"] and "Fast movers" in comp["detail"]
        assert f1["score_max_raw"] == 100
        assert f1["score"] == pytest.approx(min(100, f1["score_raw"] * 100 / 100), abs=0.06)

    def test_a_stock_uses_its_primary_theme_not_its_secondary_ones(self):
        rows = {r["symbol"]: r for r in scan_all(_members(), _history(), MAP).rows}
        assert rows["S1"]["theme"] == "slow" and rows["S1"]["secondary_themes"] == ["fast"]
        assert rows["S1"]["secondary_theme_names"] == ["Fast movers"]
        assert rows["F1"]["secondary_themes"] == []

    def test_unthemed_stocks_score_zero_for_the_component(self):
        rows = {r["symbol"]: r for r in scan_all(_members(), _history(), MAP).rows}
        lone = rows["LONE"]
        comp = next(c for c in lone["score_breakdown"] if c["key"] == "theme_strength")
        assert lone["theme"] is None and lone["theme_strength"] is None
        assert comp["points"] == 0 and comp["max_points"] == 10 and "not in any theme" in comp["detail"]

    def test_etfs_and_themes_have_no_theme_strength(self):
        result = scan_all(_members(), _history(), MAP)
        xlk = next(r for r in result.rows if r["symbol"] == "XLK")
        keys = [c["key"] for c in xlk["score_breakdown"]]
        assert "theme_strength" not in keys and xlk["score_max_raw"] == 90 and xlk["theme_strength"] is None
        fast = result.theme_rows["fast"]
        assert "theme_strength" not in [c["key"] for c in fast["score_breakdown"]] and fast["score_max_raw"] == 85
        assert "liquidity" not in [c["key"] for c in fast["score_breakdown"]]
        assert fast["kind"] == "theme" and fast["name"] == "Fast movers"

    def test_the_faster_theme_ranks_first_through_relative_strength(self):
        result = scan_all(_members(), _history(), MAP)
        assert result.strengths["fast"].rank == 1 and result.strengths["slow"].rank == 2
        pts = lambda sym: next(c for c in result.theme_rows[sym]["score_breakdown"] if c["key"] == "rs")["points"]
        assert pts("fast") > pts("slow")

    def test_scanning_without_themes_still_works(self):
        rows = scan_all(_members(), _history(), None).rows
        assert all(r["theme"] is None for r in rows) and len(rows) == 8

    def test_a_theme_without_enough_data_is_skipped(self):
        history = {k: v for k, v in _history().items() if k not in ("S1", "S2")}
        assert "slow" not in scan_all(_members(), history, MAP).theme_rows

    def test_single_symbol_rescan_reuses_the_ranking(self):
        result = scan_all(_members(), _history(), MAP)
        row = scan_symbol(_members()[0], _history()["F1"], result.strengths, result.ranks, MAP)
        assert row["theme_strength"]["rank"] == 1
        assert row["perf"] == next(r for r in result.rows if r["symbol"] == "F1")["perf"]


class TestOffUniverse:
    def test_added_symbol_without_a_theme_scores_zero_theme_points(self, client):  # noqa: F811
        client.post("/api/watchlist", json={"symbol": "MRNA"})
        row = next(r for r in client.get("/api/watchlist").json()["rows"] if r["symbol"] == "MRNA")
        assert row["in_universe"] is False and row["industry"] == "Biotechnology"
        assert row["theme"] is None and row["theme_strength"] is None
        comp = next(c for c in row["score_breakdown"] if c["key"] == "theme_strength")
        assert comp["points"] == 0
        assert "perf" in row and set(row["perf"]) == {"1m", "3m", "6m"}
        assert any(c["key"] == "rs" for c in row["score_breakdown"])

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
