"""RealSimpleAriel setups: detection / entry / stop per setup, the shared rules, and regressions from the PR #74 review."""

import numpy as np
import pandas as pd
import pytest

from strat.ariel_setups import (
    ENTRY_TF,
    RISK_PCT_MAX,
    RISK_PCT_MIN,
    SETUP_KINDS,
    SETUP_POINTS,
    SETUP_TF,
    ArielSetup,
    find_ariel_setups,
    has_defined_risk,
    to_scored_setups,
)
from strat.candles import Setup


def _frame(rows):
    idx = pd.bdate_range("2026-01-05", periods=len(rows))
    return pd.DataFrame(rows, index=idx, columns=["open", "high", "low", "close", "volume"])


def _flat(n, close=100.0, vol=1_000_000.0):
    return [(close, close + 1, close - 1, close, vol) for _ in range(n)]


def _ramp(n, start, end, vol=1_000_000.0, half_range=1.0):
    return [(c, c + half_range, c - half_range, c, vol) for c in np.linspace(start, end, n)]


def _by_kind(df, **live):
    return {s.kind: s for s in find_ariel_setups(df, **live)}


def test_setup_tf_is_daily_and_entry_is_15m():
    assert SETUP_TF == "D"
    assert ENTRY_TF == "15m"
    assert set(SETUP_KINDS) == {
        "episodic-pivot",
        "delayed-hvc",
        "flat-base-breakout",
        "undercut-rally",
        "ma-undercut-rally",
        "high-tight-flag",
    }


def test_risk_band_is_half_to_one_percent():
    assert (RISK_PCT_MIN, RISK_PCT_MAX) == (0.005, 0.01)


# --- Episodic Pivot: a same-day trade on today's forming bar ------------------------------------


def _today(open_=103.0, high=106.0, low=102.0, close=105.0, volume=0.0):
    return {"open": open_, "high": high, "low": low, "close": close, "volume": volume}


def test_episodic_pivot_is_live_with_the_opening_range_trigger_and_low_of_day_stop():
    df = _frame(_flat(22))
    setup = _by_kind(df, today=_today(volume=1_500_000.0), opening_high=104.5, session_fraction=0.25)["episodic-pivot"]
    assert setup.trigger == 104.5  # the first 15-min bar's high
    assert setup.stop == 102.0  # low of day
    assert setup.triggered is False  # the scanner's live trigger check decides the break
    assert "high of the first 15-min bar" in setup.entry_instruction


def test_episodic_pivot_before_the_opening_range_closes_uses_the_high_so_far():
    setup = _by_kind(_frame(_flat(22)), today=_today())["episodic-pivot"]
    assert setup.trigger == 106.0
    assert "still forming" in setup.detail


def test_episodic_pivot_rejects_light_projected_volume():
    # A quarter of the session gone and only 0.2x the average traded: projects to 0.8x, not "significantly above".
    found = _by_kind(_frame(_flat(22)), today=_today(volume=200_000.0), opening_high=104.5, session_fraction=0.25)
    assert "episodic-pivot" not in found


def test_episodic_pivot_needs_a_real_gap():
    assert "episodic-pivot" not in _by_kind(_frame(_flat(22)), today=_today(open_=100.5), opening_high=101.0)


def test_completed_gap_day_is_not_an_episodic_pivot():
    """The ORB entry window is the gap day itself; after the close the second chance is the Delayed HVC."""
    rows = _flat(21)
    rows.append((103.0, 106.0, 102.0, 105.0, 3_000_000.0))
    assert "episodic-pivot" not in _by_kind(_frame(rows))


# --- Delayed HVC -----------------------------------------------------------------------------------


def _gap_then(*after):
    rows = _flat(20)
    rows.append((103.0, 106.0, 102.0, 105.0, 3_000_000.0))  # EP gap day, close 105
    rows += list(after)
    return _frame(rows)


def test_delayed_hvc_triggered_on_the_break_back_through_the_gap_close():
    df = _gap_then(
        (104.0, 104.5, 103.0, 104.0, 1_000_000.0),  # back below the gap close
        (104.5, 107.0, 104.0, 106.0, 2_000_000.0),  # breaks back through 105
    )
    setup = _by_kind(df)["delayed-hvc"]
    assert (setup.trigger, setup.stop, setup.triggered) == (105.0, 104.0, True)


def test_delayed_hvc_pending_while_below_the_gap_close():
    setup = _by_kind(_gap_then((104.0, 104.5, 103.0, 104.0, 1_000_000.0)))["delayed-hvc"]
    assert setup.trigger == 105.0
    assert setup.triggered is False
    assert setup.stop is None  # set by the day the entry triggers


def test_day_after_the_gap_is_not_a_break_back_through():
    """The gap day closed at the level; trading above it the next day never went back below."""
    assert "delayed-hvc" not in _by_kind(_gap_then((105.5, 107.0, 105.2, 106.5, 1_500_000.0)))


# --- Flat Base -------------------------------------------------------------------------------------


def _base_rows():
    rows = _ramp(40, 70.0, 95.0)  # strong prior trend (+35%)
    # 15-session base between 96 and 100 with shrinking ranges.
    for i in range(15):
        half = 2.0 - i * 0.1
        rows.append((98.0, 98.0 + half, 98.0 - half, 98.0, 1_000_000.0))
    return rows


def test_flat_base_pending_at_resistance():
    rows = _base_rows()
    rows[-1] = (98.5, 99.5, 98.0, 99.3, 1_000_000.0)  # last bar's high at the base resistance
    setup = _by_kind(_frame(rows))["flat-base-breakout"]
    assert setup.triggered is False
    assert setup.trigger == pytest.approx(100.0)
    assert setup.stop == 98.0


def test_flat_base_breakout_entry_and_stop():
    rows = _base_rows()
    rows.append((99.0, 102.0, 98.5, 101.5, 2_000_000.0))  # breaks above the prior-day high / base high
    setup = _by_kind(_frame(rows))["flat-base-breakout"]
    assert setup.triggered is True
    assert setup.trigger == pytest.approx(100.0)
    assert setup.stop == 98.5  # wide breakout candle: the breakout-day low


def test_flat_base_needs_a_prior_trend():
    rows = _flat(40, close=98.0)  # no trend into the base
    rows += _base_rows()[40:]
    rows.append((99.0, 102.0, 98.5, 101.5, 2_000_000.0))
    assert "flat-base-breakout" not in _by_kind(_frame(rows))


def test_flat_base_needs_shrinking_ranges():
    rows = _ramp(40, 70.0, 95.0)
    for i in range(15):
        half = 0.6 + i * 0.1  # ranges widen
        rows.append((98.0, 98.0 + half, 98.0 - half, 98.0, 1_000_000.0))
    rows.append((99.0, 102.0, 98.5, 101.5, 2_000_000.0))
    assert "flat-base-breakout" not in _by_kind(_frame(rows))


# --- Undercut and Rally ------------------------------------------------------------------------------


def test_undercut_rally_reclaim_and_stop():
    rows = _flat(20)
    rows[10] = (100.0, 101.0, 90.0, 100.0, 1_000_000.0)  # swing low 90
    rows.append((94.0, 95.0, 88.0, 89.0, 1_000_000.0))  # undercuts to 88, closes below
    rows.append((89.5, 97.0, 89.0, 96.0, 1_000_000.0))  # reclaims 90
    setup = _by_kind(_frame(rows))["undercut-rally"]
    assert (setup.trigger, setup.stop, setup.triggered) == (90.0, 88.0, True)


def test_undercut_without_reclaim_is_not_a_setup():
    rows = _flat(20)
    rows[10] = (100.0, 101.0, 90.0, 100.0, 1_000_000.0)
    rows.append((94.0, 95.0, 88.0, 89.0, 1_000_000.0))
    rows.append((86.0, 89.0, 85.0, 87.0, 1_000_000.0))
    assert "undercut-rally" not in _by_kind(_frame(rows))


# --- MA Undercut and Rally ------------------------------------------------------------------------------


def test_ma_undercut_rally_reclaim_and_stop():
    rows = _flat(60)
    rows.append((96.0, 97.0, 94.0, 95.0, 1_000_000.0))  # closes below the ~99.8 average
    rows.append((99.0, 103.0, 98.5, 102.5, 2_000_000.0))  # reclaims it with strength
    setup = _by_kind(_frame(rows))["ma-undercut-rally"]
    assert setup.trigger == pytest.approx(99.9, abs=0.1)
    assert setup.stop == 98.5
    assert setup.triggered is True
    assert "20-day" in setup.label


def test_ma_reclaim_without_strength_is_not_a_setup():
    rows = _flat(60)
    rows.append((96.0, 97.0, 94.0, 95.0, 1_000_000.0))
    rows.append((103.0, 104.0, 98.5, 100.0, 1_000_000.0))  # closes red, low in its range
    assert "ma-undercut-rally" not in _by_kind(_frame(rows))


# --- High Tight Flag ------------------------------------------------------------------------------------


def _htf_rows():
    rows = _flat(20)
    rows += _ramp(25, 100.0, 160.0, vol=2_000_000.0)  # +60% in 5 weeks
    rows += [(158.0, 162.0, 152.0, 158.0, 1_000_000.0) for _ in range(15)]  # tight flag, volume contracts
    return rows


def test_high_tight_flag_pending_inside_the_flag():
    setup = _by_kind(_frame(_htf_rows()))["high-tight-flag"]
    assert setup.triggered is False
    assert setup.trigger == 162.0


def test_high_tight_flag_breakout_entry_and_stop():
    rows = _htf_rows() + [(161.0, 166.0, 160.0, 165.0, 2_000_000.0)]
    setup = _by_kind(_frame(rows))["high-tight-flag"]
    assert (setup.trigger, setup.stop, setup.triggered) == (162.0, 160.0, True)


def test_slow_year_long_climb_is_not_a_high_tight_flag():
    """Regression: the run-up was measured from the first bar of the whole history."""
    rows = _ramp(250, 100.0, 160.0, half_range=0.5)
    rows += [(159.5, 160.3, 158.7, 159.5, 500_000.0) for _ in range(15)]
    rows.append((160.5, 162.5, 160.0, 162.0, 1_000_000.0))
    assert "high-tight-flag" not in _by_kind(_frame(rows))


# --- Defined risk ----------------------------------------------------------------------------------------


def test_stop_at_or_above_entry_is_dropped():
    s = ArielSetup("high-tight-flag", "High Tight Flag", trigger=160.8, stop=161.19, triggered=True, entry=160.8)
    assert not has_defined_risk(s)


def test_gap_above_the_trigger_measures_risk_from_the_open():
    # Gapped over the 162 trigger, opened at 163, low of day 162.5: buyable at 163 with the stop below.
    rows = _htf_rows() + [(163.0, 166.0, 162.5, 165.0, 2_000_000.0)]
    setup = _by_kind(_frame(rows))["high-tight-flag"]
    assert setup.entry == 163.0 and setup.stop == 162.5


def test_every_setup_has_its_stop_below_its_entry():
    frames = [_htf_rows() + [(161.0, 166.0, 160.0, 165.0, 2_000_000.0)], _base_rows()]
    for rows in frames:
        for s in find_ariel_setups(_frame(rows)):
            assert has_defined_risk(s)


# --- Shared --------------------------------------------------------------------------------------------------


def test_too_little_history_finds_nothing():
    assert find_ariel_setups(_frame(_flat(10))) == []


def test_to_scored_setups_keep_the_shared_setup_shape_and_15m_entry():
    rows = _htf_rows() + [(161.0, 166.0, 160.0, 165.0, 2_000_000.0)]
    scored = to_scored_setups(_frame(rows), today=_today(open_=170.0, high=172.0, low=169.0, close=171.0))
    assert scored
    assert all(isinstance(s, Setup) and s.entry_tf == "15m" for s in scored)
    points = [SETUP_POINTS[s.kind] for s in scored]
    assert points == sorted(points, reverse=True)
    assert scored[0].kind == "episodic-pivot"


# --- short mirrors ---------------------------------------------------------------------------------------------------

from strat.ariel_setups import SHORT_KINDS, SHORT_MIRROR, find_short_setups  # noqa: E402


def _flip(rows):
    """The same chart upside down (p -> 10000 / p, high and low swap): a long pattern becomes its short mirror."""
    return [(1e4 / o, 1e4 / lo, 1e4 / h, 1e4 / c, v) for o, h, lo, c, v in rows]


def _shorts(df, **live):
    return {s.kind: s for s in find_short_setups(df, **live)}


@pytest.mark.parametrize(
    "rows, long_kind",
    [
        (_htf_rows() + [(161.0, 166.0, 160.0, 165.0, 2_000_000.0)], "high-tight-flag"),
        (_base_rows() + [(99.0, 102.0, 98.5, 101.5, 2_000_000.0)], "flat-base-breakout"),
    ],
)
def test_every_long_pattern_upside_down_is_its_short_mirror(rows, long_kind):
    long = _by_kind(_frame(rows))[long_kind]
    short_kind = SHORT_MIRROR[long_kind][0]
    short = _shorts(_frame(_flip(rows)))[short_kind]
    assert short.side == "short" and short.to_setup().side == "short"
    assert short.trigger == pytest.approx(1e4 / long.trigger)
    assert short.stop == pytest.approx(1e4 / long.stop)
    assert short.stop > short.trigger  # stop above the entry
    assert short.triggered == long.triggered


def test_gap_down_pivot_is_live_with_the_opening_range_low_and_high_of_day_stop():
    today = {"open": 97.0, "high": 98.0, "low": 94.0, "close": 95.0, "volume": 1_500_000.0}
    setup = _shorts(_frame(_flat(22)), today=today, opening_low=95.5, session_fraction=0.25)["gap-down-pivot"]
    assert setup.trigger == pytest.approx(95.5)  # below the first 15-min bar low
    assert setup.stop == pytest.approx(98.0)  # high of day
    assert setup.triggered is False
    assert "below the low of the first 15-min bar" in setup.entry_instruction


def test_ma_overcut_fail_reads_the_real_moving_average():
    rows = _flat(60)
    rows.append((102.0, 106.0, 101.0, 103.0, 1_000_000.0))  # closes above the ~100.05 average
    rows.append((100.5, 101.0, 96.5, 97.0, 2_000_000.0))  # rejected back below on a weak day
    df = _frame(rows)
    setup = _shorts(df)["ma-overcut-fail"]
    assert setup.trigger == pytest.approx(float(df["close"].rolling(20).mean().iloc[-1]))
    assert setup.stop == pytest.approx(101.0)
    assert "20-day" in setup.label


def test_short_kinds_rank_like_their_long_counterparts():
    assert len(SHORT_KINDS) == 6
    for long_kind, (short_kind, _) in SHORT_MIRROR.items():
        assert SETUP_POINTS[short_kind] == SETUP_POINTS[long_kind]


def test_a_rising_flat_chart_has_no_short_setups():
    assert find_short_setups(_frame(_htf_rows())) == []
