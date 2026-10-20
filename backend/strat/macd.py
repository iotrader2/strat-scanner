"""Daily MACD (6, 20, 9) histogram triggers.

The chart draws this same MACD in the browser. The EMA is seeded with the SMA of
the first ``period`` values, then smoothed with ``k = 2 / (period + 1)``. The
signal is an EMA of the MACD line only: bars before the slow EMA exists are
skipped, not filled with zeros. The histogram is MACD minus signal.

A bar is green when the histogram is at or above zero and red when it is below,
matching the histogram colors. A bullish trigger is the first green bar after 3
or more red bars. A bearish trigger is the first red bar after 3 or more green
bars. A later bar of the same color does not trigger again.

The scanner asks only whether the most recent daily bar is one of those
triggers. That bar is the last row of the daily frame the scan already uses,
which includes today's in-progress session when the cache has overlaid it.
Daily Strat (the D badge, inside day, hammer, and M+W+D continuity) reads that
same candle. A stricter "last completed session only" rule would match the
weekly setups, which ignore the week still in progress, but it would make this
filter disagree with the arrow on the current candle during the session.

The Daily bullish / bearish trend change *setups* (filter, row chip, hero count) also need the
latest close on the right side of the 50-day SMA: above it for bullish, below it for bearish
(``daily_trend_setup``). Names without a 50-day SMA never match. The chart arrows stay purely
MACD-based.

The Weekly bullish / bearish trend change setups use the same trigger on the weekly candles the
weekly chart draws, including the week still in progress (``resample(daily, "W",
completed_only=False)``), the same way the daily setup uses today's bar. The weekly Strat setups
still read completed weeks only. The trigger is confirmed by the latest weekly close (today's
price) against the 10-week SMA, the weekly analog of the 50-day (``weekly_trend_setup``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import numpy as np
import pandas as pd

MACD_FAST = 6
MACD_SLOW = 20
MACD_SIGNAL = 9
TRIGGER_MIN_RUN = 3

BULLISH = "bullish"
BEARISH = "bearish"
SETUP_SMA = 50
WEEKLY_SETUP_SMA = 10

if TYPE_CHECKING:
    from .leadership import Trend


def ema(values: np.ndarray, period: int) -> np.ndarray:
    """SMA-seeded EMA. NaN until ``period`` values exist. Same recurrence as the chart."""
    values = np.asarray(values, dtype=np.float64)
    out = np.full(values.shape[0], np.nan, dtype=np.float64)
    if period < 1 or values.shape[0] < period:
        return out
    k = 2.0 / (period + 1)
    prev = float(np.sum(values[:period]) / period)
    out[period - 1] = prev
    keep = 1.0 - k
    for i in range(period, values.shape[0]):
        prev = float(values[i]) * k + prev * keep
        out[i] = prev
    return out


def macd_histogram(
    closes: np.ndarray,
    fast: int = MACD_FAST,
    slow: int = MACD_SLOW,
    signal_period: int = MACD_SIGNAL,
) -> np.ndarray:
    """Histogram aligned to ``closes``. NaN until both EMAs and the signal exist."""
    closes = np.asarray(closes, dtype=np.float64)
    if fast < 1 or slow < 1 or signal_period < 1 or closes.size == 0:
        return np.full(closes.shape[0], np.nan, dtype=np.float64)
    line = ema(closes, fast) - ema(closes, slow)
    valid = np.flatnonzero(~np.isnan(line))
    signal = np.full(closes.shape[0], np.nan, dtype=np.float64)
    if valid.size:
        seeded = ema(line[valid], signal_period)
        signal[valid] = seeded
    return line - signal


def histogram_triggers(histogram: np.ndarray, min_run: int = TRIGGER_MIN_RUN) -> list[tuple[int, str, float]]:
    """``(index, "up"|"down", value)`` for each trigger bar. NaN bars are skipped."""
    histogram = np.asarray(histogram, dtype=np.float64)
    triggers: list[tuple[int, str, float]] = []
    reds = 0
    greens = 0
    for i, value in enumerate(histogram):
        if np.isnan(value):
            continue
        if value >= 0:
            if reds >= min_run:
                triggers.append((i, "up", float(value)))
            reds = 0
            greens += 1
        else:
            if greens >= min_run:
                triggers.append((i, "down", float(value)))
            greens = 0
            reds += 1
    return triggers


def trend_from_histogram(histogram: np.ndarray, min_run: int = TRIGGER_MIN_RUN) -> Optional[str]:
    """``bullish`` or ``bearish`` when the last histogram bar is that trigger, else None.

    A trigger on an earlier bar does not count. Two bars of the old color are
    not enough; the run has to be at least ``min_run`` (3).
    """
    histogram = np.asarray(histogram, dtype=np.float64)
    triggers = histogram_triggers(histogram, min_run)
    if not triggers:
        return None
    last = None
    for i in range(histogram.shape[0] - 1, -1, -1):
        if not np.isnan(histogram[i]):
            last = i
            break
    if last is None or triggers[-1][0] != last:
        return None
    return BULLISH if triggers[-1][1] == "up" else BEARISH


def trigger_dates(times: list[str], closes: np.ndarray) -> list[dict]:
    """Trigger dates for a close series. ``times`` lines up with ``closes``."""
    histogram = macd_histogram(np.asarray(closes, dtype=np.float64))
    return [
        {"time": times[i], "direction": direction, "value": value}
        for i, direction, value in histogram_triggers(histogram)
    ]


def latest_daily_trend(daily: Optional[pd.DataFrame]) -> Optional[str]:
    """Trend change on the most recent daily bar, or None.

    ``daily`` is the frame the scan already built. During the regular session
    that includes today's unfinished bar (see ``data._overlay_session``), and
    this uses it, the same way the daily Strat state does. It does not fetch
    anything and it does not keep the histogram.
    """
    if daily is None or len(daily) == 0 or "close" not in daily.columns:
        return None
    closes = np.asarray(daily["close"].to_numpy(dtype=np.float64, copy=False))
    return trend_from_histogram(macd_histogram(closes))


def daily_trend_setup(trigger: Optional[str], trend: "Optional[Trend]", period: int = SETUP_SMA) -> Optional[str]:
    """The Daily bullish / bearish trend change setup: a MACD trigger on the latest bar, confirmed by the 50-day SMA.

    ``trigger`` is ``latest_daily_trend`` for the same daily frame and ``trend`` is its ``trend_metrics``
    (both read the last close). Bullish needs that close above the SMA, bearish below it. Without
    the SMA (fewer than ``period`` bars) nothing matches.
    """
    if trigger is None or trend is None:
        return None
    sma = trend.sma.get(period)
    if sma is None:
        return None
    if trigger == BULLISH and trend.price > sma:
        return BULLISH
    if trigger == BEARISH and trend.price < sma:
        return BEARISH
    return None


def latest_weekly_trend(weekly: Optional[pd.DataFrame]) -> Optional[str]:
    """Trend change on the current weekly bar, or None. ``weekly`` is ``resample(daily, "W", completed_only=False)``,
    so the week in progress counts, like today's bar for ``latest_daily_trend``."""
    return latest_daily_trend(weekly)


def weekly_trend_setup(trigger: Optional[str], weekly: Optional[pd.DataFrame], period: int = WEEKLY_SETUP_SMA) -> Optional[str]:
    """The Weekly bullish / bearish trend change setup: a weekly MACD trigger, confirmed by the 10-week SMA.

    ``trigger`` is ``latest_weekly_trend`` for the same weekly frame. Bullish needs the last weekly
    close above the SMA of the last ``period`` weekly closes, bearish below it. Fewer than ``period``
    weeks: nothing matches.
    """
    if trigger is None or weekly is None or len(weekly) < period or "close" not in weekly.columns:
        return None
    closes = weekly["close"].to_numpy(dtype=np.float64)
    price = float(closes[-1])
    sma = float(closes[-period:].mean())
    if trigger == BULLISH and price > sma:
        return BULLISH
    if trigger == BEARISH and price < sma:
        return BEARISH
    return None
