"""Pure Strat candle logic: classification, continuity, hammers and long combos.

Everything here works on plain ``Candle`` tuples so it can be unit tested
without pandas or network access.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import NamedTuple, Optional, Sequence

INSIDE = "1"
TWO_UP = "2U"
TWO_DOWN = "2D"
OUTSIDE = "3"


class Candle(NamedTuple):
    open: float
    high: float
    low: float
    close: float


def classify(prev: Candle, cur: Candle) -> str:
    """Strat number of ``cur`` relative to ``prev``.

    1  = inside (does not take out either side of the previous range)
    2U = takes out the previous high only
    2D = takes out the previous low only
    3  = outside (takes out both sides)
    """
    broke_high = cur.high > prev.high
    broke_low = cur.low < prev.low
    if broke_high and broke_low:
        return OUTSIDE
    if broke_high:
        return TWO_UP
    if broke_low:
        return TWO_DOWN
    return INSIDE


def classify_series(candles: Sequence[Candle]) -> list[Optional[str]]:
    """Strat number for every candle; the first one has no reference so is ``None``."""
    out: list[Optional[str]] = [None]
    for prev, cur in zip(candles, candles[1:]):
        out.append(classify(prev, cur))
    return out[: len(candles)]


def continuity(c: Candle) -> str:
    """Green if price is above the period open, red if below, flat if equal."""
    if c.close > c.open:
        return "green"
    if c.close < c.open:
        return "red"
    return "flat"


def is_hammer(
    c: Candle,
    wick_body_ratio: float = 2.0,
    max_upper_wick_frac: float = 0.1,
    close_top_frac: float = 1 / 3,
) -> bool:
    """Hammer: lower wick >= 2x body, small upper wick, close in the top third.

    The upper wick counts as "small" when it is no bigger than the body or no
    bigger than ``max_upper_wick_frac`` of the full range, whichever is larger;
    that keeps near-doji hammers valid without accepting long upper shadows.
    """
    rng = c.high - c.low
    if rng <= 0:
        return False
    body = abs(c.close - c.open)
    lower_wick = min(c.open, c.close) - c.low
    upper_wick = c.high - max(c.open, c.close)
    if lower_wick <= 0 or lower_wick < wick_body_ratio * body:
        return False
    if upper_wick > max(body, max_upper_wick_frac * rng):
        return False
    return (c.close - c.low) >= (1 - close_top_frac) * rng


@dataclass
class Setup:
    """A long setup found on one timeframe."""

    kind: str  # machine key, e.g. "inside", "hammer", "2-1-2"
    label: str  # human label, e.g. "2-1-2 bullish"
    trigger: float
    triggered: bool  # True once price already traded through the trigger
    detail: str = ""
    # True when the break happened in the week / month still in progress (the trigger itself is from completed bars).
    live: bool = False


@dataclass
class TimeframeState:
    tf: str
    strat: Optional[str]
    prev_strat: Optional[str]
    color: str
    open: float
    high: float
    low: float
    close: float
    inside: bool
    hammer: bool
    setups: list[Setup] = field(default_factory=list)


def find_long_setups(candles: Sequence[Candle], types: Sequence[Optional[str]]) -> list[Setup]:
    """Long-only Strat setups ending on the last (current) candle."""
    setups: list[Setup] = []
    if len(candles) < 2:
        return setups
    cur = candles[-1]
    prev = candles[-2]
    t0 = types[-1]
    t1 = types[-2] if len(types) >= 2 else None
    t2 = types[-3] if len(types) >= 3 else None

    if t0 == INSIDE:
        if t1 in (TWO_UP, TWO_DOWN):
            label, kind = "2-1 → 2-1-2 setup", "2-1-2-pending"
        elif t1 == OUTSIDE:
            label, kind = "3-1 → 3-1-2 setup", "3-1-2-pending"
        else:
            label, kind = "Inside bar", "inside"
        setups.append(
            Setup(kind, label, cur.high, False, "break of the inside-bar high")
        )

    if is_hammer(cur):
        setups.append(Setup("hammer", "Hammer", cur.high, False, "break of the hammer high"))

    if t0 == TWO_UP and t1 == INSIDE:
        if t2 in (TWO_UP, TWO_DOWN):
            label = "2D-1-2U reversal" if t2 == TWO_DOWN else "2U-1-2U continuation"
            setups.append(Setup("2-1-2", f"2-1-2 bullish ({label})", prev.high, True))
        elif t2 == OUTSIDE:
            setups.append(Setup("3-1-2", "3-1-2 bullish", prev.high, True))

    if t0 == TWO_UP and t1 == TWO_DOWN:
        if t2 == INSIDE:
            setups.append(Setup("1-2-2", "1-2-2 RevStrat", prev.high, True))
        else:
            setups.append(Setup("2D-2U", "2D-2U reversal", prev.high, True))

    if t0 != INSIDE and len(candles) >= 2 and is_hammer(prev) and cur.high > prev.high:
        setups.append(
            Setup("hammer-triggered", "Hammer triggered", prev.high, True, "broke the prior hammer high")
        )

    return setups


def timeframe_state(tf: str, candles: Sequence[Candle]) -> Optional[TimeframeState]:
    if not candles:
        return None
    types = classify_series(candles)
    cur = candles[-1]
    return TimeframeState(
        tf=tf,
        strat=types[-1],
        prev_strat=types[-2] if len(types) >= 2 else None,
        color=continuity(cur),
        open=cur.open,
        high=cur.high,
        low=cur.low,
        close=cur.close,
        inside=types[-1] == INSIDE,
        hammer=is_hammer(cur),
        setups=find_long_setups(candles, types),
    )


PERIOD_WORDS = {"W": "week", "M": "month"}


def apply_live_triggers(state: Optional[TimeframeState], live_high: Optional[float]) -> Optional[TimeframeState]:
    """Mark pending long setups triggered once the bar still in progress has traded above the trigger.

    Setups and their trigger levels come from completed bars only (``find_long_setups`` on the completed weekly or
    monthly candles); the week or month in progress never sets a trigger. It only decides whether a pending trigger
    has already been broken: ``live_high`` is the high of the in-progress bar (which includes today's session and the
    latest price), or None when no bar is in progress (e.g. over the weekend for weeks). Strictly above, like a break.
    Only long setups exist, so there is no short-side mirror to apply.
    """
    if state is None or live_high is None:
        return state
    word = PERIOD_WORDS.get(state.tf, "bar")
    for setup in state.setups:
        if not setup.triggered and live_high > setup.trigger:
            setup.triggered = True
            setup.live = True
            setup.detail = f"broke {setup.trigger:.2f} this {word} (high {live_high:.2f})"
    return state


def candle_pattern(candles: Sequence[Candle]) -> dict:
    """Inside bar / hammer on the last candle of ``candles`` (pass completed bars only), same rules as the Strat state."""
    if not candles:
        return {"inside": False, "hammer": False}
    types = classify_series(candles)
    return {"inside": types[-1] == INSIDE, "hammer": is_hammer(candles[-1])}
