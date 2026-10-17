"""Recent breakouts: a weekly close above a tight base on heavy volume, meant to surface future leaders early.

A *tight base* is 3 to 10 weeks of narrow weekly ranges (their average true range is well below the stock's own
range over the 20 weeks before the base) that stay inside a modest depth. The *breakout* is a weekly candle that
closes above the base high, on weekly volume well above the 10-week average, closing in the upper part of its range.
Only the latest few weekly candles count, and a kill candle (a wide, heavy down day) since cancels the setup.
A *failed breakout* is the same breakout, up to 8 weeks old, that has since closed back below the base high.

Pure functions of the daily bars, so they work on a history cut off at any date (used by the backtest).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from .data import resample
from .pricebehavior import KillCandle

BASE_MIN_WEEKS = 3
BASE_MAX_WEEKS = 10
BASELINE_WEEKS = 20  # weeks before the base that its ranges are compared with
MIN_BASELINE_WEEKS = 10
BASE_TIGHT_RATIO = 0.85  # base average weekly range at most this share of the baseline's
BASE_MAX_DEPTH_PCT = 15.0  # base high to base low, % of the base high
VOLUME_WEEKS = 10
BREAKOUT_VOLUME_X = 2.0  # breakout-week volume vs the average of the 10 weeks before it
BREAKOUT_CLOSE_POSITION = 0.65  # the week closes in the upper 35% of its range
RECENT_WEEKS = 3  # the breakout week is one of the last 3 weekly candles
MIN_RS = 0.50  # relative-strength floor: future leaders may still be mid-pack
FAILED_LOOKBACK_WEEKS = 8  # Failed breakouts: the breakout week is one of the weekly candles 1 to 8 weeks back


@dataclass(frozen=True)
class Breakout:
    week: str  # first trading day of the breakout week
    weeks_ago: int  # 0 = the current week
    base_weeks: int
    base_high: float
    base_range_pct: float  # average weekly true range of the base, % of price
    baseline_range_pct: float
    volume_x: float
    close_position: float
    close: float

    @property
    def tightness(self) -> float:
        """Base range relative to the baseline (below 1 is tighter)."""
        return self.base_range_pct / self.baseline_range_pct if self.baseline_range_pct > 0 else 1.0


def _weekly(daily: pd.DataFrame) -> tuple[pd.DataFrame, float]:
    """Weekly bars plus how much to scale the (possibly part-finished) last week's volume to a full week."""
    weekly = resample(daily, "W")
    last_start = weekly.index[-1]
    sessions = int((daily.index >= last_start).sum())
    finished = daily.index[-1].weekday() == 4
    scale = 5.0 / sessions if not finished and 0 < sessions < 5 else 1.0
    return weekly, scale


def _week_range_pct(weekly: pd.DataFrame) -> pd.Series:
    prev = weekly.close.shift(1)
    high = pd.concat([weekly.high, prev], axis=1).max(axis=1)
    low = pd.concat([weekly.low, prev], axis=1).min(axis=1)
    return (high - low) / weekly.close * 100.0


def find_base(weekly: pd.DataFrame, rng: pd.Series, j: int) -> Optional[tuple[int, float, float, float]]:
    """The longest tight base ending the week before bar ``j``: (weeks, high, base range %, baseline range %)."""
    for length in range(BASE_MAX_WEEKS, BASE_MIN_WEEKS - 1, -1):
        start = j - length
        if start < 1:
            continue
        prior = rng.iloc[max(1, start - BASELINE_WEEKS) : start]
        if len(prior) < MIN_BASELINE_WEEKS:
            continue
        base = weekly.iloc[start:j]
        base_rng = float(rng.iloc[start:j].mean())
        baseline = float(prior.mean())
        high, low = float(base.high.max()), float(base.low.min())
        if baseline <= 0 or high <= 0:
            continue
        if base_rng > BASE_TIGHT_RATIO * baseline or (high - low) / high * 100.0 > BASE_MAX_DEPTH_PCT:
            continue
        return length, high, base_rng, baseline
    return None


def _breakout_at(weekly: pd.DataFrame, rng: pd.Series, j: int, scale: float) -> Optional[Breakout]:
    """The breakout the weekly candle ``j`` makes (None when it is not one); ``weeks_ago`` is counted from the last bar."""
    n = len(weekly)
    if j < BASE_MIN_WEEKS + 1:
        return None
    bar = weekly.iloc[j]
    span = float(bar.high - bar.low)
    if span <= 0:
        return None
    position = float(bar.close - bar.low) / span
    vol = float(bar.volume) * (scale if j == n - 1 else 1.0)
    avg_vol = float(weekly.volume.iloc[max(0, j - VOLUME_WEEKS) : j].mean())
    if avg_vol <= 0 or vol / avg_vol < BREAKOUT_VOLUME_X or position < BREAKOUT_CLOSE_POSITION:
        return None
    base = find_base(weekly, rng, j)
    if base is None or float(bar.close) <= base[1]:
        return None
    length, high, base_rng, baseline = base
    return Breakout(
        weekly.index[j].strftime("%Y-%m-%d"), n - 1 - j, length, round(high, 2), round(base_rng, 2), round(baseline, 2),
        round(vol / avg_vol, 2), round(position, 2), round(float(bar.close), 2),
    )


def _enough_history(daily: pd.DataFrame) -> bool:
    return daily is not None and len(daily) >= 5 * (BASE_MIN_WEEKS + MIN_BASELINE_WEEKS + 2)


def find_breakout(daily: pd.DataFrame, kill: Optional[KillCandle] = None) -> Optional[Breakout]:
    """The latest qualifying breakout among the last RECENT_WEEKS weekly candles (None when there is none)."""
    if not _enough_history(daily):
        return None
    if kill is not None and kill.penalty > 0:
        return None
    weekly, scale = _weekly(daily)
    n = len(weekly)
    rng = _week_range_pct(weekly)
    for ago in range(RECENT_WEEKS):
        found = _breakout_at(weekly, rng, n - 1 - ago, scale)
        if found is not None:
            return found
    return None


@dataclass(frozen=True)
class FailedBreakout:
    week: str  # first trading day of the breakout week
    weeks_ago: int
    base_weeks: int
    level: float  # the base high the breakout cleared
    volume_x: float
    breakout_close: float
    failed_on: str  # first close below the level since price last closed at or above it
    sessions_below: int  # sessions since then, the failure session included
    close: float  # latest close
    below_pct: float  # latest close vs the level, % (negative)
    low_pct: float  # deepest close since the breakout vs the level, % (<= below_pct)


def find_failed_breakout(daily: pd.DataFrame, lookback: int = FAILED_LOOKBACK_WEEKS) -> Optional[FailedBreakout]:
    """The latest breakout (same detection as Recent breakouts) that has since lost its level.

    Looks at the weekly candles from the current one back ``lookback`` weeks. Of the qualifying breakouts the most recent
    one counts (a breakout in the current week has not had time to fail, and hides older ones). It has failed when the
    latest daily close is below the base high it cleared. A kill candle does not hide it. The failure date is the first
    close below the level in the current run below it, so a name that dipped, reclaimed the level and dipped again is
    dated by the second dip.
    """
    if not _enough_history(daily):
        return None
    weekly, scale = _weekly(daily)
    n = len(weekly)
    rng = _week_range_pct(weekly)
    found: Optional[Breakout] = None
    j = n - 1
    for ago in range(lookback + 1):
        j = n - 1 - ago
        found = _breakout_at(weekly, rng, j, scale)
        if found is not None:
            break
    if found is None or found.weeks_ago == 0:
        return None
    after = daily.close[daily.index >= weekly.index[j + 1]]
    if after.empty:
        return None
    level = found.base_high
    close = float(after.iloc[-1])
    if close >= level:
        return None
    below = after < level
    run_start = len(below)
    while run_start > 0 and below.iloc[run_start - 1]:
        run_start -= 1
    return FailedBreakout(
        week=found.week,
        weeks_ago=found.weeks_ago,
        base_weeks=found.base_weeks,
        level=level,
        volume_x=found.volume_x,
        breakout_close=found.close,
        failed_on=after.index[run_start].strftime("%Y-%m-%d"),
        sessions_below=len(below) - run_start,
        close=round(close, 2),
        below_pct=round((close / level - 1) * 100.0, 2),
        low_pct=round((float(after.min()) / level - 1) * 100.0, 2),
    )
