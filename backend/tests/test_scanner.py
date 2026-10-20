import pandas as pd

from strat.scanner import ATR_PERIOD, average_true_range, scan_symbol
from strat.universe import Member


def _daily(n=80):
    idx = pd.bdate_range("2026-06-01", periods=n)
    close = pd.Series([100 + (i % 7) for i in range(n)], index=idx, dtype=float)
    vol = pd.Series([1_000_000.0] * (n - 20) + [2_000_000.0 + i * 100_000 for i in range(20)], index=idx)
    return pd.DataFrame({"open": close - 0.5, "high": close + 1, "low": close - 1, "close": close, "volume": vol})


def test_avg_volume_is_20_day_mean_of_shares():
    df = _daily()
    row = scan_symbol(Member("TEST", "Test", "Industrials", "stock", "SP500"), df)
    assert row["avg_volume"] == df.volume.tail(20).mean() == 2_950_000
    assert row["avg_dollar_volume"] == (df.close * df.volume).tail(20).mean()


def test_atr_is_the_14_day_average_true_range():
    df = _daily()
    atr, atr_pct = average_true_range(df)
    row = scan_symbol(Member("TEST", "Test", "Industrials", "stock", "SP500"), df)
    assert ATR_PERIOD == 14
    assert row["atr"] == round(atr, 2)
    assert row["atr_pct"] == round(atr_pct, 2)
    assert row["atr_pct"] == round(atr / float(df.close.iloc[-1]) * 100, 2)


def test_row_carries_the_daily_macd_trend_of_its_last_bar():
    from strat.macd import latest_daily_trend

    df = _daily()
    row = scan_symbol(Member("TEST", "Test", "Industrials", "stock", "SP500"), df)
    assert row["daily_trend"] == latest_daily_trend(df)
    assert row["daily_trend"] in (None, "bullish", "bearish")


def test_row_carries_score_breakdown():
    row = scan_symbol(Member("TEST", "Test", "Industrials", "stock", "SP500"), _daily())
    assert row["score_max_raw"] == 100
    assert abs(sum(c["points"] for c in row["score_breakdown"]) - row["score_raw"]) < 0.05
    assert {"key", "label", "points", "max_points", "detail"} <= set(row["score_breakdown"][0])


def _failed_breakout_history():
    from tests.test_breakout import _daily as breakout_daily, _extend

    return _extend(breakout_daily(40, 30, 6), [111.0] * 5 + [110.0, 109.0, 99.0, 98.0, 97.0])


def test_row_carries_a_failed_breakout_and_it_follows_the_cut_off_date():
    member = Member("TEST", "Test", "Industrials", "stock", "SP500")
    df = _failed_breakout_history()
    row = scan_symbol(member, df)
    failed = row["failed_breakout"]
    assert failed is not None and failed["level"] == 108.0 and failed["below_pct"] < 0
    assert failed["failed_on"] == "2026-10-21" and failed["week"] == "2026-10-05"
    # Hiding everything after the failure (what STRAT_AS_OF does) leaves a breakout that has not failed yet.
    held = scan_symbol(member, df[df.index <= "2026-10-20"])
    assert held["failed_breakout"] is None
    assert scan_symbol(member, df[df.index <= "2026-10-21"])["failed_breakout"]["sessions_below"] == 1


def test_etfs_have_no_failed_breakout():
    row = scan_symbol(Member("ETF", "Etf", "Other", "etf", "SP500"), _failed_breakout_history())
    assert row["failed_breakout"] is None
