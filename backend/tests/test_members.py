import sys

from strat import config, data, earnings, members, refresh
from strat.universe import Member

BASE = [Member("AAPL", "Apple", "Information Technology", "stock", "SP500"), Member("XLE", "Energy", "Energy", "etf", "spdr")]


def test_effective_universe_adds_only_watched_off_universe_symbols(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "cache.sqlite3")
    data.save_extra_symbol("SOFI", "SoFi", "Financials", "stock")
    data.save_extra_symbol("RIVN", "Rivian", "Consumer Discretionary", "stock")
    data.save_extra_symbol("AAPL", "Apple", "Information Technology", "stock")
    data.add_to_watchlist("SOFI")
    data.add_to_watchlist("AAPL")
    got = members.effective_universe(BASE)
    assert [m.symbol for m in got] == ["AAPL", "XLE", "SOFI"]
    assert got[-1].in_universe is False and got[-1].indexes == "Watchlist"
    assert {m.symbol for m in members.extra_members(only_tracked=False, base=BASE)} == {"SOFI", "RIVN"}


def test_cli_refresh_includes_watched_symbols_and_earnings(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "cache.sqlite3")
    data.save_extra_symbol("SOFI", "SoFi", "Financials", "stock")
    data.add_to_watchlist("SOFI")
    monkeypatch.setattr(refresh, "load_universe", lambda: BASE)
    prices, earnings_for = [], []
    monkeypatch.setattr(data, "refresh", lambda symbols, **kw: prices.extend(symbols) or {})
    monkeypatch.setattr(
        earnings, "refresh_earnings", lambda symbols, max_age_hours, progress=None: earnings_for.extend(symbols)
    )
    monkeypatch.setattr(sys, "argv", ["strat.refresh"])
    refresh.main()
    assert prices == ["AAPL", "XLE", "SOFI"]
    assert earnings_for == ["AAPL", "SOFI"]
