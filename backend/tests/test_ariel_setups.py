"""RealSimpleAriel setups: one detection / entry / stop test per setup, plus the shared rules."""

import pandas as pd
import pytest

from strat.ariel_setups import (
    ENTRY_TF,
    RISK_PCT_MAX,
    RISK_PCT_MIN,
    SETUP_KINDS,
    SETUP_POINTS,
    SETUP_TF,
    find_ariel_setups,
    to_scored_setups,
)
from strat.candles import Setup


def _frame(rows):
    idx = pd.bdate_range("2026-06-01", periods=len(rows))
    df = pd.DataFrame(rows, index=idx, columns=["open", "high", "low", "close", "volume"])
    return df


def _flat(n, close=100.0, vol=1_000_000.0):
    return [(close, close + 1, close - 1, close, vol) for _ in range(n)]


def _by_kind(df):
    return {s.kind: s for s in find_ariel_setups(df)}


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


def test_episodic_pivot_gap_volume_entry_and_stop():
    rows = _flat(21)
    rows.append((103.0, 106.0, 102.0, 105.0, 3_000_000.0))  # +3% gap on 3x volume, upper half
    setup = _by_kind(_frame(rows))["episodic-pivot"]
    assert setup.trigger == 106.0
    assert setup.stop == 102.0
    assert setup.triggered is False
    assert "15-min" in setup.entry_instruction
    assert "high of the first 15-min bar" in setup.entry_instruction


def test_episodic_pivot_needs_a_real_gap_and_volume():
    rows = _flat(21)
    rows.append((101.0, 102.0, 100.0, 101.5, 1_000_000.0))  # +1% gap, average volume
    assert "episodic-pivot" not in _by_kind(_frame(rows))


def test_delayed_hvc_second_chance_at_the_gap_close():
    rows = _flat(19)
    rows.append((103.0, 106.0, 102.0, 105.0, 3_000_000.0))  # EP gap day, close 105
    rows.append((104.0, 104.5, 103.0, 104.0, 1_000_000.0))  # holds below the gap close
    rows.append((104.5, 107.0, 104.0, 106.0, 2_000_000.0))  # breaks back through 105
    setup = _by_kind(_frame(rows))["delayed-hvc"]
    assert setup.trigger == 105.0
    assert setup.stop == 104.0
    assert setup.triggered is True
    assert "episodic-pivot" not in _by_kind(_frame(rows))  # the gap day is no longer the last bar


def test_flat_base_breakout_entry_and_stop():
    rows = _flat(10, close=98.0)
    rows += [(98.0, 100.0, 96.0, 98.0, 1_000_000.0) for _ in range(15)]  # 4% deep base
    rows.append((99.0, 102.0, 98.5, 101.5, 2_000_000.0))  # breaks the base high 100
    setup = _by_kind(_frame(rows))["flat-base-breakout"]
    assert setup.trigger == 100.0
    assert setup.stop == 98.5  # wide breakout candle: stop is the breakout-day low
    assert setup.triggered is True


def test_flat_base_breakout_tight_candle_uses_the_prior_day_low():
    rows = _flat(10, close=98.0)
    rows += [(98.0, 100.0, 96.0, 98.0, 1_000_000.0) for _ in range(15)]
    rows.append((100.5, 101.0, 100.2, 100.8, 2_000_000.0))  # tight breakout, range 0.8 < 2% of price
    setup = _by_kind(_frame(rows))["flat-base-breakout"]
    assert setup.trigger == 100.0
    assert setup.stop == 96.0  # prior-day low


def test_flat_base_needs_a_tight_base():
    rows = _flat(10, close=98.0)
    rows += [(98.0, 110.0, 90.0, 98.0, 1_000_000.0) for _ in range(15)]  # 18% deep: not a flat base
    rows.append((99.0, 112.0, 98.0, 111.0, 2_000_000.0))
    assert "flat-base-breakout" not in _by_kind(_frame(rows))


def test_undercut_rally_reclaim_and_stop():
    rows = _flat(20)
    rows[10] = (100.0, 101.0, 90.0, 100.0)  # swing low 90
    rows.append((94.0, 95.0, 88.0, 95.0, 1_000_000.0))  # undercuts to 88
    rows.append((91.0, 97.0, 91.0, 96.0, 1_000_000.0))  # reclaims 90
    setup = _by_kind(_frame(rows))["undercut-rally"]
    assert setup.trigger == 90.0
    assert setup.stop == 88.0
    assert setup.triggered is True


def test_undercut_without_reclaim_is_not_a_setup():
    rows = _flat(20)
    rows[10] = (100.0, 101.0, 90.0, 100.0)
    rows.append((94.0, 95.0, 88.0, 95.0, 1_000_000.0))
    rows.append((86.0, 89.0, 85.0, 87.0, 1_000_000.0))  # still below the swing low
    assert "undercut-rally" not in _by_kind(_frame(rows))


def test_ma_undercut_rally_reclaim_and_stop():
    rows = _flat(60)
    rows.append((96.0, 97.0, 94.0, 95.0, 1_000_000.0))  # dips below the ~99.8 average
    rows.append((100.0, 103.0, 99.0, 102.0, 2_000_000.0))  # reclaims it
    setup = _by_kind(_frame(rows))["ma-undercut-rally"]
    assert setup.trigger == pytest.approx(99.85, abs=0.05)
    assert setup.stop == 99.0
    assert setup.triggered is True
    assert "20-day" in setup.label


def test_high_tight_flag_breakout_entry_and_stop():
    rows = [(100.0 + i * 2.5, 102.0 + i * 2.5, 98.0 + i * 2.5, 100.0 + i * 2.5, 2_000_000.0) for i in range(25)]
    rows += [(160.0, 162.0, 152.0, 158.0, 1_000_000.0) for _ in range(15)]  # tight flag, volume contracts
    rows.append((163.0, 166.0, 160.0, 165.0, 2_000_000.0))  # breaks the flag high 162
    setup = _by_kind(_frame(rows))["high-tight-flag"]
    assert setup.trigger == 162.0
    assert setup.stop == 160.0
    assert setup.triggered is True


def test_high_tight_flag_needs_the_run_up():
    rows = _flat(25)
    rows += [(100.0, 102.0, 98.0, 100.0, 1_000_000.0) for _ in range(15)]
    rows.append((101.0, 103.0, 100.0, 102.5, 2_000_000.0))
    assert "high-tight-flag" not in _by_kind(_frame(rows))


def test_too_little_history_finds_nothing():
    assert find_ariel_setups(_frame(_flat(10))) == []


def test_to_scored_setups_keep_the_shared_setup_shape_and_15m_entry():
    rows = _flat(21)
    rows.append((103.0, 106.0, 102.0, 105.0, 3_000_000.0))
    scored = to_scored_setups(_frame(rows))
    assert scored
    assert all(isinstance(s, Setup) for s in scored)
    assert all(s.entry_tf == "15m" and s.stop is not None for s in scored)
    points = [SETUP_POINTS[s.kind] for s in scored]
    assert points == sorted(points, reverse=True)
    assert scored[0].kind == "episodic-pivot"
