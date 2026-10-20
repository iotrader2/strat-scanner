"""Index cards during premarket and after hours.

The daily cache ends at the last regular session, so a change taken from it before the
open is that session's move. These tests pin the live print to the prior close instead,
including across Eastern daylight time.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from strat import api, config, data, fetch_worker
from strat.quotes import (
    active_quotes,
    build_index_quotes,
    fetch_extended_prices,
    last_extended_prices,
    percent_change,
    reference_close,
)
from strat.scanner import etf_cards, scan_symbol
from strat.universe import Member

ET = ZoneInfo("America/New_York")


def _daily(closes: list[float], days: list[str]) -> pd.DataFrame:
    close = pd.Series(closes, index=pd.to_datetime(days), dtype=float)
    return pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 2_000_000.0}
    )


def test_regular_session_change_is_the_last_close_versus_the_prior_close():
    idx = pd.bdate_range("2026-08-03", periods=60)
    close = pd.Series(100.0, index=idx)
    close.iloc[-1] = 110.0
    daily = pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 2_000_000.0}
    )
    row = scan_symbol(Member("SPY", "SPY", "Benchmark", "etf", "benchmark"), daily)
    assert row is not None
    assert row["price"] == 110.0
    assert row["change_pct"] == percent_change(110.0, 100.0) == 10.0


def test_premarket_change_uses_the_prior_close_not_the_prior_session_move():
    # Friday 100, Monday 110: the prior session was up 10%. Tuesday premarket is 99.
    daily = _daily([100.0, 110.0], ["2026-10-16", "2026-10-19"])
    now = datetime(2026, 10, 20, 8, 0, tzinfo=ET)
    assert reference_close(daily, "premarket", now) == 110.0
    rows = build_index_quotes({"SPY": 99.0}, {"SPY": daily}, now, "premarket")
    assert rows[0]["session"] == "premarket"
    assert rows[0]["price"] == 99.0
    assert rows[0]["previous_close"] == 110.0
    assert rows[0]["change_pct"] == percent_change(99.0, 110.0) == -10.0
    assert percent_change(110.0, 100.0) == 10.0  # the figure the card used to show


def test_a_partial_bar_dated_today_is_not_the_premarket_baseline():
    daily = _daily([100.0, 110.0, 110.0], ["2026-10-16", "2026-10-19", "2026-10-20"])
    now = datetime(2026, 10, 20, 8, 0, tzinfo=ET)
    assert reference_close(daily, "premarket", now) == 110.0
    assert build_index_quotes({"QQQ": 104.5}, {"QQQ": daily}, now, "premarket")[0]["change_pct"] == -5.0


def test_after_hours_change_uses_todays_regular_close():
    daily = _daily([110.0, 108.0], ["2026-10-19", "2026-10-20"])
    now = datetime(2026, 10, 20, 17, 0, tzinfo=ET)
    assert reference_close(daily, "after_hours", now) == 108.0
    row = build_index_quotes({"IWM": 107.0}, {"IWM": daily}, now, "after_hours")[0]
    assert row["session"] == "after_hours"
    assert row["change_pct"] == percent_change(107.0, 108.0)
    assert row["change_pct"] != percent_change(107.0, 110.0)
    assert reference_close(_daily([110.0], ["2026-10-19"]), "after_hours", now) is None


def test_the_reference_close_uses_the_eastern_date_across_dst():
    daily = _daily([10.0, 20.0, 30.0], ["2026-07-13", "2026-07-14", "2026-07-15"])
    # 03:30 UTC is still July 14 in Eastern daylight time, so the prior close is July 13.
    summer = datetime(2026, 7, 15, 3, 30, tzinfo=timezone.utc)
    assert reference_close(daily, "premarket", summer) == 10.0
    winter = _daily([10.0, 20.0, 30.0], ["2026-01-13", "2026-01-14", "2026-01-15"])
    # 04:30 UTC is still January 14 in standard time.
    assert reference_close(winter, "premarket", datetime(2026, 1, 15, 4, 30, tzinfo=timezone.utc)) == 10.0


def test_prepost_bars_keep_only_todays_extended_window():
    idx = pd.DatetimeIndex(
        [
            pd.Timestamp("2026-10-19 19:59", tz=ET),  # yesterday after hours
            pd.Timestamp("2026-10-20 03:59", tz=ET),  # before the premarket open
            pd.Timestamp("2026-10-20 04:00", tz=ET),
            pd.Timestamp("2026-10-20 09:11", tz=ET),
            pd.Timestamp("2026-10-20 09:30", tz=ET),  # regular session
        ]
    )
    cols = pd.MultiIndex.from_product([["SPY", "QQQ"], ["Close"]], names=["Ticker", "Price"])
    frame = pd.DataFrame(
        {
            ("SPY", "Close"): [1.0, 2.0, 3.0, 4.0, 5.0],
            ("QQQ", "Close"): [10.0, 20.0, 30.0, None, 50.0],
        },
        index=idx,
    )
    frame.columns = cols
    now = datetime(2026, 10, 20, 9, 12, tzinfo=ET)
    assert last_extended_prices(frame, ["SPY", "QQQ", "IWM"], now, "premarket") == {"SPY": 4.0, "QQQ": 30.0}

    # 08:00 UTC is 04:00 EDT (inside) in July and 03:00 EST (outside) in January.
    summer = pd.DataFrame(
        {"Close": [111.0]},
        index=pd.DatetimeIndex([pd.Timestamp("2026-07-15 08:00", tz="UTC")]),
    )
    winter = pd.DataFrame(
        {"Close": [222.0]},
        index=pd.DatetimeIndex([pd.Timestamp("2026-01-15 08:00", tz="UTC")]),
    )
    assert last_extended_prices(summer, ["SPY"], datetime(2026, 7, 15, 8, 30, tzinfo=timezone.utc), "premarket") == {
        "SPY": 111.0
    }
    assert last_extended_prices(winter, ["SPY"], datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc), "premarket") == {}
    assert last_extended_prices(
        pd.DataFrame({"Close": [333.0]}, index=pd.DatetimeIndex([pd.Timestamp("2026-01-15 09:00", tz="UTC")])),
        ["SPY"],
        datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc),
        "premarket",
    ) == {"SPY": 333.0}


def test_after_hours_bars_stop_at_eight():
    idx = pd.DatetimeIndex(
        [
            pd.Timestamp("2026-10-20 15:59", tz=ET),
            pd.Timestamp("2026-10-20 16:00", tz=ET),
            pd.Timestamp("2026-10-20 19:59", tz=ET),
            pd.Timestamp("2026-10-20 20:00", tz=ET),
        ]
    )
    frame = pd.DataFrame({"Close": [1.0, 2.0, 3.0, 4.0]}, index=idx)
    now = datetime(2026, 10, 20, 19, 0, tzinfo=ET)
    assert last_extended_prices(frame, ["IWM"], now, "after_hours") == {"IWM": 3.0}


def test_yahoo_prepost_fetch_is_one_light_request(monkeypatch):
    captured = {}

    def fake_download(symbols, **kwargs):
        captured["symbols"] = list(symbols)
        captured["kwargs"] = kwargs
        idx = pd.DatetimeIndex([pd.Timestamp("2026-10-20 08:15", tz=ET)])
        cols = pd.MultiIndex.from_product([["QQQ", "SPY", "IWM"], ["Close"]], names=["Ticker", "Price"])
        return pd.DataFrame([[715.5, 765.5, 269.5]], index=idx, columns=cols)

    monkeypatch.setattr(yf, "download", fake_download)
    now = datetime(2026, 10, 20, 8, 20, tzinfo=ET)
    assert fetch_extended_prices(["QQQ", "SPY", "IWM"], now=now) == {"QQQ": 715.5, "SPY": 765.5, "IWM": 269.5}
    assert captured["kwargs"]["prepost"] is True
    assert captured["kwargs"]["interval"] == "1m"
    assert captured["kwargs"]["period"] == "1d"
    assert captured["kwargs"]["threads"] is False
    assert set(captured["symbols"]) == {"QQQ", "SPY", "IWM"}


def test_a_failed_prepost_fetch_returns_nothing(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("yahoo down")

    monkeypatch.setattr(yf, "download", boom)
    assert fetch_extended_prices(now=datetime(2026, 10, 20, 8, 0, tzinfo=ET)) == {}
    assert fetch_extended_prices(now=datetime(2026, 10, 20, 11, 0, tzinfo=ET)) == {}


def test_the_card_badge_overrides_only_the_quoted_index():
    idx = pd.bdate_range("2026-08-03", periods=60)
    frames = {}
    rows = {}
    for sym, last in (("SPY", 110.0), ("QQQ", 210.0)):
        close = pd.Series(100.0, index=idx)
        close.iloc[-2] = 100.0
        close.iloc[-1] = last
        frames[sym] = pd.DataFrame(
            {"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 2_000_000.0}
        )
        rows[sym] = scan_symbol(Member(sym, sym, "Benchmark", "etf", "benchmark"), frames[sym])
    assert rows["SPY"]["change_pct"] == 10.0
    from strat.quotes import IndexQuote

    quote = IndexQuote("SPY", 99.0, 110.0, -10.0, "premarket", "2026-10-20", "2026-10-20T08:00:00-04:00")
    cards = etf_cards(
        [("SPY", "S", "Benchmark", "benchmark"), ("QQQ", "Q", "Benchmark", "benchmark")],
        rows,
        frames,
        "D",
        20,
        quotes={"SPY": quote},
    )
    spy, qqq = cards
    assert spy["session"] == "premarket"
    assert spy["row"]["price"] == 99.0 and spy["row"]["change_pct"] == -10.0
    assert rows["SPY"]["change_pct"] == 10.0  # the scan row stays the regular-session figure
    assert qqq["session"] is None and qqq["row"]["change_pct"] == rows["QQQ"]["change_pct"]


def test_cached_quotes_apply_only_in_the_matching_session(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "cache.sqlite3")
    monkeypatch.setattr(config, "AS_OF", None)
    row = {
        "symbol": "SPY",
        "price": 99.0,
        "previous_close": 110.0,
        "change_pct": -10.0,
        "session": "premarket",
        "day": "2026-10-20",
        "as_of": "2026-10-20T08:00:00-04:00",
    }
    assert data.save_index_quotes([row])
    assert not data.save_index_quotes([row])
    assert active_quotes(datetime(2026, 10, 20, 8, 0, tzinfo=ET))["SPY"].change_pct == -10.0
    assert active_quotes(datetime(2026, 10, 20, 10, 0, tzinfo=ET)) == {}
    assert active_quotes(datetime(2026, 10, 20, 17, 0, tzinfo=ET)) == {}
    assert active_quotes(datetime(2026, 10, 21, 8, 0, tzinfo=ET)) == {}
    monkeypatch.setattr(config, "AS_OF", "2026-10-20")
    assert active_quotes(datetime(2026, 10, 20, 8, 0, tzinfo=ET)) == {}
    monkeypatch.setattr(config, "AS_OF", None)
    assert data.clear_index_quotes()
    assert not data.clear_index_quotes()


def test_index_quote_refresh_uses_the_child_and_does_not_rescan(tmp_path, monkeypatch):
    monkeypatch.setenv("STRAT_FETCH_SUBPROCESS", "1")
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "cache.sqlite3")
    monkeypatch.setattr(config, "AS_OF", None)
    monkeypatch.setattr(api, "now_et", lambda: datetime(2026, 10, 20, 8, 0, tzinfo=ET))
    monkeypatch.setattr(api, "session_phase", lambda now=None: "premarket")
    monkeypatch.setattr(api.State, "daily", {"SPY": _daily([100.0, 110.0], ["2026-10-16", "2026-10-19"])})
    monkeypatch.setattr(api.State, "version", 3)
    monkeypatch.setattr(api.State, "quoting", True)
    monkeypatch.setattr(fetch_worker, "extended_prices_in_child", lambda: {"SPY": 99.0})

    def fail(*_a, **_k):
        raise AssertionError("in-process fetch")

    monkeypatch.setattr("strat.quotes.fetch_extended_prices", fail)
    published = []
    monkeypatch.setattr(api.hub, "publish", published.append)
    api._run_index_quotes()
    assert api.State.quoting is False
    assert api.State.version == 4
    assert published and published[0]["type"] == "snapshot"
    stored = data.load_index_quotes()
    assert stored[0]["symbol"] == "SPY" and stored[0]["change_pct"] == -10.0 and stored[0]["session"] == "premarket"
    api._run_index_quotes()
    assert api.State.version == 4  # same print, no extra fan-out
