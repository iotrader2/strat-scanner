import pandas as pd
import pytest

from strat import config, data
from strat.themes import (
    ThemeError,
    build_theme_index,
    load_themes,
    parse_themes,
    sync_universe,
    unknown_symbols,
)
from strat.universe import Member, load_universe, write_universe


def _doc(**themes):
    return {"version": 1, "themes": themes}


def _theme(members, **extra):
    return {"name": extra.pop("name", "A theme"), "members": members, **extra}


class TestParsing:
    def test_primary_secondary_and_keep(self):
        m = parse_themes(
            _doc(
                cyber=_theme("CRWD PANW ZS", name="Cyber", also="NET", keep="ZS"),
                cloud=_theme("NET SNOW DDOG", name="Cloud", also="ZS"),
            )
        )
        assert [t.id for t in m.themes] == ["cyber", "cloud"]
        assert m.theme_of("CRWD").id == "cyber" and m.theme_of("NET").id == "cloud"
        assert m.theme_of("NOPE") is None
        assert m.secondary == {"NET": ["cyber"], "ZS": ["cloud"]}
        assert m.by_id("cyber").everyone == ("CRWD", "PANW", "ZS", "NET")
        assert m.by_id("cyber").keep == ("ZS",)
        assert m.symbols() == ["CRWD", "PANW", "ZS", "NET", "SNOW", "DDOG"]

    def test_tickers_accept_lists_commas_and_class_shares(self):
        m = parse_themes(_doc(a=_theme(["brk.b", "ON", "AAPL"]), b=_theme("MSFT, GOOG,  META", name="Other")))
        assert m.by_id("a").members == ("BRK-B", "ON", "AAPL")
        assert m.by_id("b").members == ("MSFT", "GOOG", "META")

    def test_a_stock_has_one_primary_theme(self):
        with pytest.raises(ThemeError) as e:
            parse_themes(_doc(a=_theme("AAPL MSFT GOOG"), b=_theme("AAPL AMZN META", name="B")))
        assert any("AAPL is the primary member of both a and b" in p for p in e.value.problems)

    def test_reports_every_problem_at_once(self):
        with pytest.raises(ThemeError) as e:
            parse_themes(
                {
                    "themes": {
                        "Bad Id": _theme("AAPL MSFT GOOG"),
                        "dup": _theme("AAPL MSFT"),
                        "unnamed": {"members": "A B C"},
                        "keepy": _theme("X Y Z", name="Keepy", keep="Q"),
                        "booleans": _theme([True, "NVDA", "AMD"], name="Bool"),
                    }
                }
            )
        text = " | ".join(e.value.problems)
        for expected in ("version", "lowercase", "at least 3", "missing name", "keep", "not a ticker string"):
            assert expected in text

    def test_primary_and_also_overlap_and_duplicates(self):
        with pytest.raises(ThemeError) as e:
            parse_themes(_doc(a=_theme("A B C C", also="A D D")))
        text = " | ".join(e.value.problems)
        assert "duplicate C" in text and "duplicate D" in text and "both primary and also" in text

    def test_duplicate_names_and_shape_errors(self):
        with pytest.raises(ThemeError, match="duplicate theme name"):
            parse_themes(_doc(a=_theme("A B C", name="Same"), b=_theme("D E F", name="same")))
        with pytest.raises(ThemeError, match="top-level"):
            parse_themes(["not", "a", "mapping"])

    def test_invalid_yaml_is_a_theme_error(self, tmp_path):
        p = tmp_path / "themes.yaml"
        p.write_text("version: 1\nthemes:\n  a:\n    description: bad: colon\n")
        with pytest.raises(ThemeError, match="not valid YAML"):
            load_themes(p)


class TestShippedMap:
    """The curated data/themes.yaml that ships with the app."""

    @pytest.fixture
    def themes(self):
        return load_themes()

    def test_loads_and_is_versioned(self, themes):
        assert themes.version >= 1
        assert len(themes.themes) >= 60

    def test_the_themes_from_the_brief_exist_with_their_names(self, themes):
        by = {t.name: t for t in themes.themes}
        expect = {
            "Cybersecurity": {"CRWD", "PANW", "ZS", "FTNT", "NET", "S", "OKTA"},
            "Mega-cap tech": {"META", "GOOGL", "MSFT", "AMZN", "AAPL"},
            "AI hardware & servers": {"DELL", "HPE", "SMCI", "ANET", "VRT"},
            "Memory & storage": {"MU", "SNDK", "WDC", "STX"},
            "Semis & chips": {"AMD", "INTC", "NVDA", "AVGO", "QCOM", "MRVL"},
            "Neoclouds & AI infrastructure": {"NBIS", "CRWV", "IREN", "CORZ"},
        }
        for name, symbols in expect.items():
            assert symbols <= set(by[name].members), name

    def test_every_requested_area_is_covered(self, themes):
        text = " ".join(t.name.lower() for t in themes.themes)
        for word in (
            "semicap", "software", "payments", "banks", "regional banks", "e&p", "oil services", "homebuilders",
            "airlines", "biotech", "pharma", "medtech", "defense", "electrification", "nuclear", "crypto", "retail",
            "restaurants", "china", "quantum", "space", "robotics",
        ):
            assert word in text, word

    def test_every_theme_has_a_description_and_enough_members(self, themes):
        for t in themes.themes:
            assert t.description, t.id
            assert len(t.members) >= 3, t.id

    def test_every_ticker_is_in_the_universe_as_a_stock(self, themes):
        assert unknown_symbols(themes, load_universe()) == []

    def test_theme_only_universe_rows_are_all_used(self, themes):
        wanted = set(themes.symbols())
        stray = [m.symbol for m in load_universe() if m.indexes == "THEME" and m.symbol not in wanted]
        assert stray == []


def _ohlc(closes, start="2026-01-05", spread=1.0, volume=1_000_000.0):
    idx = pd.bdate_range(start, periods=len(closes))
    c = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame({"open": c - 0.5, "high": c + spread, "low": c - spread, "close": c, "volume": volume})


class TestThemeIndex:
    def test_equal_weight_ignores_price_level(self):
        cheap = _ohlc([10.0, 11.0, 12.1])  # +10% a day
        dear = _ohlc([1000.0, 1000.0, 1000.0])  # flat
        idx = build_theme_index({"CHEAP": cheap, "DEAR": dear}, ["CHEAP", "DEAR"])
        # The index is 100 before the first return; each day multiplies it by the mean of (+10%, 0%) = +5%.
        assert len(idx) == 2
        assert idx.close.iloc[0] == pytest.approx(100.0 * 1.05)
        assert idx.close.iloc[1] == pytest.approx(100.0 * 1.05 * 1.05)
        assert idx.iloc[0].open < idx.iloc[0].close

    def test_candle_is_the_average_of_member_ratios_to_their_previous_close(self):
        a = _ohlc([100.0, 100.0])
        b = _ohlc([50.0, 50.0])
        idx = build_theme_index({"A": a, "B": b}, ["A", "B"])
        last = idx.iloc[-1]
        # Day 2, A: o 99.5 h 101 l 99 c 100 over prev close 100; B: o 49.5 h 51 l 49 c 50 over prev close 50.
        assert last.open == pytest.approx(100.0 * (0.995 + 0.99) / 2)
        assert last.high == pytest.approx(100.0 * (1.01 + 1.02) / 2)
        assert last.low == pytest.approx(100.0 * (0.99 + 0.98) / 2)
        assert last.close == pytest.approx(100.0)
        assert (idx.low <= idx[["open", "close"]].min(axis=1)).all() and (idx.high >= idx[["open", "close"]].max(axis=1)).all()

    def test_volume_makes_close_times_volume_the_combined_dollar_volume(self):
        a = _ohlc([100.0, 110.0, 121.0], volume=1_000_000.0)
        b = _ohlc([20.0, 20.0, 20.0], volume=5_000_000.0)
        idx = build_theme_index({"A": a, "B": b}, ["A", "B"])
        last_day = idx.index[-1]
        expected = 121.0 * 1_000_000 + 20.0 * 5_000_000
        assert idx.at[last_day, "close"] * idx.at[last_day, "volume"] == pytest.approx(expected)

    def test_late_listing_does_not_rewrite_history(self):
        a = _ohlc([100.0, 101.0, 102.0, 103.0, 104.0, 105.0])
        b = _ohlc([50.0, 55.0, 60.0], start=str(a.index[3].date()))  # joins on day 4
        c = _ohlc([10.0, 10.0, 10.0, 10.0, 10.0, 10.0])
        alone = build_theme_index({"A": a, "C": c}, ["A", "C"])
        both = build_theme_index({"A": a, "B": b, "C": c}, ["A", "B", "C"])
        # B has no prices on the first days, so those days only average A and C.
        assert both.close.iloc[2] == pytest.approx(alone.close.iloc[2])
        assert both.close.iloc[-1] != pytest.approx(alone.close.iloc[-1])

    def test_index_waits_until_half_the_members_trade(self):
        a = _ohlc([100.0] * 6)
        late1 = _ohlc([10.0, 11.0, 12.0], start=str(a.index[3].date()))
        late2 = _ohlc([10.0, 11.0, 12.0], start=str(a.index[3].date()))
        late3 = _ohlc([10.0, 11.0, 12.0], start=str(a.index[3].date()))
        idx = build_theme_index({"A": a, "L1": late1, "L2": late2, "L3": late3}, ["A", "L1", "L2", "L3"])
        assert idx.index[0] >= a.index[4]  # needs 2 of 4 members with a prior close

    def test_nothing_to_build(self):
        assert build_theme_index({}, ["A", "B"]) is None
        assert build_theme_index({"A": _ohlc([100.0])}, ["A"]) is None


def _bars(n=300, start=100.0, volume=9_000_000.0, end=None):
    idx = pd.bdate_range(end=end or pd.Timestamp.now().normalize(), periods=n)
    close = pd.Series([start + (i % 9) * 0.5 for i in range(n)], index=idx)
    return pd.DataFrame(
        {"Open": close - 0.3, "High": close + 0.8, "Low": close - 0.8, "Close": close, "Volume": volume}
    ).tz_localize("America/New_York")


class TestSync:
    @pytest.fixture
    def universe_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "CACHE_DB", tmp_path / "cache.sqlite3")
        path = tmp_path / "universe.csv"
        write_universe(
            [
                Member("AAA", "Triple A", "Information Technology", "stock", "SP500"),
                Member("OLD", "Old theme name", "Industrials", "stock", "THEME"),
            ],
            path,
        )
        return path

    def _lookup(self, table):
        def lookup(symbol):
            if symbol == "FLAKY":
                raise data.LookupFailed("connection reset")
            if symbol not in table:
                raise data.SymbolNotFound(symbol)
            return table[symbol]

        return lookup

    def test_adds_liquid_names_prunes_unused_and_reports_the_rest(self, universe_file):
        meta = {"name": "N", "sector": "Information Technology", "kind": "stock", "industry": "Software"}
        table = {
            "GOOD": (_bars(), meta),
            "THIN": (_bars(volume=1_000.0), meta),
            "PENNY": (_bars(start=0.2), meta),
            "STALE": (_bars(end=pd.Timestamp.now().normalize() - pd.Timedelta(days=60)), meta),
            "FUND": (_bars(), {**meta, "kind": "etf"}),
        }
        themes = parse_themes(_doc(t=_theme("AAA GOOD THIN", also="PENNY STALE FUND GONE FLAKY")))
        result = sync_universe(themes, lookup=self._lookup(table), path=universe_file)

        assert [m.symbol for m in result.added] == ["GOOD"]
        assert result.added[0].indexes == "THEME" and result.added[0].industry == "Software"
        assert result.pruned == ["OLD"]
        assert set(result.rejected) == {"THIN", "PENNY", "STALE", "FUND", "GONE"}
        assert "illiquid" in result.rejected["THIN"] and "ETF" in result.rejected["FUND"]
        assert "days old" in result.rejected["STALE"] and "not found" in result.rejected["GONE"]
        assert list(result.failed) == ["FLAKY"]
        assert {m.symbol for m in load_universe(universe_file)} == {"AAA", "GOOD"}
        assert "GOOD" in data.cached_symbols()

    def test_dry_run_style_call_does_not_write(self, universe_file):
        meta = {"name": "N", "sector": "Industrials", "kind": "stock", "industry": ""}
        themes = parse_themes(_doc(t=_theme("AAA GOOD OLD")))
        before = universe_file.read_text()
        result = sync_universe(themes, lookup=self._lookup({"GOOD": (_bars(), meta)}), save=False, path=universe_file)
        assert [m.symbol for m in result.added] == ["GOOD"]
        assert universe_file.read_text() == before
        assert "GOOD" not in data.cached_symbols()

    def test_nothing_to_do(self, universe_file):
        themes = parse_themes(_doc(t=_theme("AAA OLD X")))
        calls = []
        result = sync_universe(themes, lookup=lambda s: calls.append(s) or (_ for _ in ()).throw(data.SymbolNotFound(s)), path=universe_file)
        assert calls == ["X"] and result.pruned == []
