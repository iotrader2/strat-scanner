import pytest

from strat.candles import (
    INSIDE,
    OUTSIDE,
    TWO_DOWN,
    TWO_UP,
    Candle,
    classify,
    classify_series,
    continuity,
    find_long_setups,
    is_hammer,
    timeframe_state,
)

PREV = Candle(open=100, high=110, low=90, close=105)


class TestClassify:
    def test_inside_bar(self):
        assert classify(PREV, Candle(100, 108, 92, 101)) == INSIDE

    def test_inside_when_equal_to_previous_range(self):
        assert classify(PREV, Candle(100, 110, 90, 100)) == INSIDE

    def test_two_up(self):
        assert classify(PREV, Candle(105, 112, 95, 111)) == TWO_UP

    def test_two_up_is_about_range_not_color(self):
        assert classify(PREV, Candle(111, 112, 95, 96)) == TWO_UP

    def test_two_down(self):
        assert classify(PREV, Candle(100, 108, 85, 87)) == TWO_DOWN

    def test_two_down_with_equal_high(self):
        assert classify(PREV, Candle(100, 110, 89, 95)) == TWO_DOWN

    def test_outside_bar(self):
        assert classify(PREV, Candle(100, 115, 85, 112)) == OUTSIDE

    def test_series_first_candle_unclassified(self):
        candles = [PREV, Candle(100, 108, 92, 101), Candle(101, 107, 91, 98), Candle(98, 120, 95, 118), Candle(118, 121, 94, 100)]
        assert classify_series(candles) == [None, INSIDE, TWO_DOWN, TWO_UP, OUTSIDE]


class TestContinuity:
    @pytest.mark.parametrize(
        "candle,expected",
        [
            (Candle(100, 110, 95, 105), "green"),
            (Candle(100, 110, 95, 98), "red"),
            (Candle(100, 110, 95, 100), "flat"),
        ],
    )
    def test_color_vs_period_open(self, candle, expected):
        assert continuity(candle) == expected


class TestHammer:
    def test_classic_hammer(self):
        # body 1, lower wick 7, upper wick 0.5, close in top third
        assert is_hammer(Candle(open=100, high=101.5, low=93, close=101))

    def test_red_hammer_still_counts(self):
        assert is_hammer(Candle(open=101, high=101.5, low=93, close=100))

    def test_doji_hammer(self):
        assert is_hammer(Candle(open=100, high=100.2, low=95, close=100))

    def test_lower_wick_exactly_twice_body(self):
        # body 2 (98->100), lower wick 4 (94->98), upper 0
        assert is_hammer(Candle(open=98, high=100, low=94, close=100))

    def test_lower_wick_too_short(self):
        # body 3, lower wick 5 (< 6)
        assert not is_hammer(Candle(open=97, high=100, low=92, close=100))

    def test_long_upper_wick_rejected(self):
        # lower wick 6, body 1 but upper wick 3 (> body and > 10% of range)
        assert not is_hammer(Candle(open=100, high=104, low=94, close=101))

    def test_close_outside_top_third_rejected(self):
        # spinning bottom: long lower wick, but long upper wick drags close to the middle
        assert not is_hammer(Candle(open=99, high=103, low=94, close=99.5))

    def test_shooting_star_is_not_hammer(self):
        assert not is_hammer(Candle(open=100, high=108, low=99.5, close=99.8))

    def test_zero_range(self):
        assert not is_hammer(Candle(100, 100, 100, 100))

    def test_no_lower_wick(self):
        assert not is_hammer(Candle(open=95, high=100, low=95, close=100))


def _kinds(candles):
    return {s.kind for s in find_long_setups(candles, classify_series(candles))}


class TestSetups:
    def test_inside_bar_trigger(self):
        candles = [Candle(95, 100, 90, 98), Candle(98, 112, 94, 110), Candle(108, 111, 100, 109)]
        setups = find_long_setups(candles, classify_series(candles))
        pending = next(s for s in setups if s.kind == "2-1-2-pending")
        assert (pending.trigger, pending.triggered) == (111, False)

    def test_three_one_pending(self):
        candles = [Candle(95, 100, 90, 98), Candle(98, 105, 85, 99), Candle(99, 103, 88, 100)]
        assert "3-1-2-pending" in _kinds(candles)

    def test_two_one_two_bullish(self):
        candles = [
            Candle(100, 110, 90, 95),
            Candle(95, 105, 85, 88),  # 2D
            Candle(88, 100, 87, 98),  # 1
            Candle(98, 104, 96, 103),  # 2U
        ]
        setups = find_long_setups(candles, classify_series(candles))
        s = next(s for s in setups if s.kind == "2-1-2")
        assert "2D-1-2U" in s.label
        assert (s.trigger, s.triggered) == (100, True)

    def test_three_one_two(self):
        candles = [Candle(100, 105, 95, 100), Candle(100, 110, 90, 108), Candle(108, 109, 95, 100), Candle(100, 112, 99, 111)]
        assert "3-1-2" in _kinds(candles)

    def test_one_two_two_revstrat(self):
        candles = [Candle(100, 110, 90, 100), Candle(100, 108, 92, 100), Candle(100, 104, 88, 90), Candle(90, 106, 89, 105)]
        assert "1-2-2" in _kinds(candles)

    def test_two_down_two_up_reversal(self):
        candles = [Candle(100, 110, 90, 100), Candle(100, 112, 95, 110), Candle(110, 111, 93, 94), Candle(94, 115, 94, 114)]
        kinds = _kinds(candles)
        assert "2D-2U" in kinds and "1-2-2" not in kinds

    def test_hammer_setup(self):
        candles = [Candle(100, 105, 95, 96), Candle(96, 97.2, 89, 97)]
        setups = find_long_setups(candles, classify_series(candles))
        h = next(s for s in setups if s.kind == "hammer")
        assert h.trigger == 97.2

    def test_bearish_patterns_ignored(self):
        candles = [Candle(100, 110, 90, 105), Candle(105, 108, 92, 100), Candle(100, 106, 85, 86)]
        assert _kinds(candles) == set()

    def test_setups_carry_no_stop(self):
        candles = [Candle(95, 100, 90, 98), Candle(98, 112, 94, 110), Candle(108, 111, 100, 109)]
        for s in find_long_setups(candles, classify_series(candles)):
            assert not hasattr(s, "stop")

    def test_timeframe_state(self):
        st = timeframe_state("W", [Candle(95, 100, 90, 98), Candle(96, 99, 91, 97.5)])
        assert st.strat == INSIDE and st.inside and st.color == "green"
