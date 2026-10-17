import pandas as pd
import pytest

from strat import pricebehavior as pb
from strat.scoring import TIGHTNESS_POINTS, score_symbol
from strat.candles import Candle, timeframe_state


def _bars(n=120, half_range=1.0, vol=1e6, end="2026-10-15"):
    idx = pd.bdate_range(end=end, periods=n)
    close = pd.Series([100.0 + (i % 2) * 0.2 for i in range(n)], index=idx)
    return pd.DataFrame(
        {"open": close, "high": close + half_range, "low": close - half_range, "close": close, "volume": float(vol)}
    )


def _with_recent_range(df, bars, half_range):
    df = df.copy()
    df.iloc[-bars:, df.columns.get_indexer(["high"])] = df.close.iloc[-bars:].values[:, None] + half_range
    df.iloc[-bars:, df.columns.get_indexer(["low"])] = df.close.iloc[-bars:].values[:, None] - half_range
    return df


def _kill(df, age=0, close_pos=0.1, volume_x=3.0, range_x=5.0):
    """Turn the bar ``age`` sessions ago into a wide, heavy red candle."""
    df = df.copy()
    i = len(df) - 1 - age
    prev = float(df.close.iloc[i - 1])
    span = 2.0 * range_x  # the normal true range is 2
    low = prev - span * 0.9
    high = low + span
    close = low + close_pos * span
    df.iloc[i, df.columns.get_indexer(["open", "high", "low", "close", "volume"])] = [high - 0.1, high, low, close, 1e6 * volume_x]
    return df


class TestTightness:
    def test_a_tightening_stock_is_tighter_than_a_loosening_one(self):
        base = _bars()
        tight = _with_recent_range(base, 10, 0.5)
        loose = _with_recent_range(base, 10, 3.0)
        assert pb.tightness_fraction(pb.range_stats(tight)) == 1.0
        assert pb.tightness_fraction(pb.range_stats(loose)) == 0.0
        assert pb.tightness_fraction(pb.range_stats(base)) == pytest.approx(0.6 * 0.625 + 0.4 * 0.5, abs=0.01)

    def test_ratio_and_contraction_are_recent_over_baseline(self):
        t = pb.range_stats(_with_recent_range(_bars(), 10, 3.0))
        assert t.ratio > 1.25 and t.range10_pct > t.range50_pct
        t = pb.range_stats(_with_recent_range(_bars(), 5, 0.4))
        assert t.contraction < 0.8

    def test_missing_history_scores_zero(self):
        assert pb.range_stats(_bars(n=30)) is None
        assert pb.tightness_fraction(None) == 0.0

    def test_the_score_shows_tightness_with_its_weight(self):
        states = {tf: timeframe_state(tf, [Candle(90, 100, 85, 95), Candle(95, 106, 94, 105)]) for tf in "MWD"}
        loose = score_symbol(states, 100.0, 1e9, tightness=pb.range_stats(_with_recent_range(_bars(), 10, 3.0)))
        tight = score_symbol(states, 100.0, 1e9, tightness=pb.range_stats(_with_recent_range(_bars(), 10, 0.5)))
        part = lambda s: next(c for c in s.breakdown if c.key == "tightness")  # noqa: E731
        assert part(tight).points == pytest.approx(TIGHTNESS_POINTS) and part(loose).points == 0
        assert part(tight).max_points == TIGHTNESS_POINTS and part(tight).weight_pct == 5
        assert tight.score > loose.score
        assert "10-day range" in part(tight).detail


class TestKillCandle:
    def test_a_wide_heavy_red_candle_closing_low_is_flagged(self):
        k = pb.find_kill_candle(_kill(_bars(), age=0))
        assert k is not None and k.age == 0 and k.penalty == pytest.approx(pb.KILL_PENALTY)
        assert k.range_x_atr >= pb.KILL_RANGE_X_ATR and k.volume_x >= pb.KILL_VOLUME_X and k.close_position <= pb.KILL_CLOSE_POSITION

    @pytest.mark.parametrize(
        "kw",
        [dict(volume_x=1.0), dict(range_x=1.5), dict(close_pos=0.8)],
        ids=["light volume", "narrow range", "closes high"],
    )
    def test_each_condition_is_required(self, kw):
        assert pb.find_kill_candle(_kill(_bars(), **kw)) is None

    def test_a_green_candle_is_not_a_kill_candle(self):
        df = _kill(_bars())
        df.iloc[-1, df.columns.get_indexer(["open"])] = df.low.iloc[-1] - 0.5
        assert pb.find_kill_candle(df) is None

    def test_the_penalty_fades_with_age_and_expires(self):
        p = [pb.find_kill_candle(_kill(_bars(), age=a)) for a in (0, 5, 9)]
        assert p[0].penalty > p[1].penalty > p[2].penalty > 0
        assert p[1].penalty == pytest.approx(pb.KILL_PENALTY / 2)
        assert pb.kill_penalty(pb.KILL_LOOKBACK, False) == 0.0

    def test_taking_back_the_candles_high_removes_the_penalty(self):
        df = _kill(_bars(), age=3)
        df.iloc[-1, df.columns.get_indexer(["close", "high"])] = [float(df.high.iloc[-4]) + 5, float(df.high.iloc[-4]) + 6]
        k = pb.find_kill_candle(df)
        assert k.reclaimed and k.penalty == 0.0

    def test_the_penalty_multiplies_the_score_and_is_shown_with_the_date(self):
        states = {tf: timeframe_state(tf, [Candle(90, 100, 85, 95), Candle(95, 106, 94, 105)]) for tf in "MWD"}
        k = pb.find_kill_candle(_kill(_bars(), age=2))
        clean = score_symbol(states, 100.0, 1e9)
        hit = score_symbol(states, 100.0, 1e9, kill=k)
        assert hit.score == pytest.approx(clean.score * (1 - k.penalty), abs=0.1)
        part = next(c for c in hit.breakdown if c.key == "kill_candle")
        assert part.label.startswith("Kill candle (") and k.date in part.label and part.points < 0
        assert "kill_candle" not in [c.key for c in clean.breakdown]
