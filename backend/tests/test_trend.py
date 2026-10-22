import pandas as pd

from strat.trend import SCORE_MAX, index_points, index_trend


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
    assert [a["period"] for a in trend["indexes"][0]["averages"]] == [6, 20, 50]


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


def test_index_points_are_price_over_6_and_6_over_20():
    assert index_points(11, 10, 9) == {"above_short": True, "short_over_mid": True, "points": 2}
    assert index_points(9, 10, 9) == {"above_short": False, "short_over_mid": True, "points": 1}
    assert index_points(11, 10, 12) == {"above_short": True, "short_over_mid": False, "points": 1}
    assert index_points(9, 10, 12)["points"] == 0
    # Sitting exactly on an average does not score.
    assert index_points(10, 10, 10)["points"] == 0


def test_score_is_six_when_everything_is_rising_and_zero_when_falling():
    up = index_trend({s: _daily(list(range(1, 61))) for s in ("QQQ", "SPY", "IWM")})
    down = index_trend({s: _daily(list(range(60, 0, -1))) for s in ("QQQ", "SPY", "IWM")})
    assert SCORE_MAX == 6
    assert (up["score"], up["score_max"]) == (6, 6)
    assert [i["points"] for i in up["indexes"]] == [2, 2, 2]
    assert down["score"] == 0


def test_score_adds_up_per_index():
    history = {"QQQ": _daily(list(range(1, 61))), "SPY": _daily(list(range(60, 0, -1))), "IWM": _daily(_flat(10))}
    trend = index_trend(history)
    assert [i["points"] for i in trend["indexes"]] == [2, 0, 0]
    assert trend["score"] == 2


def test_card_price_overrides_the_last_close():
    rising = list(range(1, 61))  # 6-day SMA 57.5, 20-day 50.5
    history = {s: _daily(rising) for s in ("QQQ", "SPY", "IWM")}
    trend = index_trend(history, {"QQQ": 50.0})
    qqq = trend["indexes"][0]
    assert qqq["price"] == 50.0
    assert (qqq["above_short"], qqq["short_over_mid"], qqq["points"]) == (False, True, 1)
    assert trend["score"] == 5
    assert trend["call"] == "caution"
