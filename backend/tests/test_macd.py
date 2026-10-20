"""MACD (6, 20, 9) histogram triggers, including the shared fixture the chart also checks."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from strat.macd import (
    MACD_FAST,
    MACD_SIGNAL,
    MACD_SLOW,
    ema,
    histogram_triggers,
    daily_trend_setup,
    latest_daily_trend,
    macd_histogram,
    trend_from_histogram,
    trigger_dates,
)

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "macd_series.json"

# Same uneven closes the chart test locks (web/src/macd.test.ts).
CLOSES = np.array(
    [
        10, 10.5, 11, 10.8, 10.2, 10.6, 11.4, 12, 11.7, 11.1, 11.5, 12.2, 12.8, 12.4, 11.9, 12.6, 13.1, 13.5, 13.0,
        12.7, 13.2, 13.8, 14.4, 14.0, 13.6, 14.1, 14.7, 15.2, 14.8, 14.3, 14.9, 15.5, 16.0, 15.4, 15.0,
    ],
    dtype=np.float64,
)


def test_ema_seeds_with_the_sma_then_smooths():
    # period 3, k = 0.5. SMA(1, 2, 3) = 2. Next: 3. Next: 4.5.
    assert ema(np.array([1, 2, 3, 4, 6], dtype=np.float64), 3).tolist() == pytest.approx(
        [np.nan, np.nan, 2, 3, 4.5], nan_ok=True
    )


def test_histogram_matches_the_chart_on_the_known_series():
    assert (MACD_FAST, MACD_SLOW, MACD_SIGNAL) == (6, 20, 9)
    hist = macd_histogram(CLOSES)
    assert np.isnan(hist[:27]).all()
    assert hist[27] == pytest.approx(0.1299806293, abs=1e-8)
    assert hist[34] == pytest.approx(-0.1058761837, abs=1e-8)
    flat = macd_histogram(np.full(40, 10.0))
    assert np.nan_to_num(flat, nan=0.0) == pytest.approx(np.zeros(40))


def test_bullish_trigger_is_the_first_green_after_three_reds():
    assert histogram_triggers(np.array([-1, -1, -1, 0.5])) == [(3, "up", 0.5)]
    # Zero uses the bar-color rule: histogram >= 0 is green.
    assert histogram_triggers(np.array([-0.2, -0.4, -0.1, 0])) == [(3, "up", 0.0)]
    assert histogram_triggers(np.array([-1, -1, 0.5])) == []
    assert histogram_triggers(np.array([-1, -0.5, -0.2, -0.8, -0.3, -0.1, 0.4, 0.9])) == [(6, "up", 0.4)]
    assert histogram_triggers(np.array([-1, -1, -1, 0.2, 0.5, 0.1, 1])) == [(3, "up", 0.2)]
    assert histogram_triggers(np.array([0.4])) == []
    assert histogram_triggers(np.array([np.nan, np.nan, -1, -1, -1, 0.3])) == [(5, "up", 0.3)]


def test_bearish_trigger_is_the_first_red_after_three_greens():
    assert histogram_triggers(np.array([1, 1, 1, -0.5])) == [(3, "down", -0.5)]
    assert histogram_triggers(np.array([0, 0, 0, -0.2])) == [(3, "down", -0.2)]
    assert histogram_triggers(np.array([1, 1, -0.5])) == []
    assert histogram_triggers(np.array([1, 0.5, 0.2, 0.8, 0.3, 0.1, -0.4, -0.9])) == [(6, "down", -0.4)]
    assert histogram_triggers(np.array([1, 1, 1, -0.2, -0.5, -0.1, -1])) == [(3, "down", -0.2)]
    assert histogram_triggers(np.array([-0.4])) == []
    assert histogram_triggers(np.array([np.nan, np.nan, 1, 1, 1, -0.3])) == [(5, "down", -0.3)]
    assert histogram_triggers(np.array([-1, -1, -1, 0.4, 0.2, 0.1, -0.3])) == [(3, "up", 0.4), (6, "down", -0.3)]


def test_two_bars_are_not_enough_and_only_the_latest_bar_counts():
    assert trend_from_histogram(np.array([-1.0, -1.0, 0.5])) is None
    assert trend_from_histogram(np.array([1.0, 1.0, -0.5])) is None
    assert trend_from_histogram(np.array([-1.0, -1.0, -1.0, 0.4])) == "bullish"
    assert trend_from_histogram(np.array([1.0, 1.0, 1.0, -0.4])) == "bearish"
    # The flip was real, but it is not the most recent bar.
    assert trend_from_histogram(np.array([-1.0, -1.0, -1.0, 0.4, 0.2])) is None
    assert trend_from_histogram(np.array([1.0, 1.0, 1.0, -0.4, -0.2])) is None
    assert trend_from_histogram(np.array([-1.0, -1.0, -1.0, 0.4, 0.8, 0.2, -0.3])) == "bearish"
    assert trend_from_histogram(np.array([])) is None


def _step_frame() -> pd.DataFrame:
    """Eight-bar up/down steps. The last close is a bullish histogram trigger."""
    price = 100.0
    closes = []
    for i in range(100):
        price += 1.2 if (i // 8) % 2 == 0 else -1.2
        closes.append(price)
    return pd.DataFrame({"close": closes}, index=pd.bdate_range("2026-01-05", periods=len(closes)))


def test_latest_daily_trend_uses_the_last_bar_of_the_frame():
    """The scan passes the daily frame through, including today's session bar when it is overlaid.

    Dropping that last row is what a 'confirmed prior session only' rule would do. This signal
    does not: if the last bar is the trigger, the name matches, and it stops matching when that
    bar is removed.
    """
    frame = _step_frame()
    assert latest_daily_trend(frame) == "bullish"
    assert latest_daily_trend(frame.iloc[:-1]) is None
    assert latest_daily_trend(frame.iloc[0:0]) is None
    known = pd.DataFrame({"close": CLOSES}, index=pd.bdate_range("2026-01-05", periods=len(CLOSES)))
    assert latest_daily_trend(known) == trend_from_histogram(macd_histogram(CLOSES))


def test_trigger_dates_match_the_shared_fixture():
    fixture = json.loads(FIXTURE.read_text())
    got = [{"time": row["time"], "direction": row["direction"]} for row in trigger_dates(fixture["times"], fixture["closes"])]
    assert got == fixture["triggers"]


def _trend(price, sma50):
    from strat.leadership import Trend

    return Trend(price=price, sma={10: None, 20: None, 50: sma50}, rising={}, off_52w_high_pct=None, off_6m_high_pct=None, bars=60)


@pytest.mark.parametrize(
    "trigger, price, sma50, expected",
    [
        ("bullish", 105.0, 100.0, "bullish"),  # bullish above the 50 matches
        ("bullish", 95.0, 100.0, None),  # bullish below the 50 does not
        ("bullish", 100.0, 100.0, None),  # exactly on the 50 is not above it
        ("bearish", 95.0, 100.0, "bearish"),  # bearish below the 50 matches
        ("bearish", 105.0, 100.0, None),  # bearish above the 50 does not
        ("bearish", 100.0, 100.0, None),  # exactly on the 50 is not below it
        ("bullish", 105.0, None, None),  # no 50-day SMA: no match
        ("bearish", 95.0, None, None),
        (None, 105.0, 100.0, None),  # no MACD trigger: no match
    ],
)
def test_daily_trend_setup_needs_the_close_on_the_matching_side_of_the_50(trigger, price, sma50, expected):
    assert daily_trend_setup(trigger, _trend(price, sma50)) == expected


def test_daily_trend_setup_without_trend_metrics_does_not_match():
    assert daily_trend_setup("bullish", None) is None
    assert daily_trend_setup("bearish", None) is None


def test_daily_trend_setup_with_short_history_has_no_50_day_sma():
    from strat.leadership import trend_metrics

    short = pd.DataFrame({"close": [100.0 + i for i in range(40)], "high": [101.0 + i for i in range(40)]})
    trend = trend_metrics(short)
    assert trend is not None and trend.sma[50] is None
    assert daily_trend_setup("bullish", trend) is None
