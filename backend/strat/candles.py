"""Pure candle logic: Strat classification, continuity and hammers.

Everything here works on plain ``Candle`` tuples so it can be unit tested
without pandas or network access. The Strat *numbers* (1 / 2U / 2D / 3),
continuity and hammers are still used for the chart markers, the Candle
Pattern filter and the M/W/D badges. The Strat *setups* were removed on
2026-11-07 and replaced by the RealSimpleAriel setups in
``strat.ariel_setups`` (daily bars, 15-minute entry).
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
    return price_vs_open(c.close, c.open)


def price_vs_open(price: float, open_: float) -> str:
    """Green if ``price`` is above ``open_``, red if below, flat if equal."""
    if price > open_:
        return "green"
    if price < open_:
        return "red"
    return "flat"


def continuity_color(state: Optional["TimeframeState"]) -> Optional[str]:
    """The color Continuity scores and shows: the bar in progress when known, else the last completed bar."""
    if state is None:
        return None
    return state.live_color or state.color


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
    """A long setup found on one timeframe.

    ``stop`` is the playbook's defined-risk stop for the setup (RealSimpleAriel
    setups carry one; the old Strat setups did not). ``entry_tf`` is the
    chart used only to time the entry — "15m" for the Ariel setups.
    """

    kind: str  # machine key, e.g. "episodic-pivot"
    label: str  # human label, e.g. "Episodic Pivot"
    trigger: float
    triggered: bool  # True once price already traded through the trigger
    detail: str = ""
    # True when the break happened in the bar still in progress (the trigger itself is from completed bars).
    live: bool = False
    stop: Optional[float] = None
    entry_tf: str = "15m"


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
    # Continuity of the bar in progress (current month / week / today's session): price vs that bar's open. The
    # fields above stay on the last completed bar (Strat number, triggers, setups). None when not computed.
    live_color: Optional[str] = None
    live_open: Optional[float] = None


def find_long_setups(candles: Sequence[Candle], types: Sequence[Optional[str]]) -> list[Setup]:
    """Removed 2026-11-07: The Strat long setups (2-1-2, 3-1-2, hammers, …)
    were replaced by the RealSimpleAriel setups in :mod:`strat.ariel_setups`,
    detected on daily bars in :func:`strat.scanner.scan_symbol`. Kept as a
    no-op so old imports fail loudly at the call site instead of silently
    returning Strat setups; delete it once no caller references it.
    """
    return []


def timeframe_state(tf: str, candles: Sequence[Candle]) -> Optional[TimeframeState]:
    if not candles:
        return None
    types = classify_series(candles)
    cur = candles[-1]
    # Setups are no longer detected here: the Ariel setups live on the daily
    # timeframe and need volume, which ``Candle`` does not carry. The scanner
    # attaches them to the "D" state from the daily bars (see
    # ``strat.scanner.scan_symbol``); M/W states carry no setups.
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
        setups=[],
    )


PERIOD_WORDS = {"D": "day", "W": "week", "M": "month"}


def apply_live_triggers(
    state: Optional[TimeframeState], live_high: Optional[float], tolerance: float = 0.0
) -> Optional[TimeframeState]:
    """Mark pending long setups triggered once the bar still in progress has traded above the trigger.

    Setups and their trigger levels come from completed bars only; the bar in progress never sets a trigger. It only
    decides whether a pending trigger has already been broken: ``live_high`` is the high of the in-progress bar
    (which includes today's session and the latest price), or None when no bar is in progress. Strictly above, like a break.
    Only long setups exist, so there is no short-side mirror to apply. ``tolerance`` (dollars) is the
    IEX allowance: a live high from the real-time IEX feed must clear the trigger by more than that.
    """
    if state is None or live_high is None:
        return state
    word = PERIOD_WORDS.get(state.tf, "bar")
    for setup in state.setups:
        if not setup.triggered and live_high > setup.trigger + tolerance:
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
