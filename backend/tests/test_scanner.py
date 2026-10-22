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
    from strat.leadership import trend_metrics
    from strat.macd import daily_trend_setup, latest_daily_trend

    df = _daily()
    row = scan_symbol(Member("TEST", "Test", "Industrials", "stock", "SP500"), df)
    assert row["daily_macd_trigger"] == latest_daily_trend(df)
    assert row["daily_trend"] == daily_trend_setup(latest_daily_trend(df), trend_metrics(df))
    assert row["daily_trend"] in (None, "bullish", "bearish")


def _trend_frame(closes):
    idx = pd.bdate_range("2025-06-02", periods=len(closes))
    close = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame(
        {"open": close, "high": close + 0.5, "low": close - 0.5, "close": close, "volume": 2_000_000.0}
    )


def test_daily_trend_setup_in_the_scan_row_needs_the_50_day_side(monkeypatch):
    """The row's daily_trend (filter, chip and hero count) gates the raw MACD trigger on the 50-day SMA."""
    import strat.scanner as scanner

    member = Member("TEST", "Test", "Industrials", "stock", "SP500")
    rising = _trend_frame([100 + i for i in range(80)])  # last close well above its 50-day SMA
    falling = _trend_frame([200 - i for i in range(80)])  # last close well below it
    for trigger, frame, expected in (
        ("bullish", rising, "bullish"),
        ("bullish", falling, None),
        ("bearish", falling, "bearish"),
        ("bearish", rising, None),
    ):
        monkeypatch.setattr(scanner, "latest_daily_trend", lambda daily, t=trigger: t)
        row = scan_symbol(member, frame)
        assert row["daily_macd_trigger"] == trigger
        assert row["daily_trend"] == expected, (trigger, expected)


def test_row_carries_the_weekly_macd_trend_of_the_week_in_progress():
    from strat.data import resample
    from strat.macd import latest_weekly_trend, weekly_trend_setup

    df = _daily()
    weekly = resample(df, "W", completed_only=False)
    row = scan_symbol(Member("TEST", "Test", "Industrials", "stock", "SP500"), df)
    assert row["weekly_macd_trigger"] == latest_weekly_trend(weekly)
    assert row["weekly_trend"] == weekly_trend_setup(latest_weekly_trend(weekly), weekly)
    assert row["weekly_trend"] in (None, "bullish", "bearish")


def test_weekly_trend_setup_in_the_scan_row_needs_the_10_week_side(monkeypatch):
    import strat.scanner as scanner

    member = Member("TEST", "Test", "Industrials", "stock", "SP500")
    rising = _trend_frame([100 + i for i in range(80)])
    falling = _trend_frame([200 - i for i in range(80)])
    for trigger, frame, expected in (
        ("bullish", rising, "bullish"),
        ("bullish", falling, None),
        ("bearish", falling, "bearish"),
        ("bearish", rising, None),
    ):
        monkeypatch.setattr(scanner, "latest_weekly_trend", lambda weekly, t=trigger: t)
        row = scan_symbol(member, frame)
        assert row["weekly_macd_trigger"] == trigger
        assert row["weekly_trend"] == expected, (trigger, expected)


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


def _setup_weeks(live_highs, live_close=104.0):
    """Filler weeks, a 2U week (Aug 3-7), an inside week (Aug 10-14, high 108), then the week in progress (Aug 17-)."""
    rows = []
    for day in pd.bdate_range("2026-06-01", "2026-07-31"):
        rows.append((day, 100.0, 105.0, 95.0, 100.0))
    for day in pd.bdate_range("2026-08-03", "2026-08-07"):
        rows.append((day, 100.0, 110.0, 96.0, 108.0))
    for day in pd.bdate_range("2026-08-10", "2026-08-14"):
        rows.append((day, 104.0, 108.0, 100.0, 104.0))
    for day, high in zip(pd.bdate_range("2026-08-17", periods=len(live_highs)), live_highs):
        rows.append((day, 104.0, high, 101.0, live_close))
    idx = pd.DatetimeIndex([r[0] for r in rows])
    df = pd.DataFrame([r[1:] for r in rows], index=idx, columns=["open", "high", "low", "close"])
    df["volume"] = 2_000_000.0
    return df


MEMBER = Member("TEST", "Test", "Industrials", "stock", "SP500")


def test_weekly_trigger_breaks_during_the_week_in_progress():
    row = scan_symbol(MEMBER, _setup_weeks([106.0, 107.0, 109.0], live_close=104.0))
    # The trigger is still the completed inside week's high, never the week in progress.
    assert row["setup"] == "Weekly 2-1 → 2-1-2 setup"
    assert row["trigger"] == 108.0
    # Wednesday's high traded through it, so it is triggered even though the close is back below.
    assert row["triggered"] is True
    assert row["triggered_live"] is True
    assert row["trigger_distance_pct"] > 0
    primary = next(s for s in row["setups"] if s["kind"] == "2-1-2-pending")
    assert primary["live"] is True and primary["triggered"] is True
    assert "this week" in primary["detail"]


def test_weekly_trigger_counts_the_live_price_above_it():
    row = scan_symbol(MEMBER, _setup_weeks([106.0, 112.0], live_close=111.0))
    assert row["triggered"] is True
    assert row["trigger"] == 108.0
    assert row["trigger_distance_pct"] < 0


def test_weekly_setup_stays_pending_until_the_week_in_progress_breaks_it():
    row = scan_symbol(MEMBER, _setup_weeks([106.0, 107.0, 108.0]))
    # Touching the trigger is not a break.
    assert row["setup"] == "Weekly 2-1 → 2-1-2 setup"
    assert row["triggered"] is False
    assert row["triggered_live"] is False
    assert all(not s["live"] for s in row["setups"])


def test_a_completed_week_has_no_bar_in_progress():
    """After Friday's close the inside week itself is the last completed bar, so it is the setup (no live break)."""
    from strat.scanner import in_progress_high
    from strat.data import resample

    df = _setup_weeks([])
    assert in_progress_high(df, resample(df, "W"), "W", 104.0) is None
    live = _setup_weeks([106.0, 109.0])
    assert in_progress_high(live, resample(live, "W"), "W", 104.0) == 109.0
    # August is still in progress too: its high so far is the 2U week's 110.
    assert in_progress_high(live, resample(live, "M"), "M", 104.0) == 110.0


def _pattern_days():
    """Filler, then Thu 2026-08-13 a hammer (long lower wick, close at the top) and Fri 2026-08-14 an inside day."""
    rows = [(d, 100.0, 105.0, 95.0, 100.0) for d in pd.bdate_range("2026-06-01", "2026-08-12")]
    rows.append((pd.Timestamp("2026-08-13"), 99.0, 100.2, 90.0, 100.0))  # hammer: lower wick 9, body 1, upper 0.2
    rows.append((pd.Timestamp("2026-08-14"), 98.5, 99.0, 95.0, 96.0))  # inside the hammer's 90-100.2 range, not a hammer
    idx = pd.DatetimeIndex([r[0] for r in rows])
    df = pd.DataFrame([r[1:] for r in rows], index=idx, columns=["open", "high", "low", "close"])
    df["volume"] = 2_000_000.0
    return df


def test_candle_patterns_use_the_last_completed_daily_bar(monkeypatch):
    from datetime import datetime

    import strat.periods as periods
    from strat.scheduler import ET

    df = _pattern_days()
    # After Friday's close the inside day is the last completed bar.
    monkeypatch.setattr(periods, "clock", lambda: datetime(2026, 8, 14, 16, 30, tzinfo=ET))
    after = scan_symbol(MEMBER, df)["candle_patterns"]["D"]
    assert after == {"inside": True, "hammer": False, "date": "2026-08-14"}
    # During Friday's session that bar is still forming, so Thursday's hammer is the last completed one.
    monkeypatch.setattr(periods, "clock", lambda: datetime(2026, 8, 14, 11, 0, tzinfo=ET))
    during = scan_symbol(MEMBER, df)["candle_patterns"]["D"]
    assert during == {"inside": False, "hammer": True, "date": "2026-08-13"}


def test_weekly_candle_patterns_come_from_the_completed_week():
    row = scan_symbol(MEMBER, _setup_weeks([106.0, 107.0]))
    weekly = row["candle_patterns"]["W"]
    # The completed week (Aug 10-14) is the inside week; the week in progress does not count.
    assert weekly["inside"] is True and weekly["date"] == "2026-08-10"
    assert weekly["inside"] == row["tf"]["W"]["inside"] and weekly["hammer"] == row["tf"]["W"]["hammer"]


def test_daily_bar_complete():
    from datetime import date, datetime

    from strat.periods import daily_bar_complete
    from strat.scheduler import ET

    assert not daily_bar_complete(date(2026, 8, 14), datetime(2026, 8, 14, 15, 59, tzinfo=ET))
    assert daily_bar_complete(date(2026, 8, 14), datetime(2026, 8, 14, 16, 0, tzinfo=ET))
    assert daily_bar_complete(date(2026, 8, 13), datetime(2026, 8, 14, 8, 0, tzinfo=ET))
