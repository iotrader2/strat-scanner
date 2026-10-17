import dataclasses

import pandas as pd
import pytest

from strat import breakout as bo
from strat.pricebehavior import KillCandle


def _daily(weeks, wild_weeks, base_weeks, breakout_close=112.0, breakout_vol_x=3.0, breakout_pos=0.9, end_friday="2026-10-09"):
    """Wild early weeks, ``base_weeks`` tight weeks around 100, then a breakout week."""
    total = weeks
    idx = pd.bdate_range(end=end_friday, periods=total * 5)
    rows = []
    for w in range(total):
        wk_from_end = total - 1 - w
        for d in range(5):
            if wk_from_end == 0:
                lo, hi = 100.0, breakout_close + 0.0
                close = lo + breakout_pos * (hi - lo) if d == 4 else 101.0 + d
                high, low = max(close, hi if d == 4 else close) + 0.1, 100.0
                vol = 1e6 * breakout_vol_x
            elif wk_from_end <= base_weeks:
                close = 100.0 + (d % 2) * 0.3
                high, low, vol = close + 0.6, close - 0.6, 1e6
            else:
                close = 100.0 + ((w + d) % 3) * 4 - 4
                high, low, vol = close + 4.0, close - 4.0, 1e6
            rows.append((close, high, low, close, vol))
    return pd.DataFrame(rows, index=idx, columns=["open", "high", "low", "close", "volume"])


class TestFindBreakout:
    def test_a_close_above_a_tight_base_on_heavy_volume_is_a_breakout(self):
        b = bo.find_breakout(_daily(40, 30, 6))
        assert b is not None
        assert b.weeks_ago == 0 and bo.BASE_MIN_WEEKS <= b.base_weeks <= bo.BASE_MAX_WEEKS
        assert b.close > b.base_high and b.volume_x >= bo.BREAKOUT_VOLUME_X and b.close_position >= bo.BREAKOUT_CLOSE_POSITION
        assert b.tightness < bo.BASE_TIGHT_RATIO

    def test_the_breakout_stays_listed_for_the_next_two_weeks_only(self):
        df = _daily(40, 30, 6)
        nxt = pd.bdate_range(df.index[-1] + pd.Timedelta(days=3), periods=5)
        extra = pd.DataFrame({"open": 111.0, "high": 112.0, "low": 110.5, "close": 111.5, "volume": 1e6}, index=nxt)
        one_week_later = pd.concat([df, extra])
        b = bo.find_breakout(one_week_later)
        assert b is not None and b.weeks_ago == 1
        nxt2 = pd.bdate_range(nxt[-1] + pd.Timedelta(days=3), periods=10)
        extra2 = pd.DataFrame({"open": 111.0, "high": 112.0, "low": 110.5, "close": 111.5, "volume": 1e6}, index=nxt2)
        assert bo.find_breakout(pd.concat([df, extra, extra2])) is None

    @pytest.mark.parametrize(
        "kw",
        [dict(breakout_vol_x=1.2), dict(breakout_close=100.4), dict(breakout_pos=0.3)],
        ids=["light volume", "no close above the base", "weak close"],
    )
    def test_every_condition_is_required(self, kw):
        assert bo.find_breakout(_daily(40, 30, 6, **kw)) is None

    def test_a_loose_base_is_not_tight(self):
        assert bo.find_breakout(_daily(40, 40, 0)) is None

    def test_an_active_kill_candle_cancels_it(self):
        kill = KillCandle("2026-10-07", 2, 3.0, 2.0, 0.1, 100.0, False, 0.2)
        assert bo.find_breakout(_daily(40, 30, 6), kill) is None
        expired = KillCandle("2026-09-01", 20, 3.0, 2.0, 0.1, 100.0, False, 0.0)
        assert bo.find_breakout(_daily(40, 30, 6), expired) is not None

    def test_too_little_history_has_no_breakout(self):
        assert bo.find_breakout(_daily(10, 5, 3)) is None

    def test_a_part_finished_week_scales_its_volume_to_a_full_week(self):
        df = _daily(40, 30, 6)
        partial = df.iloc[:-2]  # Wednesday of the breakout week: 3 sessions of 5
        weekly, scale = bo._weekly(partial)
        assert scale == pytest.approx(5 / 3)
        _, full = bo._weekly(df)
        assert full == 1.0


def _extend(df, closes):
    """Append one session per close (business days after the last bar)."""
    idx = pd.bdate_range(df.index[-1] + pd.Timedelta(days=1), periods=len(closes))
    extra = pd.DataFrame(
        {"open": closes, "high": [c + 0.3 for c in closes], "low": [c - 0.3 for c in closes], "close": closes, "volume": 1e6},
        index=idx,
    )
    return pd.concat([df, extra])


class TestFindFailedBreakout:
    HOLD = 111.0  # a close above the level
    LEVEL = bo.find_breakout(_daily(40, 30, 6)).base_high  # the base high the breakout week clears (108.0)

    def _failed(self, closes):
        return bo.find_failed_breakout(_extend(_daily(40, 30, 6), closes))

    def test_a_close_back_below_the_base_high_after_a_breakout_week_is_a_failure(self):
        f = self._failed([self.HOLD] * 5 + [110.0, 109.0, 99.0, 98.0, 97.0])
        assert f is not None
        assert f.level == self.LEVEL and f.week == "2026-10-05" and f.breakout_close == 110.8
        assert f.below_pct == pytest.approx((97.0 / self.LEVEL - 1) * 100, abs=0.01) and f.below_pct < 0
        assert f.weeks_ago == 2 and f.failed_on == "2026-10-21" and f.sessions_below == 3
        assert f.low_pct == f.below_pct and f.volume_x >= bo.BREAKOUT_VOLUME_X

    def test_low_pct_is_the_deepest_close_since_the_breakout(self):
        f = self._failed([self.HOLD] * 5 + [110.0, 109.0, 95.0, 98.0, 97.0])
        assert f.low_pct < f.below_pct < 0

    def test_a_breakout_that_still_holds_its_level_has_not_failed(self):
        assert self._failed([self.HOLD] * 10) is None

    def test_a_close_exactly_at_the_level_holds(self):
        assert self._failed([self.HOLD] * 5 + [110.0, 109.0, 109.0, 108.5, self.LEVEL]) is None

    def test_a_dip_below_the_level_that_was_reclaimed_has_not_failed(self):
        assert self._failed([self.HOLD] * 4 + [99.0, 98.0, 110.0, 110.0, 110.0, 110.0]) is None

    def test_the_failure_date_is_the_start_of_the_current_run_below_the_level(self):
        f = self._failed([self.HOLD] * 3 + [99.0, 110.0, 110.0, 99.5, 99.0, 98.0, 98.5])
        assert f is not None and f.sessions_below == 4 and f.failed_on == "2026-10-20"

    def test_a_breakout_in_the_current_week_cannot_have_failed(self):
        assert bo.find_failed_breakout(_daily(40, 30, 6)) is None

    def test_the_breakout_must_be_within_the_lookback(self):
        assert bo.FAILED_LOOKBACK_WEEKS == 8
        too_old = [self.HOLD] * 5 * 8 + [99.0] * 3  # 9 weekly candles after the breakout week
        assert self._failed(too_old) is None
        oldest = [self.HOLD] * 5 * 7 + [99.0] * 3  # 8
        f = self._failed(oldest)
        assert f is not None and f.weeks_ago == 8

    def test_a_kill_candle_does_not_hide_a_failure(self):
        # Wide heavy down days are what failures look like; unlike Recent breakouts, a kill candle is not a veto.
        assert self._failed([self.HOLD] * 5 + [99.0] * 3) is not None

    def test_too_little_history_has_no_failed_breakout(self):
        assert bo.find_failed_breakout(_daily(10, 5, 3)) is None

    def test_find_breakout_still_sees_a_breakout_that_failed_within_three_weeks(self):
        df = _extend(_daily(40, 30, 6), [self.HOLD] * 5 + [99.0] * 5)
        assert bo.find_breakout(df) is not None and bo.find_failed_breakout(df) is not None

    def test_a_newer_breakout_in_the_current_week_hides_an_older_failed_one(self, monkeypatch):
        df = _extend(_daily(40, 30, 6), [self.HOLD] * 5 + [99.0] * 5)
        assert bo.find_failed_breakout(df) is not None
        real = bo._breakout_at
        n = len(bo._weekly(df)[0])

        def fake(weekly, rng, j, scale):
            if j == n - 1:
                return dataclasses.replace(real(weekly, rng, n - 3, scale), weeks_ago=0)
            return real(weekly, rng, j, scale)

        monkeypatch.setattr(bo, "_breakout_at", fake)
        assert bo.find_failed_breakout(df) is None
