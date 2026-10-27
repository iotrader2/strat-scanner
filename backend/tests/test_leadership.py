import pandas as pd
import pytest

from strat.leadership import (
    BROKEN,
    LAGGARD,
    LEADER,
    LEADER_MIN_RS,
    WARNING,
    Breakdown,
    assess_breakdown,
    qqq_excess,
    is_leader,
    leader_status,
    long_term_rs,
    trend_metrics,
)


def _frame(closes, high_pad=1.0):
    idx = pd.bdate_range(end="2026-10-15", periods=len(closes))
    close = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame({"open": close, "high": close + high_pad, "low": close - high_pad, "close": close, "volume": 1e6})


UPTREND = [100 + i * 0.5 for i in range(300)]
DOWNTREND = [250 - i * 0.5 for i in range(300)]


class TestTrendMetrics:
    def test_a_steady_uptrend_is_above_rising_stacked_averages_at_its_highs(self):
        t = trend_metrics(_frame(UPTREND, high_pad=0.0))
        assert all(t.above(p) for p in (10, 20, 50))
        assert all(t.rising[p] for p in (10, 20, 50))
        assert t.stacked
        assert t.off_52w_high_pct == 0 and t.off_6m_high_pct == 0

    def test_a_downtrend_is_below_falling_averages_and_far_from_the_highs(self):
        t = trend_metrics(_frame(DOWNTREND, high_pad=0.0))
        assert not any(t.above(p) for p in (10, 20, 50))
        assert not any(t.rising[p] for p in (10, 20, 50))
        assert not t.stacked
        assert t.off_52w_high_pct > t.off_6m_high_pct > 20

    def test_distance_from_the_high_uses_the_intraday_high(self):
        t = trend_metrics(_frame([100.0] * 100, high_pad=5.0))
        assert t.off_52w_high_pct == pytest.approx(5 / 105 * 100, abs=0.01)

    def test_short_history_leaves_the_long_measures_empty(self):
        t = trend_metrics(_frame([100 + i for i in range(30)]))
        assert t.above(10) and t.above(20) and t.above(50) is None
        assert t.rising[20] and t.rising[50] is None
        assert t.off_52w_high_pct is None and t.off_6m_high_pct is None

    def test_empty_frames_have_no_trend(self):
        assert trend_metrics(pd.DataFrame()) is None
        assert trend_metrics(_frame([])) is None


class TestQqqExcess:
    def test_excess_is_measured_against_qqq_only(self):
        perf = {"1m": 10.0, "3m": 30.0, "6m": None}
        qqq = {"1m": 4.0, "3m": 3.0, "6m": 12.0}
        assert qqq_excess(perf, qqq) == {"1m": 6.0, "3m": 27.0, "6m": None}

    def test_a_missing_qqq_period_gives_no_excess_for_it(self):
        assert qqq_excess({"1m": 5.0, "3m": 5.0, "6m": 5.0}, {"1m": 1.0, "3m": None}) == {"1m": 4.0, "3m": None, "6m": None}

    def test_no_qqq_gives_no_excess(self):
        assert qqq_excess({"1m": 5.0, "3m": 5.0, "6m": 5.0}, None) == {"1m": None, "3m": None, "6m": None}


class TestBreakdown:
    def _trend(self, closes, pad=0.0):
        return trend_metrics(_frame(closes, pad))

    def test_a_healthy_leader_has_no_flag(self):
        b = assess_breakdown(self._trend(UPTREND), {"1m": 8.0, "3m": 30.0, "6m": 60.0}, 0.95)
        assert b == Breakdown("none", [])

    def test_losing_the_50_day_is_a_breakdown(self):
        closes = UPTREND + [UPTREND[-1] - 1.5 * i for i in range(1, 30)]
        b = assess_breakdown(self._trend(closes), {"1m": -12.0, "3m": 10.0, "6m": 40.0}, 0.9)
        assert b.level == BROKEN and any("50-day" in r for r in b.reasons)

    def test_a_deep_drawdown_from_the_six_month_high_is_a_breakdown(self):
        closes = UPTREND + [UPTREND[-1] * (1 - 0.01 * i) for i in range(1, 30)]
        b = assess_breakdown(self._trend(closes), {"1m": -20.0, "3m": 5.0, "6m": 30.0}, 0.9)
        assert b.level == BROKEN and any("6-month high" in r for r in b.reasons)

    def test_a_shallow_pullback_under_the_20_day_is_only_a_warning(self):
        closes = UPTREND + [UPTREND[-1] - 8.0] * 3
        t = self._trend(closes)
        assert t.above(50) and t.above(20) is False
        b = assess_breakdown(t, {"1m": 2.0, "3m": 25.0, "6m": 60.0}, 0.9)
        assert b.level == WARNING and "below the 20-day average" in b.reasons

    def test_one_month_turning_negative_while_3m_6m_are_strong_is_flagged(self):
        t = self._trend(UPTREND)
        rolling = assess_breakdown(t, {"1m": -3.0, "3m": 50.0, "6m": 90.0}, 0.9)
        assert rolling.level == WARNING and any("1M -3.0%" in r for r in rolling.reasons)
        weak_anyway = assess_breakdown(t, {"1m": -3.0, "3m": 1.0, "6m": 2.0}, 0.3)
        assert weak_anyway.level == "none"

    def test_missing_trend_is_not_flagged(self):
        assert assess_breakdown(None, {"1m": -50.0, "3m": None, "6m": None}, None).level == "none"


class TestLeaderStatus:
    def test_the_cut_is_the_top_decile_by_default(self):
        assert LEADER_MIN_RS == 0.90

    def test_status_depends_on_rs_and_trend(self):
        healthy, broken = Breakdown("none"), Breakdown(BROKEN)
        assert leader_status(0.95, healthy) == LEADER
        assert leader_status(0.95, Breakdown(WARNING)) == LEADER  # weakening is flagged and penalised, not removed
        assert leader_status(0.95, broken) == BROKEN
        assert leader_status(0.89, healthy) == LAGGARD
        assert leader_status(None, healthy) == LAGGARD
        assert leader_status(0.85, healthy, min_rs=0.8) == LEADER

    def test_is_leader_helper(self):
        assert is_leader(0.92, "none") and is_leader(0.92, "warning")
        assert not is_leader(0.92, "broken") and not is_leader(0.5, "none") and not is_leader(None, "none")
        assert is_leader(0.82, "none", min_rs=0.8)

    def test_leaders_scan_adds_a_score_strictly_above_70(self):
        from strat.leadership import LEADERS_MIN_SCORE, in_leaders_scan

        assert LEADERS_MIN_SCORE == 70.0
        assert not in_leaders_scan(0.92, "none", 70.0)
        assert in_leaders_scan(0.92, "none", 70.1)
        assert in_leaders_scan(0.92, "warning", 85.0)
        assert not in_leaders_scan(0.92, "broken", 95.0)
        assert not in_leaders_scan(0.5, "none", 95.0)
        assert not in_leaders_scan(0.92, "none", None)
        # The leader flag itself does not look at the score.
        assert is_leader(0.92, "none")
        # An RS-line 52-week high admits a name under P90. The score cut and a broken trend still apply.
        assert in_leaders_scan(0.5, "none", 80.0, rs_line_high=True)
        assert in_leaders_scan(None, "warning", 70.1, rs_line_high=True)
        assert not in_leaders_scan(0.5, "none", 70.0, rs_line_high=True)
        assert not in_leaders_scan(0.5, "broken", 95.0, rs_line_high=True)
        # Raising the cut above P90 is not bypassed by the RS line. Lowering it still uses the percentile.
        assert not in_leaders_scan(0.85, "none", 90.0, min_rs=0.97, rs_line_high=True)
        assert in_leaders_scan(0.85, "none", 90.0, min_rs=0.8)


def test_long_term_rs_blends_3m_and_6m_only():
    assert long_term_rs({"1m": 0.0, "3m": 0.8, "6m": 1.0}) == pytest.approx(0.9)
    assert long_term_rs({"1m": 0.5, "3m": None, "6m": 0.7}) == pytest.approx(0.7)
    assert long_term_rs({"1m": 0.5, "3m": None, "6m": None}) is None


class TestRsLineNewHigh:
    def _series(self, values, start="2024-01-02"):
        return pd.Series(values, index=pd.bdate_range(start, periods=len(values)), dtype=float)

    def test_a_high_in_the_last_five_sessions_counts_and_one_just_older_does_not(self):
        from strat.leadership import HIGH_52W_BARS, rs_line_new_high

        n = HIGH_52W_BARS
        bench = self._series([100.0] * n)
        peaked_six_ago = self._series([100.0] * (n - 6) + [130.0] + [110.0] * 5)
        assert rs_line_new_high(peaked_six_ago, bench) is False
        peaked_today = self._series([100.0] * (n - 1) + [130.0])
        assert rs_line_new_high(peaked_today, bench) is True

    def test_missing_benchmark_or_a_short_history_is_false(self):
        from strat.leadership import rs_line_new_high

        close = self._series([float(i) for i in range(300)])
        assert rs_line_new_high(close, None) is False
        assert rs_line_new_high(None, close) is False
        assert rs_line_new_high(close, self._series([1.0] * 40)) is False

    def test_within_a_tenth_of_a_percent_of_the_high_still_counts(self):
        from strat.leadership import HIGH_52W_BARS, rs_line_new_high

        n = HIGH_52W_BARS
        bench = self._series([100.0] * n)
        near = self._series([80.0] * (n - 10) + [100.0] + [90.0] * 8 + [99.95])
        far = self._series([80.0] * (n - 10) + [100.0] + [90.0] * 8 + [99.8])
        assert rs_line_new_high(near, bench) is True
        assert rs_line_new_high(far, bench) is False

    def test_repeated_calls_do_not_keep_the_ratio(self):
        import tracemalloc

        from strat.leadership import rs_line_new_high

        n = 800
        idx = pd.bdate_range("2023-01-02", periods=n)
        close = pd.Series(range(n), index=idx, dtype=float)
        bench = pd.Series([100.0] * n, index=idx)
        tracemalloc.start()
        rs_line_new_high(close, bench)
        tracemalloc.clear_traces()
        assert all(rs_line_new_high(close, bench) for _ in range(40))
        current, _peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        # A retained copy of the 800-bar inputs, forty times over, would be far past this.
        assert current < 500_000
