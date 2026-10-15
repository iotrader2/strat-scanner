from strat.candles import Candle, timeframe_state
from strat.scoring import liquidity_points, score_symbol


def _states(m, w, d):
    return {"M": timeframe_state("M", m), "W": timeframe_state("W", w), "D": timeframe_state("D", d)}


GREEN_UP = [Candle(90, 100, 85, 95), Candle(95, 106, 94, 105)]
RED_DOWN = [Candle(90, 100, 85, 95), Candle(95, 96, 80, 82)]
INSIDE_GREEN = [Candle(90, 110, 85, 105), Candle(100, 106, 95, 104)]


def test_full_continuity_beats_red_monthly():
    good = score_symbol(_states(GREEN_UP, GREEN_UP, GREEN_UP), 105, 1e9)
    bad = score_symbol(_states(RED_DOWN, GREEN_UP, GREEN_UP), 105, 1e9)
    assert good.full_continuity and good.mw_green
    assert not bad.mw_green
    assert good.score > bad.score


def test_higher_timeframe_inside_bar_ranks_higher():
    weekly_inside = score_symbol(_states(GREEN_UP, INSIDE_GREEN, GREEN_UP), 104, 1e9)
    daily_inside = score_symbol(_states(GREEN_UP, GREEN_UP, INSIDE_GREEN), 104, 1e9)
    assert weekly_inside.score > daily_inside.score
    assert weekly_inside.primary.tf == "W"
    assert weekly_inside.primary.setup.trigger == 106


def test_trigger_closer_to_price_scores_higher():
    near = score_symbol(_states(GREEN_UP, INSIDE_GREEN, GREEN_UP), 105.5, 1e9)
    far = score_symbol(_states(GREEN_UP, INSIDE_GREEN, GREEN_UP), 100.0, 1e9)
    assert near.trigger_distance_pct < far.trigger_distance_pct
    assert near.score > far.score


def test_liquidity_points_are_monotonic_and_capped():
    assert liquidity_points(10e6) == 0
    assert 0 < liquidity_points(200e6) < liquidity_points(2e9) <= liquidity_points(50e9) == 10


def test_pinned_low_volatility_name_is_penalised():
    normal = score_symbol(_states(GREEN_UP, INSIDE_GREEN, GREEN_UP), 104, 1e9, atr_pct=2.0)
    pinned = score_symbol(_states(GREEN_UP, INSIDE_GREEN, GREEN_UP), 104, 1e9, atr_pct=0.2)
    assert pinned.score < normal.score
    assert any("low volatility" in r for r in pinned.reasons)


def test_reason_mentions_trigger_without_stop():
    s = score_symbol(_states(GREEN_UP, INSIDE_GREEN, GREEN_UP), 104, 1e9)
    text = " ".join(s.reasons)
    assert "trigger 106.00" in text
    assert "stop" not in text.lower()
