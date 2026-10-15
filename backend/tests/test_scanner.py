import pandas as pd

from strat.scanner import scan_symbol
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


def test_row_carries_score_breakdown():
    row = scan_symbol(Member("TEST", "Test", "Industrials", "stock", "SP500"), _daily())
    assert row["score_max_raw"] == 108
    assert abs(sum(c["points"] for c in row["score_breakdown"]) - row["score_raw"]) < 0.05
    assert {"key", "label", "points", "max_points", "detail"} <= set(row["score_breakdown"][0])
