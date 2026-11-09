"""Intraday entries for daily setups on 15-minute bars: a pullback to a rising 120 / 240 / 480 EMA (long), or a
rally into a falling one (short).

The setup decision is daily: the caller checks only names with a daily setup on the scanner (``alert_symbols`` /
``alert_short_symbols`` in ``api``): a long daily setup is checked for the long pullback, a short daily setup for the
short rally. The 15-minute EMAs only time the entry.

Everything here is pure: :func:`simulate` takes one symbol's completed regular-session bars for one
day plus a little context and returns the alerts that day would have produced, each with its outcome
so far. The live poll (``alerts_live``) and the replay script call the same function, so a replay
shows exactly what the tab would have shown.

Bars are dicts ``{"t": datetime (bar start, UTC), "o", "h", "l", "c", "v"}``. Bar ``i`` is the
``i``-th 15-minute bar after the open, so bar 0 is the opening bar (6:30 Phoenix while New York is on
daylight time). The moving averages are EMAs of regular-session 15-minute closes (premarket and after
hours are left out), the same lines the 15-minute chart draws: 120 (red), 240 (yellow) and 480 (blue).
Each is carried over from the prior sessions (``Context.ma_tail``) and continued with today's closes.

An alert has two steps.

1. **Watch** (status ``pending``). A completed bar touches a rising EMA coming from above:

   * the EMA is rising: its value on the bar before is higher than ``rising_bars`` bars earlier;
   * the bar before closed above the EMA (more than ``touch_tol_pct`` over it), so this is a pullback
     to the line, not price already sitting on it;
   * this bar's low reaches the EMA (within ``touch_tol_pct``);
   * this bar did not close more than ``hold_pct`` under the EMA.

   When one bar touches more than one EMA, the alert is for the lowest one it held. The buy stop is the
   touch bar's high + $0.01 and the stop is the pullback low - $0.01.

2. **Trigger** (status ``triggered``). A later bar trades over the previous 15-minute candle's high +
   $0.01; the fill is always that price (a gap over it does not move the entry). While the alert waits, each completed bar that does not trigger moves the buy stop to its own
   high + $0.01 and the stop to the lowest low so far - $0.01. The watch is cancelled when a bar closes
   more than ``hold_pct`` under the EMA, and expires after ``watch_bars`` bars without a trigger. The live
   poll also checks the forming bar, so a trigger shows up within a poll instead of after the candle closes.

After the fill the trade is managed on completed bars: the stop, break-even after
``breakeven_after_new_highs`` new-high bars, an exit on a close more than ``hold_pct`` under the EMA
(``exit_close_under_ma``), and the session end.

One live alert per name at a time, and no new alert once ``max_attempts`` of the name's alerts have
triggered that day. Which names are checked (any name with a daily setup on that side) is decided by the caller.

**Short side** (``side="short"``, setups ``s120`` / ``s240`` / ``s480``) is the exact mirror, for short daily setups: a
completed bar rallies up into a *falling* EMA coming from below (the bar before closed under it, this bar's
high reaches it, the close did not go more than ``hold_pct`` over it). The sell stop is the touch bar's low -
$0.01 and the stop the rally high + $0.01; while waiting, both follow the bars. After the fill: the stop
above, break-even after ``breakeven_after_new_highs`` new-low bars, an exit on a close more than ``hold_pct``
over the EMA, and the session end. For a short, ``high_reached`` holds the lowest price reached (the best
price) and R is measured downward. When a bar touches several falling EMAs the alert is for the highest.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional, Sequence

from .earnings import DEFAULT_WARNING_WINDOW_DAYS

TICK = 0.01
BAR_MINUTES = 15
BAR = timedelta(minutes=BAR_MINUTES)
SESSION_BARS = 390 // BAR_MINUTES  # bars in a full regular session
MA_PERIODS = (120, 240, 480)
EMA_LONG = MA_PERIODS[-1]
LONG_SETUPS = tuple(str(p) for p in MA_PERIODS)
SHORT_SETUPS = tuple(f"s{p}" for p in MA_PERIODS)
SETUPS = LONG_SETUPS + SHORT_SETUPS
SETUP_NAMES = {
    **{str(p): f"Pullback to rising {p} EMA" for p in MA_PERIODS},
    **{f"s{p}": f"Short: rally to falling {p} EMA" for p in MA_PERIODS},
}


def setup_side(setup: str) -> str:
    """"short" for the s120 / s240 / s480 setups, else "long"."""
    return "short" if str(setup).startswith("s") else "long"


def setup_period(setup: str) -> int:
    return int(str(setup).lstrip("s"))
ACTIVE = ("pending", "triggered")
FINAL = ("stopped", "breakeven", "exited", "expired", "cancelled")
TAIL_KEEP = 30  # prior-session EMA values kept per period (enough for any ``rising_bars``)


@dataclass
class Settings:
    """Adjustable rule values. Percentages are in percent (0.5 means 0.5%)."""

    # Which names: any stock or ETF with a long daily setup, highest scan score first, at most this many.
    max_symbols: int = 150
    # Short side: any stock or ETF with a short daily setup, weakest RS first, at most this many.
    shorts: int = 1  # 1 = alert short setups too, 0 = longs only
    max_short_symbols: int = 75
    # Which averages (1 = on, 0 = off).
    ma_120: int = 1
    ma_240: int = 1
    ma_480: int = 1
    touch_tol_pct: float = 0.1  # a low this close above the EMA counts as a touch
    hold_pct: float = 0.3  # a close more than this under the EMA has lost it
    rising_bars: int = 4  # rising = higher than this many bars earlier (4 bars = 1 hour)
    watch_bars: int = 4  # bars after the touch the buy stop stays live
    max_attempts: int = 2
    breakeven_after_new_highs: int = 3
    exit_close_under_ma: int = 1  # exit an open trade on a close under the EMA (1 = on, 0 = off)
    top_names: int = 3
    # Earnings ⚠ on the scanner, watchlist, alerts, positions and the chart. Calendar days, today included.
    earnings_window_days: int = DEFAULT_WARNING_WINDOW_DAYS
    # 1 = move that day's alerts into history after the 16:05 ET close. 0 = leave them on the live table.
    auto_archive: int = 1

    @classmethod
    def from_mapping(cls, raw: Optional[Mapping[str, Any]]) -> "Settings":
        s = cls()
        for f in fields(cls):
            if raw and f.name in raw and raw[f.name] is not None:
                value = raw[f.name]
                setattr(s, f.name, int(value) if f.type in ("int", int) else float(value))
        return s

    def to_dict(self) -> dict:
        return asdict(self)

    def periods(self) -> list[int]:
        return [p for p in MA_PERIODS if getattr(self, f"ma_{p}", 0)]


SETTING_LIMITS: dict[str, tuple[float, float]] = {
    "max_symbols": (1, 1000),
    "shorts": (0, 1), "max_short_symbols": (0, 1000),
    "ma_120": (0, 1), "ma_240": (0, 1), "ma_480": (0, 1),
    "touch_tol_pct": (0, 5), "hold_pct": (0, 5), "rising_bars": (1, TAIL_KEEP - 1), "watch_bars": (1, 26),
    "max_attempts": (1, 20), "breakeven_after_new_highs": (1, 50), "exit_close_under_ma": (0, 1),
    "top_names": (0, 50), "earnings_window_days": (0, 30), "auto_archive": (0, 1),
}


@dataclass
class Context:
    """Per symbol, per day inputs that are not today's bars."""

    # Per period: the EMA after each of the prior session's last few regular bars, oldest first.
    ma_tail: Mapping[int, Sequence[float]] = field(default_factory=dict)
    prev_close: Optional[float] = None  # last regular-session close before today
    session_bars: int = SESSION_BARS  # bars in a full session (fewer on a half day)


def context_from_closes(closes: Sequence[float], session_bars: int = SESSION_BARS) -> Context:
    """Context from prior sessions' regular 15-minute closes (oldest first). Periods without enough closes stay unknown."""
    tails = {}
    for p in MA_PERIODS:
        series = [v for v in ema_series(closes, p) if v is not None]
        if series:
            tails[p] = series[-TAIL_KEEP:]
    return Context(ma_tail=tails, prev_close=float(closes[-1]) if closes else None, session_bars=session_bars)


@dataclass
class Alert:
    symbol: str
    session: str
    setup: str  # the EMA period, "120" / "240" / "480"; short side "s120" / "s240" / "s480"
    origin_bar: datetime  # the touch bar (the key)
    setup_bar: datetime  # the candle whose high + $0.01 is the buy stop (moves while waiting)
    setup_index: int
    trigger: float
    stop: float
    setup_low: float  # pullback low so far
    setup_high: float  # high of ``setup_bar``
    ref_price: float  # touch bar close
    status: str = "pending"
    filled: bool = False
    fill_price: Optional[float] = None
    fill_at: Optional[datetime] = None
    high_reached: Optional[float] = None
    stop_hit: bool = False
    breakeven_at: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_at: Optional[datetime] = None
    exit_reason: Optional[str] = None
    r_multiple: Optional[float] = None
    details: dict = field(default_factory=dict)
    # Tracking state.
    bars_waited: int = 0
    current_stop: float = 0.0
    running_high: float = 0.0
    new_highs: int = 0

    @property
    def key(self) -> str:
        return f"{self.symbol}|{self.session}|{self.setup}|{_iso(self.origin_bar)}"

    @property
    def period(self) -> int:
        return setup_period(self.setup)

    @property
    def side(self) -> str:
        return setup_side(self.setup)

    @property
    def short(self) -> bool:
        return self.side == "short"

    @property
    def fired_at(self) -> datetime:
        return self.origin_bar + BAR

    @property
    def stop_pct(self) -> float:
        return abs(self.trigger - self.stop) / self.trigger * 100 if self.trigger else 0.0

    @property
    def risk(self) -> float:
        return abs(self.trigger - self.stop)

    def record(self) -> dict:
        """Row for the alerts table (outcome and levels; bookkeeping columns are added by the store)."""
        return {
            "key": self.key,
            "symbol": self.symbol,
            "session": self.session,
            "setup": self.setup,
            "setup_bar": _iso(self.setup_bar),
            "fired_at": _iso(self.fired_at),
            "trigger_price": round(self.trigger, 4),
            "stop_price": round(self.stop, 4),
            "setup_low": round(self.setup_low, 4),
            "setup_high": round(self.setup_high, 4),
            "ref_price": round(self.ref_price, 4),
            "status": self.status,
            "filled": int(self.filled),
            "fill_price": _r(self.fill_price),
            "fill_at": _iso(self.fill_at),
            "high_reached": _r(self.high_reached),
            "stop_hit": int(self.stop_hit),
            "breakeven_at": _iso(self.breakeven_at),
            "exit_price": _r(self.exit_price),
            "exit_at": _iso(self.exit_at),
            "exit_reason": self.exit_reason,
            "r_multiple": None if self.r_multiple is None else round(self.r_multiple, 3),
            "details": json.dumps(self.details, sort_keys=True),
        }


def _r(v: Optional[float]) -> Optional[float]:
    return None if v is None else round(v, 4)


def _iso(ts: Optional[datetime]) -> Optional[str]:
    if ts is None:
        return None
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------------------------- indicators


def ema_series(values: Sequence[float], period: int) -> list[Optional[float]]:
    """Same definition as the 15-minute chart: seeded with the SMA of the first ``period``."""
    out: list[Optional[float]] = [None] * len(values)
    if period <= 0 or len(values) < period:
        return out
    k = 2.0 / (period + 1)
    value = sum(values[:period]) / period
    out[period - 1] = value
    for i in range(period, len(values)):
        value += k * (values[i] - value)
        out[i] = value
    return out


def ema_seed(closes: Sequence[float], period: int = EMA_LONG) -> Optional[float]:
    """Last value of the SMA-seeded EMA over ``closes`` (None with fewer than ``period`` closes)."""
    if period <= 0 or len(closes) < period:
        return None
    k = 2.0 / (period + 1)
    value = sum(closes[:period]) / period
    for c in closes[period:]:
        value += k * (c - value)
    return value


def ema_continue(seed: Optional[float], values: Sequence[float], period: int) -> list[Optional[float]]:
    """EMA after each value, continuing from ``seed`` (all None without a seed)."""
    if seed is None:
        return [None] * len(values)
    k = 2.0 / (period + 1)
    out, value = [], seed
    for v in values:
        value += k * (v - value)
        out.append(value)
    return out


class Frame:
    """Today's bars with the EMAs every rule reads. Negative indexes reach into the prior session."""

    def __init__(self, bars: Sequence[Mapping], ctx: Context):
        self.bars = list(bars)
        self.ctx = ctx
        closes = [float(b["c"]) for b in self.bars]
        self.tail = {p: list(ctx.ma_tail.get(p) or ()) for p in MA_PERIODS}
        self.ma = {p: ema_continue(self.tail[p][-1] if self.tail[p] else None, closes, p) for p in MA_PERIODS}

    def ma_at(self, p: int, i: int) -> Optional[float]:
        if i >= 0:
            return self.ma[p][i] if i < len(self.bars) else None
        tail = self.tail[p]
        return tail[i] if -i <= len(tail) else None

    def close_at(self, i: int) -> Optional[float]:
        if i >= 0:
            return float(self.bars[i]["c"])
        return self.ctx.prev_close if i == -1 else None


def match(f: Frame, i: int, p: int, s: Settings) -> Optional[dict]:
    """Bar ``i`` pulls back to the rising ``p`` EMA from above and holds it. Returns the levels, or None."""
    m, mp, mb = f.ma_at(p, i), f.ma_at(p, i - 1), f.ma_at(p, i - 1 - s.rising_bars)
    pc = f.close_at(i - 1)
    if m is None or mp is None or mb is None or pc is None or m <= 0:
        return None
    if not mp > mb:
        return None  # not rising
    tol = s.touch_tol_pct / 100
    if pc <= mp * (1 + tol):
        return None  # the bar before was not above the line: not a pullback to it
    b = f.bars[i]
    if float(b["l"]) > m * (1 + tol):
        return None  # did not reach it
    if float(b["c"]) < m * (1 - s.hold_pct / 100):
        return None  # closed through it
    return {"ma": m, "slope_pct": (mp - mb) / mb * 100}


def match_short(f: Frame, i: int, p: int, s: Settings) -> Optional[dict]:
    """Bar ``i`` rallies up to the falling ``p`` EMA from below and is held under it. Returns the levels, or None."""
    m, mp, mb = f.ma_at(p, i), f.ma_at(p, i - 1), f.ma_at(p, i - 1 - s.rising_bars)
    pc = f.close_at(i - 1)
    if m is None or mp is None or mb is None or pc is None or m <= 0:
        return None
    if not mp < mb:
        return None  # not falling
    tol = s.touch_tol_pct / 100
    if pc >= mp * (1 - tol):
        return None  # the bar before was not under the line: not a rally into it
    b = f.bars[i]
    if float(b["h"]) < m * (1 - tol):
        return None  # did not reach it
    if float(b["c"]) > m * (1 + s.hold_pct / 100):
        return None  # closed through it
    return {"ma": m, "slope_pct": (mp - mb) / mb * 100}


def touch(f: Frame, i: int, s: Settings, side: str = "long") -> Optional[tuple[int, dict, list[int]]]:
    """(period, levels, every period touched) for the EMA bar ``i`` came back to and was held by.

    Long: the lowest rising EMA it pulled back to. Short: the highest falling EMA it rallied into.
    """
    if side == "short":
        hits = [(p, x) for p in s.periods() if (x := match_short(f, i, p, s))]
        if not hits:
            return None
        p, x = max(hits, key=lambda h: (h[1]["ma"], h[0]))
        return p, x, [h[0] for h in hits]
    hits = [(p, x) for p in s.periods() if (x := match(f, i, p, s))]
    if not hits:
        return None
    p, x = min(hits, key=lambda h: (h[1]["ma"], h[0]))
    return p, x, [h[0] for h in hits]


# --------------------------------------------------------------------------------------------- outcomes


def _close_trade(a: Alert, price: float, at: datetime, reason: str, status: str) -> None:
    a.exit_price = price
    a.exit_at = at
    a.exit_reason = reason
    a.status = status
    fill = a.fill_price or a.trigger
    if a.short:
        risk = a.stop - fill
        a.r_multiple = (fill - price) / risk if risk > 0 else None
    else:
        risk = fill - a.stop
        a.r_multiple = (price - fill) / risk if risk > 0 else None


def _fill(a: Alert, bar: Mapping) -> None:
    a.filled = True
    a.fill_at = bar["t"]
    a.status = "triggered"
    a.current_stop = a.stop
    # The entry is always the trigger: the previous 15-minute candle's high + $0.01 (short: low - $0.01),
    # even when the bar opens through it.
    a.fill_price = a.trigger
    if a.short:
        a.running_high = a.high_reached = float(bar["l"])  # best (lowest) price so far
    else:
        a.running_high = a.high_reached = float(bar["h"])


def _lost(bar: Mapping, ma: Optional[float], s: Settings, short: bool = False) -> bool:
    if ma is None:
        return False
    if short:
        return float(bar["c"]) > ma * (1 + s.hold_pct / 100)
    return float(bar["c"]) < ma * (1 - s.hold_pct / 100)


def _step_short(a: Alert, bar: Mapping, index: int, ma: Optional[float], s: Settings) -> None:
    """``step`` for a short alert: every comparison mirrored."""
    end = bar["t"] + BAR
    if a.status == "pending":
        a.bars_waited += 1
        if bar["l"] <= a.trigger:
            _fill(a, bar)
            if bar["h"] >= a.stop:  # stop and fill in one bar: the stop counts first
                a.stop_hit = True
                _close_trade(a, a.stop, end, "stop", "stopped")
            elif s.exit_close_under_ma and _lost(bar, ma, s, short=True):
                _close_trade(a, float(bar["c"]), end, "close_over_ma", "exited")
            return
        if _lost(bar, ma, s, short=True):
            a.status = "cancelled"
            a.exit_reason = "close_over_ma"
            a.exit_at = end
            return
        if a.bars_waited >= s.watch_bars:
            a.status = "expired"
            a.exit_at = end
            a.exit_reason = "not_triggered"
            return
        # Still watching: the sell stop follows the previous candle's low, the stop the rally high.
        a.setup_bar, a.setup_index = bar["t"], index
        a.setup_low = float(bar["l"])
        a.trigger = round(float(bar["l"]) - TICK, 2)
        a.setup_high = max(a.setup_high, float(bar["h"]))
        a.stop = a.current_stop = round(a.setup_high + TICK, 2)
        a.details["rearmed"] = a.details.get("rearmed", 0) + 1
        return
    if a.status != "triggered":
        return
    if bar["h"] >= a.current_stop:
        at_be = a.breakeven_at is not None and a.current_stop <= (a.fill_price or 0)
        price = max(a.current_stop, float(bar["o"]))  # a gap through the stop fills at the open
        a.stop_hit = True
        _close_trade(a, price, end, "breakeven_stop" if at_be else "stop", "breakeven" if at_be else "stopped")
        return
    a.high_reached = min(a.high_reached or bar["l"], float(bar["l"]))
    if bar["l"] < a.running_high:
        a.running_high = float(bar["l"])
        a.new_highs += 1  # new lows, for a short
        if a.breakeven_at is None and a.new_highs >= s.breakeven_after_new_highs:
            a.breakeven_at = end
            a.current_stop = min(a.current_stop, a.fill_price or a.trigger)
    if s.exit_close_under_ma and _lost(bar, ma, s, short=True):
        _close_trade(a, float(bar["c"]), end, "close_over_ma", "exited")


def step(a: Alert, bar: Mapping, index: int, ma: Optional[float], s: Settings) -> None:
    """Advance one active alert by one completed bar (the bars after its touch bar, in order)."""
    if a.short:
        _step_short(a, bar, index, ma, s)
        return
    end = bar["t"] + BAR
    if a.status == "pending":
        a.bars_waited += 1
        if bar["h"] >= a.trigger:
            _fill(a, bar)
            if bar["l"] <= a.stop:  # stop and fill in one bar: the stop counts first
                a.stop_hit = True
                _close_trade(a, a.stop, end, "stop", "stopped")
            elif s.exit_close_under_ma and _lost(bar, ma, s):
                _close_trade(a, float(bar["c"]), end, "close_under_ma", "exited")
            return
        if _lost(bar, ma, s):
            a.status = "cancelled"
            a.exit_reason = "close_under_ma"
            a.exit_at = end
            return
        if a.bars_waited >= s.watch_bars:
            a.status = "expired"
            a.exit_at = end
            a.exit_reason = "not_triggered"
            return
        # Still watching: the buy stop follows the previous candle, the stop the pullback low.
        a.setup_bar, a.setup_index = bar["t"], index
        a.setup_high = float(bar["h"])
        a.trigger = round(float(bar["h"]) + TICK, 2)
        a.setup_low = min(a.setup_low, float(bar["l"]))
        a.stop = a.current_stop = round(a.setup_low - TICK, 2)
        a.details["rearmed"] = a.details.get("rearmed", 0) + 1
        return
    if a.status != "triggered":
        return
    if bar["l"] <= a.current_stop:
        at_be = a.breakeven_at is not None and a.current_stop >= (a.fill_price or 0)
        price = min(a.current_stop, float(bar["o"]))  # a gap through the stop fills at the open
        a.stop_hit = True
        _close_trade(a, price, end, "breakeven_stop" if at_be else "stop", "breakeven" if at_be else "stopped")
        return
    a.high_reached = max(a.high_reached or bar["h"], float(bar["h"]))
    if bar["h"] > a.running_high:
        a.running_high = float(bar["h"])
        a.new_highs += 1
        if a.breakeven_at is None and a.new_highs >= s.breakeven_after_new_highs:
            a.breakeven_at = end
            a.current_stop = max(a.current_stop, a.fill_price or a.trigger)
    if s.exit_close_under_ma and _lost(bar, ma, s):
        _close_trade(a, float(bar["c"]), end, "close_under_ma", "exited")


def check_forming(a: Alert, bar: Mapping) -> None:
    """The bar still forming has traded through the buy (short: sell) stop: mark the fill now (no stop or exit checks)."""
    through = float(bar["l"]) <= a.trigger if a.short else float(bar["h"]) >= a.trigger
    if a.status == "pending" and through:
        _fill(a, bar)
        a.details["fill_on_forming_bar"] = True


def finish_session(a: Alert, last_bar: Mapping) -> None:
    """The session is over: a waiting alert expires and an open trade is closed at the last close."""
    end = last_bar["t"] + BAR
    if a.status == "pending":
        a.status = "expired"
        a.exit_at = end
        a.exit_reason = "session_end"
    elif a.status == "triggered":
        _close_trade(a, float(last_bar["c"]), end, "session_end", "exited")


# --------------------------------------------------------------------------------------------- driver


def _index_of(bars: Sequence[Mapping], ts: datetime) -> Optional[int]:
    for i, b in enumerate(bars):
        if b["t"] == ts or _iso(b["t"]) == _iso(ts):
            return i
    return None


def advance_stored(
    *,
    symbol: str,
    session: str,
    setup: str,
    origin_bar: datetime,
    setup_bar: datetime,
    trigger: float,
    stop: float,
    setup_low: float,
    setup_high: float,
    ref_price: float,
    details: Optional[dict] = None,
    bars: Sequence[Mapping],
    ctx: Context,
    settings: Optional[Settings] = None,
    forming: Optional[Mapping] = None,
) -> Optional["Alert"]:
    """Re-walk outcomes for an alert that already fired, without re-matching the touch.

    Live polls re-run ``simulate`` from scratch. When SIP later replaces IEX prices on earlier bars
    the touch can stop reproducing; ``save_session`` would then leave the stored row stuck. Call this
    for ACTIVE rows missing from the new run so fills / expiry / stops still update from the stored levels.
    """
    s = settings or Settings()
    if not bars or setup not in SETUPS:
        return None
    setup_i = _index_of(bars, setup_bar)
    origin_i = _index_of(bars, origin_bar)
    if setup_i is None:
        return None
    a = Alert(
        symbol=symbol, session=session, setup=setup, origin_bar=origin_bar, setup_bar=setup_bar,
        setup_index=setup_i, trigger=trigger, stop=stop, setup_low=setup_low, setup_high=setup_high,
        ref_price=ref_price, details=dict(details or {}), current_stop=stop,
        bars_waited=setup_i - origin_i if origin_i is not None else 0,
    )
    f = Frame(bars, ctx)
    for i in range(setup_i + 1, len(bars)):
        if a.status not in ACTIVE:
            break
        step(a, bars[i], i, f.ma[a.period][i], s)
    if a.status in ACTIVE and ctx.session_bars and len(bars) >= ctx.session_bars:
        finish_session(a, bars[-1])
    elif forming is not None:
        check_forming(a, forming)
    return a


def simulate(
    symbol: str,
    session: str,
    bars: Sequence[Mapping],
    ctx: Context,
    settings: Optional[Settings] = None,
    skipped: Optional[list] = None,
    forming: Optional[Mapping] = None,
    side: str = "long",
) -> list[Alert]:
    """Alerts for one symbol and day, oldest first, with outcomes through the last bar given.

    ``side="short"`` looks for the short mirror (rallies into a falling EMA) instead of pullbacks.

    ``bars`` are that day's completed regular-session bars in order, starting with the opening bar.
    ``forming`` is the bar still forming (live only): it can fill a waiting alert, nothing else.
    When ``skipped`` is a list, touches that were not alerted are appended to it (for replays).
    """
    s = settings or Settings()
    if not bars:
        return []
    f = Frame(bars, ctx)
    alerts: list[Alert] = []
    for i, bar in enumerate(f.bars):
        for a in alerts:
            if a.status in ACTIVE and a.setup_index < i:
                step(a, bar, i, f.ma[a.period][i], s)
        hit = touch(f, i, s, side)
        if not hit:
            continue
        period, lv, touched = hit
        setup_key = f"s{period}" if side == "short" else str(period)
        reason = None
        if i + 1 >= ctx.session_bars:
            reason = "last bar of the session"
        elif any(a.status in ACTIVE for a in alerts):
            reason = "an alert on this name is still live"
        elif sum(1 for a in alerts if a.filled) >= s.max_attempts:
            reason = "%d attempts already" % s.max_attempts
        if reason:
            if skipped is not None:
                skipped.append({"symbol": symbol, "bar": _iso(bar["t"]), "setup": setup_key, "reason": reason})
            continue
        if side == "short":
            trigger, stop = round(float(bar["l"]) - TICK, 2), round(float(bar["h"]) + TICK, 2)
        else:
            trigger, stop = round(float(bar["h"]) + TICK, 2), round(float(bar["l"]) - TICK, 2)
        alerts.append(
            Alert(
                symbol=symbol, session=session, setup=setup_key, origin_bar=bar["t"], setup_bar=bar["t"],
                setup_index=i, trigger=trigger, stop=stop, setup_low=float(bar["l"]),
                setup_high=float(bar["h"]), ref_price=float(bar["c"]), current_stop=stop,
                details={
                    "ma": round(lv["ma"], 4),
                    "ma_slope_pct": round(lv["slope_pct"], 3),
                    "touched": touched,
                    "ma_values": {str(p): (None if f.ma[p][i] is None else round(f.ma[p][i], 4)) for p in MA_PERIODS},
                },
            )
        )
    if len(f.bars) >= ctx.session_bars:
        for a in alerts:
            finish_session(a, f.bars[-1])
    elif forming is not None:
        for a in alerts:
            check_forming(a, forming)
    return alerts


def mark_top(rows: list[dict], top_names: int) -> set[str]:
    """First ``top_names`` distinct symbols of the day, by fire time (then symbol)."""
    names: list[str] = []
    for r in sorted(rows, key=lambda r: (r["fired_at"], r["symbol"])):
        if r["symbol"] not in names:
            names.append(r["symbol"])
        if len(names) >= top_names:
            break
    return set(names[:top_names])


def metrics(rows: Sequence[Mapping]) -> list[dict]:
    """Per setup: count, fill rate, win rate, average R, total R. Wins / R use closed filled trades (win: R > 0.00)."""
    out = []
    for setup in SETUPS + ("All",):
        group = [r for r in rows if setup == "All" or r["setup"] == setup]
        filled = [r for r in group if r["filled"]]
        closed = [r for r in filled if r["r_multiple"] is not None]
        wins = [r for r in closed if round(r["r_multiple"], 2) > 0]  # a 1-cent scratch is not a win
        total = sum(r["r_multiple"] for r in closed)
        out.append(
            {
                "setup": setup,
                "name": SETUP_NAMES.get(setup, "All setups"),
                "count": len(group),
                "filled": len(filled),
                "closed": len(closed),
                "open": len(filled) - len(closed),
                "fill_rate": round(len(filled) / len(group) * 100, 1) if group else None,
                "win_rate": round(len(wins) / len(closed) * 100, 1) if closed else None,
                "avg_r": round(total / len(closed), 2) if closed else None,
                "total_r": round(total, 2) if closed else None,
            }
        )
    return out
