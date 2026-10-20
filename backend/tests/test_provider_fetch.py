"""Yahoo download shape: serial 5-day polls, and a serial retry after a partial miss."""

import pandas as pd

from strat.provider import YahooProvider


def _frame(symbols: list[str]) -> pd.DataFrame:
    idx = pd.to_datetime(["2026-10-16"])
    cols = pd.MultiIndex.from_product([symbols, ["Open", "High", "Low", "Close", "Volume"]])
    return pd.DataFrame({col: 1.0 for col in cols}, index=idx)


def test_five_day_poll_downloads_serially(monkeypatch):
    calls = []

    def download(symbols, **kwargs):
        calls.append((list(symbols), kwargs["threads"]))
        return _frame(list(symbols))

    monkeypatch.setattr("yfinance.download", download)
    result = YahooProvider().fetch_history(["AAA", "BBB"], "5d")
    assert calls == [(["AAA", "BBB"], False)]
    assert set(result.frames) == {"AAA", "BBB"}


def test_threaded_partial_miss_is_retried_serially(monkeypatch):
    calls = []

    def download(symbols, **kwargs):
        symbols = list(symbols)
        calls.append((symbols, kwargs["threads"]))
        # The threaded pass drops the last symbol, the way a cache lock does.
        kept = symbols if not kwargs["threads"] else symbols[:-1]
        return _frame(kept)

    monkeypatch.setattr("yfinance.download", download)
    result = YahooProvider().fetch_history(["AAA", "BBB"], "3mo")
    assert calls == [(["AAA", "BBB"], True), (["BBB"], False)]
    assert set(result.frames) == {"AAA", "BBB"}


def test_total_miss_is_not_retried_symbol_by_symbol(monkeypatch):
    calls = []

    def download(symbols, **kwargs):
        calls.append((list(symbols), kwargs["threads"]))
        return pd.DataFrame()

    monkeypatch.setattr("yfinance.download", download)
    result = YahooProvider().fetch_history(["AAA", "BBB"], "3mo")
    assert calls == [(["AAA", "BBB"], True)]
    assert result.frames == {}
