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
