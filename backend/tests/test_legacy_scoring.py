import pytest

from strat.ariel_setups import SETUP_POINTS
from strat.candles import Candle, Setup, timeframe_state
from strat.perf import MomentumRanks
from strat.legacy_scoring import (
    ETF_MAX_RAW_POINTS,
    MAX_RAW_POINTS,
    MONTHLY_2U_POINTS,
    MOMENTUM_POINTS,
    THEME_MAX_RAW_POINTS,
    ThemeStrength,
    liquidity_points,
    score_symbol,
)

TOP_THEME = ThemeStrength("memory", "Memory & storage", 80.0, 1, 82, "memory", 80.0, "Memory & storage")
TOP_MOMENTUM = MomentumRanks.from_perf({"stock": {"A": {"1m": 1.0, "3m": 1.0, "6m": 1.0}, "B": {"1m": 9.0, "3m": 9.0, "6m": 9.0}}})


def _states(m, w, d):
    return {"M": timeframe_state("M", m), "W": timeframe_state("W", w), "D": timeframe_state("D", d)}


def _with_setup(states, tf, *setups):
    """Inject Ariel ``Setup`` objects into one timeframe state (the scanner now attaches daily Ariel setups itself)."""
    from dataclasses import replace

    return {**states, tf: replace(states[tf], setups=list(setups))}


def _ep(trigger=106.0, stop=102.0, triggered=False):
    return Setup("episodic-pivot", "Episodic Pivot", trigger, triggered, stop=stop)


GREEN_UP = [Candle(90, 100, 85, 95), Candle(95, 106, 94, 105)]  # 2U, green, no setup
GREEN_INSIDE_PRIOR = [Candle(90, 110, 85, 105), Candle(100, 108, 95, 104)]  # 1, green, plain prior
RED_DOWN = [Candle(90, 100, 85, 95), Candle(95, 96, 80, 82)]  # 2D, red
INSIDE_GREEN = [Candle(90, 110, 85, 105), Candle(100, 106, 95, 104)]  # 1, green -> inside setup
HAMMER = [Candle(100, 105, 95, 96), Candle(96, 97.2, 89, 97)]  # 2D hammer, green


def test_only_daily_setups_are_ranked():
    daily = score_symbol(_with_setup(_states(GREEN_UP, INSIDE_GREEN, GREEN_UP), "D", _ep()), 104, 1e9)
    assert daily.has_setup
    assert daily.primary.tf == "D"
    assert daily.primary.setup.trigger == 106
    assert all(s.tf == "D" for s in daily.setups)


def test_weekly_and_monthly_only_setups_are_ignored():
    # Setups injected on the Weekly and Monthly states are never ranked: only daily setups count.
    states = _with_setup(_states(GREEN_UP, GREEN_UP, GREEN_UP), "W", _ep())
    states = _with_setup(states, "M", _ep(trigger=90.0, stop=88.0))
    no_setup = score_symbol(states, 104, 1e9)
    assert not no_setup.has_setup
    assert no_setup.primary is None
    assert no_setup.trigger_distance_pct is None
    assert "No daily setup" in no_setup.reasons


def test_daily_ep_is_a_setup():
    s = score_symbol(_with_setup(_states(GREEN_UP, GREEN_UP, GREEN_UP), "D", _ep()), 104, 1e9)
    assert s.primary.setup.kind == "episodic-pivot"
    assert s.primary.setup.trigger == 106.0


def test_monthly_2u_gets_a_strong_boost():
    m2u = score_symbol(_states(GREEN_UP, INSIDE_GREEN, GREEN_UP), 104, 1e9)
    m_inside = score_symbol(_states(GREEN_INSIDE_PRIOR, INSIDE_GREEN, GREEN_UP), 104, 1e9)
    assert m2u.monthly_2u and not m_inside.monthly_2u
    # Both monthly candles are green, so the gap is exactly the Monthly 2U boost.
    assert abs((m2u.score - m_inside.score) - MONTHLY_2U_POINTS * 100 / MAX_RAW_POINTS) < 0.15
    assert "Monthly 2U" in m2u.reasons


def test_full_continuity_beats_red_monthly():
    good = score_symbol(_states(GREEN_UP, INSIDE_GREEN, GREEN_UP), 104, 1e9)
    bad = score_symbol(_states(RED_DOWN, INSIDE_GREEN, GREEN_UP), 104, 1e9)
    assert good.full_continuity and good.mw_green
    assert not bad.mw_green
    assert good.score > bad.score


def test_trigger_closer_to_price_scores_higher():
    near = score_symbol(_with_setup(_states(GREEN_UP, INSIDE_GREEN, GREEN_UP), "D", _ep()), 105.5, 1e9)
    far = score_symbol(_with_setup(_states(GREEN_UP, INSIDE_GREEN, GREEN_UP), "D", _ep()), 100.0, 1e9)
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


def test_reason_leads_with_daily_trigger_and_stop_on_setup():
    s = score_symbol(_with_setup(_states(GREEN_UP, INSIDE_GREEN, GREEN_UP), "D", _ep()), 104, 1e9)
    assert s.reasons[0].startswith("Daily Episodic Pivot — trigger 106.00")
    assert s.primary.setup.stop == 102.0


def test_best_possible_setup_scores_at_most_100():
    top = TOP_MOMENTUM.momentum("stock", {"1m": 99.0, "3m": 99.0, "6m": 99.0})
    # Best case needs two daily setups (EP 23 + 25% of HTF 22 = 28.5, capped at 25) to reach the old >90 bound.
    best = _with_setup(
        _states(GREEN_UP, INSIDE_GREEN, GREEN_UP),
        "D",
        _ep(),
        Setup("high-tight-flag", "High Tight Flag", 110.0, False, stop=105.0),
    )
    s = score_symbol(best, 105.9, 50e9, theme=TOP_THEME, momentum=top)
    assert 90 < s.score <= 100
    etf = score_symbol(best, 105.9, 50e9, kind="etf", momentum=top)
    assert 90 < etf.score <= 100


def test_breakdown_components_sum_to_raw_and_rescale_to_score():
    top = TOP_MOMENTUM.momentum("stock", {"1m": 5.0, "3m": 5.0, "6m": 5.0})
    s = score_symbol(_states(GREEN_UP, INSIDE_GREEN, GREEN_UP), 104, 1e9, theme=TOP_THEME, momentum=top)
    keys = [c.key for c in s.breakdown]
    assert keys == ["monthly_2u", "continuity", "daily_setup", "proximity", "liquidity", "momentum", "theme_strength"]
    assert abs(sum(c.points for c in s.breakdown) - s.raw) < 0.01
    assert abs(s.score - s.raw * 100 / MAX_RAW_POINTS) < 0.06
    assert sum(c.max_points for c in s.breakdown) == MAX_RAW_POINTS == s.max_raw == 163
    for c in s.breakdown:
        assert 0 <= c.points <= c.max_points


def test_etfs_are_scored_without_theme_strength_on_the_123_scale():
    s = score_symbol(_states(GREEN_UP, INSIDE_GREEN, GREEN_UP), 104, 1e9, kind="etf", theme=TOP_THEME)
    assert "theme_strength" not in [c.key for c in s.breakdown]
    assert sum(c.max_points for c in s.breakdown) == ETF_MAX_RAW_POINTS == s.max_raw == 123
    assert abs(s.score - s.raw * 100 / 123) < 0.06


def test_themes_are_scored_without_liquidity_or_theme_strength_on_the_113_scale():
    s = score_symbol(_states(GREEN_UP, INSIDE_GREEN, GREEN_UP), 104, 0.0, kind="theme", theme=TOP_THEME)
    assert [c.key for c in s.breakdown] == ["monthly_2u", "continuity", "daily_setup", "proximity", "momentum"]
    assert sum(c.max_points for c in s.breakdown) == THEME_MAX_RAW_POINTS == s.max_raw == 113
    assert abs(s.score - s.raw * 100 / 113) < 0.06


def test_momentum_component_adds_up_to_15_points_and_rescales_the_score():
    states = _states(GREEN_UP, INSIDE_GREEN, GREEN_UP)
    strong = score_symbol(states, 104, 1e9, momentum=TOP_MOMENTUM.momentum("stock", {"1m": 20.0, "3m": 20.0, "6m": 20.0}))
    weak = score_symbol(states, 104, 1e9, momentum=TOP_MOMENTUM.momentum("stock", {"1m": -20.0, "3m": -20.0, "6m": -20.0}))
    none = score_symbol(states, 104, 1e9)
    pts = lambda s: next(c for c in s.breakdown if c.key == "momentum")
    assert pts(strong).max_points == MOMENTUM_POINTS == 15
    assert pts(strong).points == pytest.approx(15.0)  # above both peers on every period: percentile 1.0
    assert pts(weak).points == pytest.approx(0.0)
    assert "not enough" in pts(none).detail and pts(none).points == 0
    assert strong.raw - weak.raw == pytest.approx(15.0)
    assert strong.score - weak.score == pytest.approx(15 * 100 / MAX_RAW_POINTS, abs=0.1)


def test_breakdown_values_for_known_setup():
    # Monthly 2U green, weekly inside green, daily 2U green; price 104 vs an Episodic Pivot trigger of 106 (1.92% away).
    s = score_symbol(_with_setup(_states(GREEN_UP, INSIDE_GREEN, GREEN_UP), "D", _ep()), 104, 1e9)
    pts = {c.key: c.points for c in s.breakdown}
    assert pts["monthly_2u"] == 20
    assert pts["continuity"] == 12 + 12 + 6 + 8
    assert pts["daily_setup"] == SETUP_POINTS["episodic-pivot"] == 23.0
    assert abs(pts["proximity"] - 15 * (1 - (2 / 104 * 100) / 5)) < 1e-9
    assert abs(pts["liquidity"] - liquidity_points(1e9)) < 1e-9


def test_pinned_penalty_shows_in_breakdown():
    s = score_symbol(_states(GREEN_UP, INSIDE_GREEN, GREEN_UP), 104, 1e9, atr_pct=0.2)
    pinned = next(c for c in s.breakdown if c.key == "pinned")
    before = sum(c.points for c in s.breakdown if c.key != "pinned")
    assert abs(pinned.points + before / 2) < 1e-9
    assert abs(s.raw - before / 2) < 0.01


def test_setup_points_cap_is_explained():
    # An Episodic Pivot (23) plus a High Tight Flag (22): 23 + 25% of 22 = 28.5 -> capped at 25.
    states = _with_setup(
        _states(GREEN_UP, INSIDE_GREEN, GREEN_UP),
        "D",
        _ep(),
        Setup("high-tight-flag", "High Tight Flag", 110.0, False, stop=105.0),
    )
    s = score_symbol(states, 104, 1e9)
    setup = next(c for c in s.breakdown if c.key == "daily_setup")
    assert setup.points == 25
    assert "capped at 25" in setup.detail


def test_legacy_continuity_reads_the_bars_in_progress():
    from dataclasses import replace

    red = _states(RED_DOWN, RED_DOWN, RED_DOWN)
    live = {tf: replace(s, live_color={"M": "green", "W": "green", "D": "red"}[tf], live_open=1.0) for tf, s in red.items()}
    sc = score_symbol(live, 104, 1e9)
    cont = next(c for c in sc.breakdown if c.key == "continuity")
    assert cont.detail.startswith("M +")
    assert sc.mw_green is True and sc.full_continuity is False
    assert next(c for c in score_symbol(red, 104, 1e9).breakdown if c.key == "continuity").points == 0
