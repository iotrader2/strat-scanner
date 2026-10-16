import pandas as pd

from strat.trend import index_trend


def _daily(closes):
    idx = pd.bdate_range(end="2026-10-15", periods=len(closes))
    close = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame({"open": close, "high": close, "low": close, "close": close, "volume": 1.0})


def _flat(level, n=60):
    return [level] * n


def test_game_on_when_every_index_is_above_all_three_averages():
    rising = list(range(1, 61))
    trend = index_trend({s: _daily(rising) for s in ("QQQ", "SPY", "IWM")})
    assert trend["call"] == "on"
    assert [i["symbol"] for i in trend["indexes"]] == ["QQQ", "SPY", "IWM"]
    assert all(a["above"] for i in trend["indexes"] for a in i["averages"])
    assert [a["period"] for a in trend["indexes"][0]["averages"]] == [10, 20, 50]


def test_do_not_trade_when_every_index_is_below_all_three_averages():
    falling = list(range(60, 0, -1))
    trend = index_trend({s: _daily(falling) for s in ("QQQ", "SPY", "IWM")})
    assert trend["call"] == "off"
    assert all(not a["above"] for i in trend["indexes"] for a in i["averages"])


def test_caution_when_the_indexes_disagree():
    history = {"QQQ": _daily(list(range(1, 61))), "SPY": _daily(list(range(60, 0, -1))), "IWM": _daily(_flat(10))}
    assert index_trend(history)["call"] == "caution"


def test_a_flat_market_is_not_game_on_or_do_not_trade():
    # Price sits on each average, so it is neither above nor below them.
    assert index_trend({s: _daily(_flat(10)) for s in ("QQQ", "SPY", "IWM")})["call"] == "caution"


def test_missing_history_hides_the_call():
    short = _daily(_flat(10, n=20))
    assert index_trend({"QQQ": short, "SPY": short, "IWM": short}) is None
    assert index_trend({"QQQ": _daily(_flat(10)), "SPY": _daily(_flat(10))}) is None
