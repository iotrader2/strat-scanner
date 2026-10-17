import pandas as pd
import pytest

from strat.candles import Candle, timeframe_state
from strat.leadership import Breakdown, Trend, qqq_excess, trend_metrics
from strat.perf import MomentumRanks
from strat.scanner import LEGACY, scan_all, scan_symbol
from strat.scoring import (
    QQQ_POINTS,
    BROKEN_FACTOR,
    ETF_MAX_RAW_POINTS,
    MAX_RAW_POINTS,
    RS_POINTS,
    STRAT_OVERLAY_MAX,
    THEME_MAX_RAW_POINTS,
    THEME_POINTS,
    TREND_POINTS,
    WARNING_FACTOR,
    ThemeStrength,
    qqq_points,
    score_symbol,
    trend_points,
)
from strat.themes import parse_themes
from strat.universe import Member

PEERS = {
    "stock": {f"S{i}": {"1m": float(i), "3m": float(i), "6m": float(i)} for i in range(100)},
}
RANKS = MomentumRanks.from_perf(PEERS)
LEADER_PERF = {"1m": 95.0, "3m": 95.0, "6m": 95.0}  # P96
LAGGARD_PERF = {"1m": 10.0, "3m": 10.0, "6m": 10.0}  # P10
QQQ = {"1m": 2.0, "3m": 4.0, "6m": 8.0}


def _states(m, w, d):
    return {"M": timeframe_state("M", m), "W": timeframe_state("W", w), "D": timeframe_state("D", d)}


GREEN_UP = [Candle(90, 100, 85, 95), Candle(95, 106, 94, 105)]  # 2U, green, no setup
INSIDE_GREEN = [Candle(90, 110, 85, 105), Candle(100, 106, 95, 104)]  # 1, green -> inside setup
RED_DOWN = [Candle(90, 100, 85, 95), Candle(95, 96, 80, 82)]  # 2D, red

NO_SETUP = _states(GREEN_UP, GREEN_UP, GREEN_UP)
INSIDE_SETUP = _states(GREEN_UP, INSIDE_GREEN, GREEN_UP)
RED = _states(RED_DOWN, RED_DOWN, RED_DOWN)


def _frame(closes):
    idx = pd.bdate_range(end="2026-10-15", periods=len(closes))
    close = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame({"open": close, "high": close, "low": close, "close": close, "volume": 1e6})


STRONG_TREND = trend_metrics(_frame([100 + i * 0.5 for i in range(300)]))
WEAK_TREND = trend_metrics(_frame([250 - i * 0.5 for i in range(300)]))


def _score(states, perf, trend=STRONG_TREND, trend_break=None, kind="stock", theme=None, **kw):
    return score_symbol(
        states, 105.0, 1e9, kind=kind, momentum=RANKS.momentum(kind, perf), trend=trend,
        excess=qqq_excess({"1m": perf["1m"], "3m": perf["3m"], "6m": perf["6m"]}, QQQ),
        trend_break=trend_break, theme=theme, **kw,
    )


TOP_THEME = ThemeStrength("memory", "Memory", 90.0, 1, 40, "memory", 90.0, "Memory")


class TestScale:
    def test_components_add_up_to_exactly_100_for_stocks(self):
        assert MAX_RAW_POINTS == 100
        assert RS_POINTS + QQQ_POINTS + THEME_POINTS + TREND_POINTS + STRAT_OVERLAY_MAX + 5 == 100

    def test_etfs_and_themes_drop_the_components_they_cannot_have(self):
        assert ETF_MAX_RAW_POINTS == 100 - THEME_POINTS
        assert THEME_MAX_RAW_POINTS == ETF_MAX_RAW_POINTS - 5

    def test_the_strat_overlay_is_a_modest_bonus(self):
        assert STRAT_OVERLAY_MAX == 15
        assert STRAT_OVERLAY_MAX / MAX_RAW_POINTS <= 0.15

    def test_leadership_is_most_of_the_score(self):
        assert (RS_POINTS + QQQ_POINTS + THEME_POINTS + TREND_POINTS) >= 0.75 * MAX_RAW_POINTS

    def test_a_perfect_name_scores_100(self):
        s = _score(
            _states(GREEN_UP, INSIDE_GREEN, GREEN_UP), {"1m": 99.0, "3m": 99.0, "6m": 99.0}, theme=TOP_THEME,
        )
        assert s.score <= 100.0
        assert [c.key for c in s.breakdown][:4] == ["rs", "qqq", "theme_strength", "trend"]


class TestWeights:
    def test_stock_weights_are_the_max_points_and_add_up_to_100(self):
        s = _score(NO_SETUP, LEADER_PERF, theme=TOP_THEME, theme_name="Memory")
        by = {c.key: c for c in s.breakdown}
        assert by["rs"].weight_pct == 32 and by["qqq"].weight_pct == 15 and by["theme_strength"].weight_pct == 20
        assert by["trend"].weight_pct == 13 and by["liquidity"].weight_pct == 5
        assert sum(c.weight_pct for c in s.breakdown) == pytest.approx(100.0, abs=0.2)

    def test_etf_weights_are_rescaled_to_100(self):
        s = _score(NO_SETUP, LEADER_PERF, kind="etf")
        assert "theme_strength" not in {c.key for c in s.breakdown}
        assert sum(c.weight_pct for c in s.breakdown) == pytest.approx(100.0, abs=0.2)
        assert {c.key: c.weight_pct for c in s.breakdown}["rs"] == pytest.approx(32 / 80 * 100, abs=0.05)

    def test_penalties_have_no_weight(self):
        s = _score(NO_SETUP, LEADER_PERF, trend_break=Breakdown("broken", ["below the 50-day average"]))
        assert {c.key: c.weight_pct for c in s.breakdown}["breakdown"] == 0

    def test_sub_weights_are_listed(self):
        by = {c.key: c for c in _score(NO_SETUP, LEADER_PERF).breakdown}
        assert by["rs"].sub_weights == ["1M 20%", "3M 40%", "6M 40%"]
        assert by["qqq"].sub_weights == [
            "1M 20% (full at +15 pts)", "3M 40% (full at +40 pts)", "6M 40% (full at +70 pts)",
        ]
        assert by["trend"].sub_weights[0] == "10-day 6.5 pts · 20-day 6.5 pts"
        assert "above 4" in by["trend"].sub_weights[1] and "rising 2.5" in by["trend"].sub_weights[1]
        assert by["continuity"].sub_weights[-1] == "all three +0.5"


class TestLeadershipComesFirst:
    def test_a_leader_with_no_setup_beats_a_laggard_with_a_perfect_setup(self):
        leader = _score(NO_SETUP, LEADER_PERF)
        laggard = _score(INSIDE_SETUP, LAGGARD_PERF, trend=WEAK_TREND)
        assert not leader.has_setup and laggard.has_setup
        assert leader.score > laggard.score + 20

    def test_the_setup_is_a_bonus_of_at_most_the_overlay(self):
        with_setup = _score(INSIDE_SETUP, LEADER_PERF)
        without = _score(NO_SETUP, LEADER_PERF)
        gap = with_setup.score - without.score
        assert 0 < gap <= STRAT_OVERLAY_MAX

    def test_a_leader_without_a_setup_is_not_filtered_by_the_score(self):
        s = _score(NO_SETUP, LEADER_PERF)
        assert s.is_leader and s.score >= 60
        assert "No weekly setup" in s.reasons
        setup_part = next(c for c in s.breakdown if c.key == "weekly_setup")
        assert setup_part.points == 0 and "leader still scores" in setup_part.detail

    def test_relative_strength_dominates_between_otherwise_equal_names(self):
        hi, lo = _score(NO_SETUP, LEADER_PERF), _score(NO_SETUP, LAGGARD_PERF)
        rs = lambda s: next(c for c in s.breakdown if c.key == "rs").points  # noqa: E731
        assert rs(hi) == pytest.approx(RS_POINTS * 0.955, abs=0.2) and rs(lo) == pytest.approx(RS_POINTS * 0.105, abs=0.2)
        assert hi.score - lo.score > 25

    def test_status_follows_the_rs_percentile(self):
        assert _score(NO_SETUP, LEADER_PERF).status == "leader"
        assert _score(NO_SETUP, LAGGARD_PERF).status == "laggard"
        assert _score(NO_SETUP, LEADER_PERF).rs == pytest.approx(0.955)


class TestComponents:
    def test_trend_points_use_only_the_rising_10_and_20_day_averages(self):
        assert trend_points(STRONG_TREND) == pytest.approx(TREND_POINTS) == 13
        assert trend_points(WEAK_TREND) == 0
        assert trend_points(None) == 0

    def test_trend_gives_partial_credit_for_above_or_rising_alone(self):
        def trend(above10, rising10, above20, rising20):
            # one shared price of 101: an average of 100 is under it (above), 102 is over it (below)
            sma = {10: 100.0 if above10 else 102.0, 20: 100.0 if above20 else 102.0, 50: 0.0}
            return Trend(101.0, sma, {10: rising10, 20: rising20, 50: False}, 0.0, 0.0, 300)

        assert trend_points(trend(True, True, True, True)) == 13
        assert trend_points(trend(True, False, True, False)) == pytest.approx(8.0)
        assert trend_points(trend(False, True, False, True)) == pytest.approx(5.0)
        assert trend_points(trend(True, True, False, False)) == pytest.approx(6.5)

    def test_the_50_day_and_the_highs_no_longer_score(self):
        far_below_highs = Trend(101.0, {10: 100.0, 20: 100.0, 50: 200.0}, {10: True, 20: True, 50: False}, 60.0, 40.0, 300)
        assert trend_points(far_below_highs) == 13

    def test_qqq_points_scale_with_outperformance(self):
        full = {"1m": 15.0, "3m": 40.0, "6m": 70.0}
        half = {p: v / 2 for p, v in full.items()}
        assert qqq_points(full) == pytest.approx(QQQ_POINTS)
        assert qqq_points(half) == pytest.approx(QQQ_POINTS / 2)
        assert qqq_points({"1m": -5.0, "3m": -5.0, "6m": -5.0}) == 0
        assert qqq_points({"1m": None, "3m": None, "6m": None}) == 0
        assert qqq_points(None) == 0
        only_6m = {"1m": None, "3m": None, "6m": 70.0}
        assert qqq_points(only_6m) == pytest.approx(QQQ_POINTS)  # weights are renormalised

    def test_tooltip_details_name_the_inputs(self):
        s = _score(NO_SETUP, LEADER_PERF, theme=TOP_THEME, theme_name="Memory")
        by = {c.key: c for c in s.breakdown}
        assert "P96" in by["rs"].label and "percentile among 100 stocks" in by["rs"].detail
        assert "minus QQQ" in by["qqq"].detail and by["qqq"].label == "Vs QQQ"
        assert "#1 of 40" in by["theme_strength"].label
        assert by["trend"].detail == "10-day above & rising; 20-day above & rising"

    def test_missing_inputs_score_zero_with_a_reason(self):
        s = score_symbol(NO_SETUP, 105.0, 1e9)
        by = {c.key: c for c in s.breakdown}
        assert by["rs"].points == 0 and "not enough price history" in by["rs"].detail
        assert by["trend"].points == 0 and by["qqq"].points == 0
        assert s.rs is None and s.status == "laggard"


class TestBreakdownDemotion:
    def test_a_broken_leader_is_halved_and_removed_from_the_leaders(self):
        ok = _score(NO_SETUP, LEADER_PERF)
        broken = _score(NO_SETUP, LEADER_PERF, trend_break=Breakdown("broken", ["below the 50-day average"]))
        assert broken.score == pytest.approx(ok.score * BROKEN_FACTOR, abs=0.1)
        assert broken.status == "broken" and not broken.is_leader
        part = next(c for c in broken.breakdown if c.key == "breakdown")
        assert part.points < 0 and "50-day" in part.detail and part.label == "Breakdown penalty"
        assert any(r.startswith("Broken:") for r in broken.reasons)

    def test_a_weakening_leader_is_trimmed_but_stays_listed(self):
        ok = _score(NO_SETUP, LEADER_PERF)
        weak = _score(NO_SETUP, LEADER_PERF, trend_break=Breakdown("warning", ["below the 20-day average"]))
        assert weak.score == pytest.approx(ok.score * WARNING_FACTOR, abs=0.1)
        assert weak.status == "leader"
        assert any(r.startswith("Weakening:") for r in weak.reasons)

    def test_the_breakdown_line_is_absent_for_healthy_names(self):
        assert "breakdown" not in [c.key for c in _score(NO_SETUP, LEADER_PERF).breakdown]

    def test_the_total_still_adds_up(self):
        s = _score(INSIDE_SETUP, LEADER_PERF, trend_break=Breakdown("broken", ["x"]))
        assert sum(c.points for c in s.breakdown) == pytest.approx(s.raw, abs=0.05)
        assert 0 <= s.score <= 100


class TestKinds:
    def test_etfs_have_no_theme_strength_and_themes_no_liquidity(self):
        etf = _score(NO_SETUP, LEADER_PERF, kind="etf")
        assert "theme_strength" not in [c.key for c in etf.breakdown] and etf.max_raw == ETF_MAX_RAW_POINTS
        theme = score_symbol(NO_SETUP, 105.0, 0.0, kind="theme")
        assert "liquidity" not in [c.key for c in theme.breakdown] and theme.max_raw == THEME_MAX_RAW_POINTS


# ---- the full scan -------------------------------------------------------------------------------------------------

def _history(drift, n=320, noise=0.0, end="2026-10-15"):
    idx = pd.bdate_range(end=end, periods=n)
    close = pd.Series([100 + i * drift + (i % 4) * noise for i in range(n)], index=idx, dtype=float)
    return pd.DataFrame({"open": close, "high": close + 2, "low": close - 2, "close": close, "volume": 3_000_000.0})


def _universe(n=30):
    members = [Member(f"S{i:02d}", f"S{i:02d}", "Information Technology", "stock", "SP500") for i in range(n)]
    members += [Member("SPY", "SPY", "Other", "etf", "benchmark"), Member("QQQ", "QQQ", "Other", "etf", "benchmark")]
    hist = {f"S{i:02d}": _history(-0.1 + i * 0.05) for i in range(n)}
    hist["SPY"], hist["QQQ"] = _history(0.1), _history(0.12)
    return members, hist


MAP = parse_themes(
    {
        "version": 1,
        "themes": {
            "up": {"name": "Risers", "members": "S27 S28 S29"},
            "down": {"name": "Fallers", "members": "S00 S01 S02"},
        },
    }
)


class TestScan:
    def test_the_strongest_names_are_the_leaders_and_need_no_weekly_setup(self):
        members, hist = _universe()
        rows = {r["symbol"]: r for r in scan_all(members, hist, MAP).rows}
        leaders = [s for s, r in rows.items() if r["is_leader"] and r["kind"] == "stock"]
        assert set(leaders) >= {"S29", "S28", "S27"} and "S00" not in leaders
        assert len(leaders) <= 4  # top decile of 30 stocks
        top = rows["S29"]
        assert top["leader_status"] == "leader" and top["rs"] > 0.9
        assert not top["has_setup"] and top["setup"] is None
        assert top["leadership"]["above_ma"] == {"10": True, "20": True, "50": True}
        assert top["leadership"]["breakdown"] == "none"

    def test_a_leader_with_no_setup_shows_its_nearest_trigger(self):
        members, hist = _universe()
        rows = {r["symbol"]: r for r in scan_all(members, hist, MAP).rows}
        top = rows["S29"]
        assert top["trigger"] is None and top["trigger_distance_pct"] is None
        assert top["nearest_trigger"] is not None and top["nearest_trigger"] > top["price"]
        assert top["nearest_trigger_label"] in {"this week's high", "last week's high"}
        assert top["nearest_trigger_distance_pct"] > 0

    def test_ranking_is_by_leadership_score(self):
        members, hist = _universe()
        rows = scan_all(members, hist, MAP).rows
        stocks = [r for r in rows if r["kind"] == "stock"]
        assert [r["symbol"] for r in stocks[:3]] == ["S29", "S28", "S27"]
        assert stocks[0]["score"] > stocks[-1]["score"] + 30

    def test_a_leader_that_fell_apart_is_demoted_and_flagged(self):
        members, hist = _universe()
        crash = hist["S29"].copy()
        crash.iloc[-25:, crash.columns.get_indexer(["open", "high", "low", "close"])] *= 0.6
        hist["S29"] = crash
        rows = {r["symbol"]: r for r in scan_all(members, hist, MAP).rows}
        broken = rows["S29"]
        assert broken["leadership"]["breakdown"] == "broken" and broken["is_leader"] is False
        assert broken["leadership"]["breakdown_reasons"]
        assert broken["score"] < rows["S28"]["score"]
        assert any(c["key"] == "breakdown" and c["points"] < 0 for c in broken["score_breakdown"])

    def test_row_scores_are_0_to_100_with_a_breakdown_of_the_new_components(self):
        members, hist = _universe()
        for r in scan_all(members, hist, MAP).rows:
            assert 0 <= r["score"] <= 100
            keys = [c["key"] for c in r["score_breakdown"]]
            assert keys[:2] == ["rs", "qqq"] and {"trend", "weekly_setup", "proximity"} <= set(keys)
            assert sum(c["points"] for c in r["score_breakdown"]) == pytest.approx(r["score_raw"], abs=0.1)

    def test_theme_strength_comes_from_the_themes_leadership_rank(self):
        members, hist = _universe()
        result = scan_all(members, hist, MAP)
        assert result.strengths["up"].rank == 1 and result.strengths["down"].rank == 2
        rows = {r["symbol"]: r for r in result.rows}
        pts = lambda sym: next(c for c in rows[sym]["score_breakdown"] if c["key"] == "theme_strength")["points"]  # noqa: E731
        assert pts("S29") == pytest.approx(THEME_POINTS) and pts("S00") == pytest.approx(THEME_POINTS / 2)

    def test_the_legacy_method_keeps_the_old_scale(self):
        members, hist = _universe()
        row = scan_symbol(members[0], hist["S00"], method=LEGACY)
        assert row["score_max_raw"] == 163
        assert "momentum" in [c["key"] for c in row["score_breakdown"]]
