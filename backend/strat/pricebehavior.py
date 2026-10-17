"""Price behaviour of the last few weeks: how tight the daily ranges are and whether a "kill candle" just printed.

Both are pure functions of the daily bars, so they work on a history cut off at any date (used by the backtest).

*Range tightness* compares the average true range (as a % of price) of the last 10 sessions with the stock's own
50-session baseline, and the last 5 sessions with the last 20 (contraction). Orderly, contracting ranges score high;
wide, expanding ranges score low.

A *kill candle* is a wide-range, heavy-volume DOWN day that closes near its low. It is a distribution warning, so it
lowers the score for a while (fading as it ages) unless price takes back the candle's high.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

# Tightness
RECENT_BARS = 10
BASELINE_BARS = 50
SHORT_BARS = 5
MEDIUM_BARS = 20
# Share of the tightness points each measure is worth.
RELATIVE_WEIGHT = 0.6  # last-10 range vs the 50-day baseline
CONTRACTION_WEIGHT = 0.4  # last-5 range vs the last-20
# (full credit, no credit) for each measure.
RELATIVE_RANGE = (0.85, 1.25)  # ratio of recent to baseline range
CONTRACTION_RANGE = (0.80, 1.20)  # ratio of the last 5 to the last 20 sessions

# Kill candle
KILL_LOOKBACK = 10  # sessions (including today) in which a kill candle counts
KILL_RANGE_X_ATR = 2.5  # true range at least this many times the prior 20-day average true range
KILL_VOLUME_X = 1.5  # volume at least this many times the prior 50-day average volume
KILL_CLOSE_POSITION = 0.35  # closes in the lower 35% of its range (0 = at the low)
KILL_PENALTY = 0.25  # share of the score removed on the day (fades to 0 over the lookback)
ATR_BARS = 20
VOLUME_BARS = 50


@dataclass(frozen=True)
class Tightness:
    range10_pct: float  # average true range of the last 10 sessions, % of price
    range50_pct: float
    range5_pct: float
    range20_pct: float

    @property
    def ratio(self) -> float:
        """Recent (10-day) range relative to the stock's own 50-day baseline; below 1 is tighter than usual."""
        return self.range10_pct / self.range50_pct if self.range50_pct > 0 else 1.0

    @property
    def contraction(self) -> float:
        """Last 5 sessions relative to the last 20; below 1 is contracting."""
        return self.range5_pct / self.range20_pct if self.range20_pct > 0 else 1.0


def true_range_pct(daily: pd.DataFrame) -> pd.Series:
    """Daily true range (gaps included) as a percent of the close."""
    prev = daily.close.shift(1)
    high = pd.concat([daily.high, prev], axis=1).max(axis=1)
    low = pd.concat([daily.low, prev], axis=1).min(axis=1)
    return (high - low) / daily.close * 100.0


def range_stats(daily: pd.DataFrame) -> Optional[Tightness]:
    if daily is None or len(daily) < BASELINE_BARS + 1:
        return None
    tr = true_range_pct(daily).iloc[1:]
    return Tightness(
        float(tr.tail(RECENT_BARS).mean()),
        float(tr.tail(BASELINE_BARS).mean()),
        float(tr.tail(SHORT_BARS).mean()),
        float(tr.tail(MEDIUM_BARS).mean()),
    )


def _fraction(value: float, full: float, none: float) -> float:
    """1 at ``full`` (or better), 0 at ``none`` (or worse), linear in between (works for either direction)."""
    return min(1.0, max(0.0, (none - value) / (none - full)))


def tightness_fraction(t: Optional[Tightness]) -> float:
    """0..1 tightness: 1 is a calm, contracting range, 0 is wide and expanding."""
    if t is None:
        return 0.0
    return (
        RELATIVE_WEIGHT * _fraction(t.ratio, *RELATIVE_RANGE)
        + CONTRACTION_WEIGHT * _fraction(t.contraction, *CONTRACTION_RANGE)
    )


@dataclass(frozen=True)
class KillCandle:
    date: str
    age: int  # sessions ago (0 = the latest bar)
    range_x_atr: float
    volume_x: float
    close_position: float  # 0 = closed at the low, 1 = at the high
    high: float
    reclaimed: bool  # the latest close is above the candle's high
    penalty: float  # share of the score removed now, after fading (0 when reclaimed or expired)


def kill_penalty(age: int, reclaimed: bool) -> float:
    """The penalty fades linearly from KILL_PENALTY on the day to nothing at KILL_LOOKBACK sessions."""
    if reclaimed or age >= KILL_LOOKBACK:
        return 0.0
    return KILL_PENALTY * (1.0 - age / KILL_LOOKBACK)


def find_kill_candle(daily: pd.DataFrame) -> Optional[KillCandle]:
    """The kill candle in the last KILL_LOOKBACK sessions with the biggest remaining penalty (None when there is none)."""
    if daily is None or len(daily) < max(ATR_BARS, VOLUME_BARS) + KILL_LOOKBACK:
        return None
    prev = daily.close.shift(1)
    tr = pd.concat([daily.high, prev], axis=1).max(axis=1) - pd.concat([daily.low, prev], axis=1).min(axis=1)
    last_close = float(daily.close.iloc[-1])
    n = len(daily)
    best: Optional[KillCandle] = None
    for age in range(KILL_LOOKBACK):
        i = n - 1 - age
        row = daily.iloc[i]
        span = float(row.high - row.low)
        if span <= 0 or not row.close < row.open:
            continue
        atr = float(tr.iloc[i - ATR_BARS : i].mean())
        avg_vol = float(daily.volume.iloc[i - VOLUME_BARS : i].mean())
        if atr <= 0 or avg_vol <= 0:
            continue
        range_x, vol_x = float(tr.iloc[i]) / atr, float(row.volume) / avg_vol
        pos = float(row.close - row.low) / span
        if range_x < KILL_RANGE_X_ATR or vol_x < KILL_VOLUME_X or pos > KILL_CLOSE_POSITION:
            continue
        reclaimed = last_close > float(row.high)
        candle = KillCandle(
            daily.index[i].strftime("%Y-%m-%d"), age, round(range_x, 2), round(vol_x, 2), round(pos, 2),
            float(row.high), reclaimed, kill_penalty(age, reclaimed),
        )
        if best is None or candle.penalty > best.penalty:
            best = candle
    return best
