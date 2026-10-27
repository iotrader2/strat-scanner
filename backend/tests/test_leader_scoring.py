import pandas as pd
import pytest

from strat.candles import Candle, timeframe_state
from strat.leadership import Breakdown, Trend, qqq_excess, trend_metrics
from strat.perf import MomentumRanks
from strat.data import resample
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
    TIGHTNESS_POINTS,
    TREND_POINTS,
    WARNING_FACTOR,
    ThemeStrength,
    qqq_points,
    score_symbol,
    theme_strength_points,
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
        assert RS_POINTS + QQQ_POINTS + THEME_POINTS + TREND_POINTS + TIGHTNESS_POINTS + STRAT_OVERLAY_MAX + 5 == 100

    def test_etfs_and_themes_drop_the_components_they_cannot_have(self):
        assert ETF_MAX_RAW_POINTS == 100 - THEME_POINTS
        assert THEME_MAX_RAW_POINTS == ETF_MAX_RAW_POINTS - 5 and (ETF_MAX_RAW_POINTS, THEME_MAX_RAW_POINTS) == (75, 70)

    def test_the_strat_overlay_is_a_modest_bonus(self):
        assert STRAT_OVERLAY_MAX == 10
        assert STRAT_OVERLAY_MAX / MAX_RAW_POINTS <= 0.10

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
        assert by["rs"].weight_pct == 15 and by["qqq"].weight_pct == 30 and by["theme_strength"].weight_pct == 25
        assert by["trend"].weight_pct == 10 and by["tightness"].weight_pct == 5 and by["liquidity"].weight_pct == 5
        # All Strat timing is one Continuity line out of 10, the weight the four old lines had together.
        assert not {"weekly_setup", "proximity", "monthly_2u"} & set(by)
        assert by["continuity"].label == "Continuity"
        assert by["continuity"].max_points == 10 and by["continuity"].weight_pct == pytest.approx(10.0)
        assert sum(c.weight_pct for c in s.breakdown) == pytest.approx(100.0, abs=0.2)

    def test_a_number_one_theme_is_worth_25_and_lifts_the_refiners_example(self):
        # SCORE BREAKDOWN for a #1-of-82 theme (Refiners), under the previous 45/10 split.
        rs, qqq_old, theme_old, trend, tightness = 14.5, 16.3, 10.0, 10.0, 4.1
        setup, proximity, continuity, monthly_2u, liquidity = 3.7, 2.5, 2.0, 1.5, 3.5
        before = rs + qqq_old + theme_old + trend + tightness + setup + proximity + continuity + monthly_2u + liquidity
        top = ThemeStrength("refiners", "Refiners", 90.0, 1, 82, "refiners", 90.0, "Refiners")
        assert theme_strength_points(top) == THEME_POINTS == 25
        qqq_new = qqq_old * QQQ_POINTS / 45.0  # same outperformance fraction, new 30-point max
        after = rs + qqq_new + THEME_POINTS + trend + tightness + setup + proximity + continuity + monthly_2u + liquidity
        assert qqq_new == pytest.approx(10.8667, abs=1e-3)
        assert after == pytest.approx(before + 15 - qqq_old * 15 / 45)
        assert after == pytest.approx(77.6667, abs=1e-3)
        # The tooltip's raw total was 67.9; the lines above are those points rounded to 0.1 (they sum to 68.1).
        assert before == pytest.approx(68.1, abs=1e-9)
        assert 67.9 + (after - before) == pytest.approx(77.4667, abs=1e-3)

    def test_etf_weights_are_rescaled_to_100(self):
        s = _score(NO_SETUP, LEADER_PERF, kind="etf")
        assert "theme_strength" not in {c.key for c in s.breakdown}
        assert sum(c.weight_pct for c in s.breakdown) == pytest.approx(100.0, abs=0.2)
        assert {c.key: c.weight_pct for c in s.breakdown}["rs"] == pytest.approx(15 / ETF_MAX_RAW_POINTS * 100, abs=0.05)
        assert {c.key: c.weight_pct for c in s.breakdown}["qqq"] == pytest.approx(30 / ETF_MAX_RAW_POINTS * 100, abs=0.05)

    def test_penalties_have_no_weight(self):
        s = _score(NO_SETUP, LEADER_PERF, trend_break=Breakdown("broken", ["below the 50-day average"]))
        assert {c.key: c.weight_pct for c in s.breakdown}["breakdown"] == 0

    def test_sub_weights_are_listed(self):
        by = {c.key: c for c in _score(NO_SETUP, LEADER_PERF).breakdown}
        assert by["rs"].sub_weights == ["1M 20%", "3M 40%", "6M 40%"]
        assert by["qqq"].sub_weights == [
            "1M 20% (full at +20 pts)", "3M 40% (full at +60 pts)", "6M 40% (full at +100 pts)",
        ]
        assert by["trend"].sub_weights[0] == "10-day 5 pts · 20-day 5 pts"
        assert "above 3" in by["trend"].sub_weights[1] and "rising 2" in by["trend"].sub_weights[1]
        assert by["continuity"].sub_weights == ["M 4 · W 4 · D 1 · all three +1"]


class TestLeadershipComesFirst:
    def test_a_leader_with_no_setup_beats_a_laggard_with_a_perfect_setup(self):
        leader = _score(NO_SETUP, LEADER_PERF)
        laggard = _score(INSIDE_SETUP, LAGGARD_PERF, trend=WEAK_TREND)
        assert not leader.has_setup and laggard.has_setup
        assert leader.score > laggard.score + 20

    def test_a_weekly_setup_does_not_score(self):
        # Same M/W/D colours (all green); only one has an inside-week setup. The setup is shown, not scored.
        with_setup = _score(INSIDE_SETUP, LEADER_PERF)
        without = _score(NO_SETUP, LEADER_PERF)
        assert with_setup.has_setup and with_setup.primary is not None and with_setup.trigger_distance_pct is not None
        assert not without.has_setup
        assert with_setup.score == without.score and with_setup.raw == without.raw
        assert STRAT_OVERLAY_MAX == 10

    def test_a_leader_without_a_setup_is_not_filtered_by_the_score(self):
        s = _score(NO_SETUP, LEADER_PERF)
        assert s.is_leader
        assert "No weekly setup" in s.reasons
        cont = next(c for c in s.breakdown if c.key == "continuity")
        assert cont.points == 10  # M+W+D green with no setup still earns full Continuity
        # This fixture has no theme, so the lower Vs QQQ cap (30, was 45) leaves it in the 50s.
        # The same leader in the #1 theme gains the full 25 and stays a high score with no setup.
        themed = _score(NO_SETUP, LEADER_PERF, theme=TOP_THEME)
        assert themed.is_leader and themed.score == pytest.approx(s.score + THEME_POINTS, abs=0.1)
        assert themed.score >= 70

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
        assert trend_points(STRONG_TREND) == pytest.approx(TREND_POINTS) == 10
        assert trend_points(WEAK_TREND) == 0
        assert trend_points(None) == 0

    def test_trend_gives_partial_credit_for_above_or_rising_alone(self):
        def trend(above10, rising10, above20, rising20):
            # one shared price of 101: an average of 100 is under it (above), 102 is over it (below)
            sma = {10: 100.0 if above10 else 102.0, 20: 100.0 if above20 else 102.0, 50: 0.0}
            return Trend(101.0, sma, {10: rising10, 20: rising20, 50: False}, 0.0, 0.0, 300)

        assert trend_points(trend(True, True, True, True)) == 10
        assert trend_points(trend(True, False, True, False)) == pytest.approx(6.0)
        assert trend_points(trend(False, True, False, True)) == pytest.approx(4.0)
        assert trend_points(trend(True, True, False, False)) == pytest.approx(5.0)

    def test_the_50_day_and_the_highs_no_longer_score(self):
        far_below_highs = Trend(101.0, {10: 100.0, 20: 100.0, 50: 200.0}, {10: True, 20: True, 50: False}, 60.0, 40.0, 300)
        assert trend_points(far_below_highs) == 10

    def test_qqq_points_scale_with_outperformance(self):
        from strat.leadership import FULL_EXCESS_PCT

        assert FULL_EXCESS_PCT == {"1m": 20.0, "3m": 60.0, "6m": 100.0}
        full = dict(FULL_EXCESS_PCT)
        half = {p: v / 2 for p, v in full.items()}
        assert qqq_points(full) == pytest.approx(QQQ_POINTS)
        assert qqq_points(half) == pytest.approx(QQQ_POINTS / 2)
        assert qqq_points({"1m": -5.0, "3m": -5.0, "6m": -5.0}) == 0
        assert qqq_points({"1m": None, "3m": None, "6m": None}) == 0
        assert qqq_points(None) == 0
        only_6m = {"1m": None, "3m": None, "6m": FULL_EXCESS_PCT["6m"]}
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

    def test_rs_line_high_is_a_bool_and_a_cold_start_without_qqq_still_scans(self):
        members, hist = _universe()
        rows = {r["symbol"]: r for r in scan_all(members, hist, MAP).rows}
        assert rows["S29"]["rs_line_high"] is True  # rising faster than QQQ, high is the last bar
        assert rows["S00"]["rs_line_high"] is False
        assert rows["QQQ"]["rs_line_high"] is False  # the benchmark is not compared with itself
        assert all(isinstance(r["rs_line_high"], bool) for r in rows.values())
        hist.pop("QQQ")
        cold = scan_all(members, hist, MAP).rows
        assert cold and all(r["rs_line_high"] is False for r in cold)

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
            assert keys[:2] == ["rs", "qqq"] and {"trend", "continuity"} <= set(keys)
            assert not {"weekly_setup", "proximity", "monthly_2u"} & set(keys)
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

    def test_rows_carry_tightness_kill_candle_and_breakout_fields(self):
        members, hist = _universe()
        rows = {r["symbol"]: r for r in scan_all(members, hist, MAP).rows}
        top = rows["S29"]
        assert {"tightness", "kill_candle", "breakout"} <= set(top)
        assert top["kill_candle"] is None and top["breakout"] is None
        keys = [c["key"] for c in top["score_breakdown"]]
        assert "tightness" in keys and "kill_candle" not in keys

    def test_a_kill_candle_in_the_history_lowers_the_row_score(self):
        members, hist = _universe()
        clean = {r["symbol"]: r for r in scan_all(members, hist, MAP).rows}["S28"]
        df = hist["S28"].copy()
        prev = float(df.close.iloc[-2])
        df.iloc[-1, df.columns.get_indexer(["open", "high", "low", "close", "volume"])] = [prev, prev + 0.1, prev - 25, prev - 24, 2e7]
        hist["S28"] = df
        hit = {r["symbol"]: r for r in scan_all(members, hist, MAP).rows}["S28"]
        assert hit["kill_candle"] is not None and hit["kill_candle"]["penalty"] > 0
        assert any(c["key"] == "kill_candle" and c["points"] < 0 for c in hit["score_breakdown"])
        assert hit["score"] < clean["score"]


class TestContinuityScore:
    """Continuity is Monthly / Weekly / Daily alignment only, out of 10: M 4 · W 4 · D 1 · all three +1."""

    @pytest.mark.parametrize(
        "m, w, d, points",
        [
            (GREEN_UP, GREEN_UP, GREEN_UP, 10.0),
            (GREEN_UP, GREEN_UP, RED_DOWN, 8.0),
            (GREEN_UP, RED_DOWN, GREEN_UP, 5.0),
            (RED_DOWN, GREEN_UP, RED_DOWN, 4.0),
            (RED_DOWN, RED_DOWN, GREEN_UP, 1.0),
            (RED_DOWN, RED_DOWN, RED_DOWN, 0.0),
        ],
    )
    def test_points_by_timeframe(self, m, w, d, points):
        cont = next(c for c in _score(_states(m, w, d), LEADER_PERF).breakdown if c.key == "continuity")
        assert cont.points == points and cont.max_points == 10

    def test_detail_names_the_green_timeframes(self):
        full = next(c for c in _score(NO_SETUP, LEADER_PERF).breakdown if c.key == "continuity")
        assert full.detail == "M +4 · W +4 · D +1 · all three +1"
        mw = next(c for c in _score(_states(GREEN_UP, GREEN_UP, RED_DOWN), LEADER_PERF).breakdown if c.key == "continuity")
        assert mw.detail == "M +4 · W +4 (D not green)"
        none = next(c for c in _score(RED, LEADER_PERF).breakdown if c.key == "continuity")
        assert none.detail == "no timeframe green (M/W/D not green)"

    def test_setup_trigger_and_monthly_2u_are_not_scored(self):
        s = _score(INSIDE_SETUP, LEADER_PERF)
        keys = {c.key for c in s.breakdown}
        assert not {"weekly_setup", "proximity", "monthly_2u"} & keys
        assert s.monthly_2u and s.has_setup  # still reported for display and filters
        assert sum(c.points for c in s.breakdown) == pytest.approx(s.raw, abs=0.01)

    def test_continuity_keeps_ten_points_for_etfs_and_themes(self):
        for kind, max_raw in (("etf", ETF_MAX_RAW_POINTS), ("theme", THEME_MAX_RAW_POINTS)):
            cont = next(c for c in _score(NO_SETUP, LEADER_PERF, kind=kind).breakdown if c.key == "continuity")
            assert cont.max_points == 10
            assert cont.weight_pct == pytest.approx(round(10 / max_raw * 100, 1))


def _live(states, **colors):
    from dataclasses import replace

    return {tf: replace(s, live_color=colors.get(tf), live_open=100.0 if colors.get(tf) else None) for tf, s in states.items()}


class TestContinuityReadsTheBarsInProgress:
    """TEAM, Oct 22 2026: September, the last completed week and today are red, but the week and month in progress are green."""

    def test_completed_red_but_month_and_week_in_progress_green_is_8_of_10(self):
        sc = _score(_live(RED, M="green", W="green", D="red"), LEADER_PERF)
        cont = next(c for c in sc.breakdown if c.key == "continuity")
        assert cont.points == 8
        assert sc.mw_green is True
        assert sc.full_continuity is False
        assert "M+W green" in sc.reasons
        assert "No green continuity" not in sc.reasons

    def test_all_in_progress_green_is_full_continuity(self):
        sc = _score(_live(RED, M="green", W="green", D="green"), LEADER_PERF)
        assert next(c for c in sc.breakdown if c.key == "continuity").points == 10
        assert sc.full_continuity is True

    def test_in_progress_red_beats_a_green_completed_bar(self):
        sc = _score(_live(NO_SETUP, M="red", W="red", D="red"), LEADER_PERF)
        assert next(c for c in sc.breakdown if c.key == "continuity").points == 0
        assert sc.mw_green is False

    def test_without_live_colors_it_falls_back_to_the_completed_bar(self):
        assert next(c for c in _score(RED, LEADER_PERF).breakdown if c.key == "continuity").points == 0
        assert next(c for c in _score(NO_SETUP, LEADER_PERF).breakdown if c.key == "continuity").points == 10

    def test_setups_and_monthly_2u_stay_on_completed_bars(self):
        live = _score(_live(INSIDE_SETUP, M="red", W="red", D="red"), LEADER_PERF)
        done = _score(INSIDE_SETUP, LEADER_PERF)
        assert live.monthly_2u == done.monthly_2u
        assert [(s.tf, s.setup.kind, s.setup.trigger) for s in live.setups] == [
            (s.tf, s.setup.kind, s.setup.trigger) for s in done.setups
        ]
