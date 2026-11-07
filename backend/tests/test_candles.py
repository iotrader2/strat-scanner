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
    # The Strat long setups were removed on 2026-11-07 (replaced by the
    # RealSimpleAriel setups in strat.ariel_setups, tested in
    # test_ariel_setups.py). ``find_long_setups`` is kept only as a no-op so
    # the removal is explicit; there are no Strat setup kinds left to assert.
    return {s.kind for s in find_long_setups(candles, classify_series(candles))}


class TestSetupsRemoved:
    def test_find_long_setups_is_a_removed_no_op(self):
        candles = [Candle(95, 100, 90, 98), Candle(98, 112, 94, 110), Candle(108, 111, 100, 109)]
        assert find_long_setups(candles, classify_series(candles)) == []
        assert _kinds(candles) == set()

    def test_timeframe_state_carries_no_strat_setups(self):
        st = timeframe_state("W", [Candle(95, 100, 90, 98), Candle(96, 99, 91, 97.5)])
        assert st.strat == INSIDE and st.inside and st.color == "green"
        assert st.setups == []

    def test_ariel_setups_carry_a_stop_and_15m_entry(self):
        from strat.ariel_setups import find_ariel_setups

        import pandas as pd

        idx = pd.bdate_range("2026-06-01", periods=22)
        df = pd.DataFrame(
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1_000_000.0}, index=idx
        )
        df.iloc[-1] = (103.0, 106.0, 102.0, 105.0, 3_000_000.0)
        setups = find_ariel_setups(df)
        assert setups and setups[0].kind == "episodic-pivot"
        assert setups[0].stop == 102.0 and setups[0].to_setup().entry_tf == "15m"


def test_apply_live_triggers_marks_pending_long_setups_above_the_trigger():
    from strat.candles import Setup, TimeframeState, apply_live_triggers

    def state(tf="D"):
        return TimeframeState(
            tf, "1", "2U", "green", 1, 2, 0.5, 1.5, True, False,
            setups=[Setup("episodic-pivot", "Episodic Pivot", 10.0, False), Setup("flat-base-breakout", "Flat Base Breakout", 9.0, True, "x")],
        )

    hit = apply_live_triggers(state(), 10.5)
    assert [(s.triggered, s.live) for s in hit.setups] == [(True, True), (True, False)]
    assert hit.setups[0].trigger == 10.0
    assert hit.setups[0].detail == "broke 10.00 this day (high 10.50)"
    assert hit.setups[1].detail == "x"
    assert [s.triggered for s in apply_live_triggers(state(), 10.0).setups] == [False, True]
    assert [s.triggered for s in apply_live_triggers(state(), None).setups] == [False, True]
    assert apply_live_triggers(state("M"), 11.0).setups[0].detail.startswith("broke 10.00 this month")
    assert apply_live_triggers(None, 11.0) is None
