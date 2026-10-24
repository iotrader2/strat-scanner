import math

import pandas as pd

from strat.scanner import MA_DISTANCE_PERIODS, ma_distance_pct, scan_symbol
from strat.universe import Member


def _closes(values):
    return pd.Series(values, index=pd.bdate_range("2026-01-01", periods=len(values)), dtype=float)


def test_periods_match_the_chart_averages():
    assert MA_DISTANCE_PERIODS == (6, 20, 50)


def test_distance_is_price_minus_sma_over_sma_worked_by_hand():
    # 50 closes: 44 at 100, then 101..106. Price 106.
    closes = _closes([100.0] * 44 + [101, 102, 103, 104, 105, 106])
    out = ma_distance_pct(closes, 106.0)
    # SMA6 = 103.5 -> 2.5 / 103.5 = 2.4155% -> 2.42
    assert out["6"] == 2.42
    # SMA20 = (14*100 + 621)/20 = 101.05 -> 4.95 / 101.05 = 4.8986% -> 4.9
    assert out["20"] == 4.9
    # SMA50 = (44*100 + 621)/50 = 100.42 -> 5.58 / 100.42 = 5.5567% -> 5.56
    assert out["50"] == 5.56


def test_on_just_under_and_above_the_average():
    flat = _closes([50.0] * 60)
    assert ma_distance_pct(flat, 50.0) == {"6": 0.0, "20": 0.0, "50": 0.0}
    assert ma_distance_pct(flat, 49.9) == {"6": -0.2, "20": -0.2, "50": -0.2}
    assert ma_distance_pct(flat, 51.5) == {"6": 3.0, "20": 3.0, "50": 3.0}


def test_short_history_gives_none_for_the_longer_averages():
    out = ma_distance_pct(_closes([10.0 + i for i in range(30)]), 39.0)
    assert out["6"] is not None and out["20"] is not None
    assert out["50"] is None
    assert ma_distance_pct(_closes([10.0] * 5), 10.0) == {"6": None, "20": None, "50": None}


def test_bad_price_or_sma_gives_none():
    assert ma_distance_pct(_closes([10.0] * 60), math.nan) == {"6": None, "20": None, "50": None}
    assert ma_distance_pct(_closes([0.0] * 60), 1.0) == {"6": None, "20": None, "50": None}


def test_nan_closes_are_skipped_not_counted():
    closes = _closes([10.0] * 5 + [math.nan] + [12.0])  # six real closes, SMA6 = 62/6
    assert ma_distance_pct(closes, 12.0)["6"] == round((12.0 - 62 / 6) / (62 / 6) * 100, 2)


def _daily(n):
    idx = pd.bdate_range("2026-03-02", periods=n)
    close = pd.Series([100 + (i % 7) + i * 0.1 for i in range(n)], index=idx, dtype=float)
    return pd.DataFrame({"open": close - 0.5, "high": close + 1, "low": close - 1, "close": close, "volume": 1_000_000.0})


def test_scan_row_carries_the_distance_from_the_row_price():
    df = _daily(80)
    row = scan_symbol(Member("TEST", "Test", "Industrials", "stock", "SP500"), df)
    price = float(df.close.iloc[-1])
    for p in (6, 20, 50):
        sma = df.close.tail(p).mean()
        assert row["ma_dist_pct"][str(p)] == round((price - sma) / sma * 100, 2)


def test_scan_row_with_under_50_bars_has_no_50_distance():
    row = scan_symbol(Member("NEW", "New", "Industrials", "stock", "SP500"), _daily(30))
    assert row["ma_dist_pct"]["50"] is None
    assert row["ma_dist_pct"]["6"] is not None
