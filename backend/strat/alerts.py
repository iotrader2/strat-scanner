"""Intraday setup alerts (A-F) on 5-minute bars, and what happened after each one.

Everything here is pure: :func:`simulate` takes one symbol's completed regular-session bars for one
day plus a little context and returns the alerts that day would have produced, each with its outcome
so far. The live poll (``alerts_live``) and the replay script call the same function, so a replay
shows exactly what the tab would have shown.

Bars are dicts ``{"t": datetime (bar start, UTC), "o", "h", "l", "c", "v"}``. ``v`` is IEX volume
(compared only to IEX averages). Bar ``i`` is the ``i``-th 5-minute bar after the open, so bar 0 is
the opening bar (6:30 Phoenix while New York is on daylight time). Setup windows are stored as minutes
after the open, which keeps them right when the clocks change.

Rules common to every setup:

* the setup bar is green, or a doji (body <= ``doji_body_pct`` of its range) closing in the top
  ``doji_close_top_pct`` of its range;
* entry is a buy stop at setup high + $0.01, good for the next ``entry_valid_bars`` bars, cancelled
  when a bar closes under the setup low;
* the stop is setup low - $0.01; a setup whose stop is more than ``max_stop_pct`` away is skipped,
  except A, which uses entry - ``max_stop_pct`` instead;
* the setup bar's IEX volume must be at least ``vol_mult`` x the average IEX volume of the same bar
  (same time of day) over the last 20 sessions (skipped when fewer than ``vol_min_sessions`` exist);
* each bar gets at most one tag, checked C, A, B, D, E, F;
* no second alert of the same setup on a name while the first is still pending or in a trade (a C
  tight run moves its pending entry to the newest tight bar instead), and no new alert at all once
  ``max_attempts`` of the name's alerts have triggered that day;
* not extended (``ext_filter``): at the setup bar the lowest low of today's last ``ext_lookback_bars``
  bars is at most ``ext_low_pct`` above the 5-minute EMA 360 (the trader's stand-in for the 1-hour
  EMA 30; at or under it is fine), and the setup bar closes at most ``ext_close_pct`` above it. The
  EMA 360 runs over regular-session closes only (no premarket), seeded from prior sessions. When there
  is not enough history for it the filter does not block.

D has two paths. Classic (variant ``pullback``): stacked 6>20>50, rising 20, reclaim of the 6 after a
touch/hold of the 20 EMA or VWAP. Hold20 (variant ``hold20``, when ``d_hold20`` is on): a green bar whose
low is within ``touch_tol_pct`` of a rising 20 EMA, closing above it, and not already more than
``d_hold20_extend_pct`` above the 20 on the prior bar. Hold20 can also require the trigger within
``d_hold20_daily_pct`` of the daily 4 EMA (``d_hold20_daily_filter``; skipped when that EMA is unknown).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional, Sequence

from .earnings import DEFAULT_WARNING_WINDOW_DAYS

TICK = 0.01
BAR = timedelta(minutes=5)
SETUPS = ("A", "B", "C", "D", "E", "F")
SETUP_NAMES = {
    "A": "Opening-bar breakout",
    "B": "Opening flush then reclaim",
    "C": "Opening-drive continuation",
    "D": "Pullback to rising 20 EMA",
    "E": "Gap-down V-reversal",
    "F": "Midday squeeze",
}
CHECK_ORDER = ("C", "A", "B", "D", "E", "F")
ACTIVE = ("pending", "triggered")
FINAL = ("stopped", "breakeven", "exited", "expired", "cancelled")


@dataclass
class Settings:
    """Adjustable rule values. Percentages are in percent (0.5 means 0.5%)."""

    # Approved defaults.
    doji_body_pct: float = 10.0
    doji_close_top_pct: float = 45.0
    bunched_pct: float = 0.5
    strong_close_top_pct: float = 30.0
    tight_range_pct: float = 50.0
    gap_down_pct: float = 1.0  # E: open this far under the prior close, or the low this far under the 20 and 50
    f_bunched_minutes: int = 120
    f_volume_mult: float = 1.5
    # Strong marubozu breakout: allow a slightly lower IEX volume floor (IEX is thin vs SIP).
    f_soft_body_pct: float = 80.0  # body at least this % of range to use the soft volume floor
    f_soft_volume_mult: float = 1.2  # soft volume floor; 0 disables the exception
    top_names: int = 3
    # From the spec.
    vol_mult: float = 0.8
    max_stop_pct: float = 2.0
    entry_valid_bars: int = 3
    max_attempts: int = 2
    breakeven_after_new_highs: int = 3
    # Working definitions for the looser words in the spec (all adjustable).
    vol_min_sessions: int = 5
    touch_tol_pct: float = 0.1
    d_lookback_bars: int = 6
    f_full_body_pct: float = 50.0
    # Not extended: price near the 5-minute EMA 360 (about the 1-hour EMA 30). 1 = on, 0 = off.
    ext_filter: int = 1
    ext_low_pct: float = 1.0  # last hour's low at most this far over the EMA 360
    ext_close_pct: float = 3.0  # setup bar close at most this far over the EMA 360
    ext_lookback_bars: int = 12  # "last hour" in 5-minute bars (today's bars only)
    # Windows, minutes after the open (setup bar start). 5-25 = 6:35-6:55 Phoenix in daylight time.
    b_from: int = 5
    b_to: int = 25
    c_from: int = 5
    c_to: int = 25
    d_from: int = 25
    d_to: int = 90
    # D hold20 path (additive to classic pullback). 1 = on, 0 = off.
    d_hold20: int = 1
    d_hold20_extend_pct: float = 0.5  # skip hold20 when the prior bar was already this far over the 20
    d_hold20_daily_filter: int = 1  # hold20 only near the daily 4 EMA (1 = on, 0 = off)
    d_hold20_daily_pct: float = 2.0  # trigger at most this far from the daily 4 EMA (%)
    e_from: int = 10
    e_to: int = 80
    f_from: int = 120
    f_to: int = 385
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


SETTING_LIMITS: dict[str, tuple[float, float]] = {
    "doji_body_pct": (0, 50), "doji_close_top_pct": (0, 100), "bunched_pct": (0.01, 5),
    "strong_close_top_pct": (1, 100), "tight_range_pct": (1, 100), "gap_down_pct": (0.1, 20),
    "f_bunched_minutes": (15, 360), "f_volume_mult": (0.1, 20), "f_soft_body_pct": (0, 100), "f_soft_volume_mult": (0, 20), "top_names": (0, 50),
    "vol_mult": (0, 20), "max_stop_pct": (0.1, 20), "entry_valid_bars": (1, 20), "max_attempts": (1, 20),
    "breakeven_after_new_highs": (1, 50), "vol_min_sessions": (1, 20), "touch_tol_pct": (0, 5),
    "d_lookback_bars": (1, 30), "f_full_body_pct": (0, 100),
    "d_hold20": (0, 1), "d_hold20_extend_pct": (0, 5), "d_hold20_daily_filter": (0, 1),
    "d_hold20_daily_pct": (0, 20),
    "ext_filter": (0, 1), "ext_low_pct": (0, 50), "ext_close_pct": (0, 50), "ext_lookback_bars": (1, 78),
    "b_from": (0, 390), "b_to": (0, 390), "c_from": (0, 390), "c_to": (0, 390), "d_from": (0, 390),
    "d_to": (0, 390), "e_from": (0, 390), "e_to": (0, 390), "f_from": (0, 390), "f_to": (0, 390),
    "earnings_window_days": (0, 30),
    "auto_archive": (0, 1),
}


@dataclass
class Context:
    """Per symbol, per day inputs that are not today's bars."""

    warm_closes: Sequence[float] = ()  # prior sessions' regular 5-minute closes, oldest first (EMA seed)
    prev_close: Optional[float] = None
    premarket_low: Optional[float] = None
    vol_avg: Mapping[int, float] = field(default_factory=dict)  # bar index -> average IEX volume
    vol_sessions: int = 0  # sessions behind vol_avg
    session_bars: int = 78  # bars in a full session (fewer on a half day)
    ema360_seed: Optional[float] = None  # 5-minute EMA 360 after the prior session's last regular bar
    daily_4_ema: Optional[float] = None  # daily EMA 4 as of the prior session close (hold20 quality gate)


@dataclass
class Alert:
    symbol: str
    session: str
    setup: str
    origin_bar: datetime  # first setup bar (the key; a C tight run can move the setup bar later)
    setup_bar: datetime
    setup_index: int
    trigger: float
    stop: float
    setup_low: float
    setup_high: float
    ref_price: float  # setup bar close, the price "stop %" is measured against
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
    def fired_at(self) -> datetime:
        return self.setup_bar + BAR

    @property
    def stop_pct(self) -> float:
        return (self.trigger - self.stop) / self.trigger * 100 if self.trigger else 0.0

    @property
    def risk(self) -> float:
        return self.trigger - self.stop

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
    """Same definition as the 5-minute chart (watch5m): seeded with the SMA of the first ``period``."""
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


EMA_LONG = 360  # 5-minute bars: 360 x 5 min = 30 hours = 30 one-hour bars of the regular session (6.5 h/day)


def ema_seed(closes: Sequence[float], period: int = EMA_LONG) -> Optional[float]:
    """Last value of the SMA-seeded EMA over ``closes`` (None with fewer than ``period`` closes)."""
    if period <= 0 or len(closes) < period:
        return None
    k = 2.0 / (period + 1)
    value = sum(closes[:period]) / period
    for c in closes[period:]:
        value += k * (c - value)
    return value


def ema_continue(seed: Optional[float], values: Sequence[float], period: int = EMA_LONG) -> list[Optional[float]]:
    """EMA after each value, continuing from ``seed`` (all None without a seed)."""
    if seed is None:
        return [None] * len(values)
    k = 2.0 / (period + 1)
    out, value = [], seed
    for v in values:
        value += k * (v - value)
        out.append(value)
    return out


def vwap_series(bars: Sequence[Mapping]) -> list[Optional[float]]:
    """Regular-session VWAP after each bar, typical price weighted by (IEX) volume."""
    out: list[Optional[float]] = []
    pv = vol = 0.0
    for b in bars:
        v = float(b.get("v") or 0)
        pv += (b["h"] + b["l"] + b["c"]) / 3 * v
        vol += v
        out.append(pv / vol if vol > 0 else None)
    return out


class Frame:
    """Today's bars with the indicators every rule reads."""

    def __init__(self, bars: Sequence[Mapping], ctx: Context):
        self.bars = list(bars)
        warm = list(ctx.warm_closes)
        closes = warm + [float(b["c"]) for b in self.bars]
        n = len(warm)
        self.e6 = ema_series(closes, 6)[n:]
        self.e20 = ema_series(closes, 20)[n:]
        self.e50 = ema_series(closes, 50)[n:]
        # The 20 EMA one bar before today's first bar (for "rising" on bar 0).
        full20 = ema_series(closes, 20)
        self.e20_before = full20[n - 1] if n >= 1 else None
        self.vwap = vwap_series(self.bars)
        self.e360 = ema_continue(ctx.ema360_seed, [float(b["c"]) for b in self.bars])
        self.ctx = ctx

    def emas(self, i: int) -> Optional[tuple[float, float, float]]:
        a, b, c = self.e6[i], self.e20[i], self.e50[i]
        if a is None or b is None or c is None:
            return None
        return a, b, c

    def e20_prev(self, i: int) -> Optional[float]:
        return self.e20[i - 1] if i > 0 else self.e20_before


def _range(b: Mapping) -> float:
    return float(b["h"]) - float(b["l"])


def _close_pos(b: Mapping) -> Optional[float]:
    """Close as a fraction of the bar's range from the low (1 = closed on the high)."""
    r = _range(b)
    return (b["c"] - b["l"]) / r if r > 0 else None


def is_green(b: Mapping) -> bool:
    return b["c"] > b["o"]


def is_doji(b: Mapping, s: Settings) -> bool:
    r = _range(b)
    return r > 0 and abs(b["c"] - b["o"]) <= r * s.doji_body_pct / 100


def setup_bar_ok(b: Mapping, s: Settings) -> bool:
    """Green, or a doji closing in the top ``doji_close_top_pct`` of its range."""
    if is_green(b):
        return True
    pos = _close_pos(b)
    return is_doji(b, s) and pos is not None and pos >= 1 - s.doji_close_top_pct / 100


def strong_bar(b: Mapping, s: Settings) -> bool:
    pos = _close_pos(b)
    return is_green(b) and pos is not None and pos >= 1 - s.strong_close_top_pct / 100


def bunched(levels: Sequence[float], s: Settings) -> bool:
    lo, hi = min(levels), max(levels)
    return lo > 0 and (hi - lo) / lo * 100 <= s.bunched_pct


def _in(i: int, lo: int, hi: int) -> bool:
    return lo <= i * 5 <= hi


# --------------------------------------------------------------------------------------------- setups


def _c_tight_run(f: Frame, i: int, s: Settings) -> bool:
    """Bars 1..i are all tight (range <= tight_range_pct of bar 0) and each closes over the 6 EMA or VWAP."""
    r0 = _range(f.bars[0])
    if i < 1 or i > 5 or r0 <= 0:
        return False
    for k in range(1, i + 1):
        b = f.bars[k]
        if _range(b) > r0 * s.tight_range_pct / 100:
            return False
        e6, vw = f.e6[k], f.vwap[k]
        if not ((e6 is not None and b["c"] > e6) or (vw is not None and b["c"] > vw)):
            return False
    return True


def match_c(f: Frame, i: int, s: Settings) -> Optional[str]:
    if not _in(i, s.c_from, s.c_to) or not strong_bar(f.bars[0], s):
        return None
    if i == 1 and f.bars[1]["c"] > f.bars[0]["h"]:
        return "drive"
    if _c_tight_run(f, i, s):
        return "tight"
    return None


def match_a(f: Frame, i: int, s: Settings) -> Optional[str]:
    if i != 0:
        return None
    b = f.bars[0]
    e6, e20 = f.e6[0], f.e20[0]
    if e6 is None or e20 is None or not strong_bar(b, s):
        return None
    return "open" if b["c"] > e6 and b["c"] > e20 else None


def _b_dipped(f: Frame, i: int) -> bool:
    open0 = f.bars[0]["o"]
    lows = [f.bars[k]["l"] for k in range(i + 1)]
    if f.ctx.premarket_low is not None:
        lows.append(f.ctx.premarket_low)
    low = min(lows)
    return low < open0 or (f.ctx.prev_close is not None and low < f.ctx.prev_close)


def _b_ok(f: Frame, i: int, s: Settings) -> bool:
    b = f.bars[i]
    em = f.emas(i)
    if em is None or not is_green(b) or not b["c"] > max(em) or not bunched(em, s):
        return False
    prev = f.emas(i - 1) if i > 0 else None
    # A reclaim: the bar before had not already closed over all three.
    return prev is None or not f.bars[i - 1]["c"] > max(prev)


def match_b(f: Frame, i: int, s: Settings) -> Optional[str]:
    if not _in(i, s.b_from, s.b_to) or not _b_dipped(f, i) or not _b_ok(f, i, s):
        return None
    # Only the first qualifying bar of the window.
    for k in range(i):
        if _in(k, s.b_from, s.b_to) and _b_dipped(f, k) and _b_ok(f, k, s):
            return None
    return "reclaim"


def match_d_classic(f: Frame, i: int, s: Settings) -> Optional[str]:
    """Stacked 6>20>50, rising 20, reclaim of the 6 after a touch/hold of the 20 EMA or VWAP."""
    if not _in(i, s.d_from, s.d_to) or i < 1:
        return None
    # The trend is judged on the bar before the setup bar, so the setup bar cannot create it alone:
    # 6 > 20 > 50 there and the 20 rising into it, and still stacked on the setup bar.
    em, prev_em, e20pp = f.emas(i), f.emas(i - 1), f.e20_prev(i - 1)
    if em is None or prev_em is None or e20pp is None:
        return None
    e6, e20, e50 = em
    if not (e6 > e20 > e50 and prev_em[0] > prev_em[1] > prev_em[2] and prev_em[1] > e20pp):
        return None
    b, prev = f.bars[i], f.bars[i - 1]
    if f.e6[i - 1] is None or not (prev["c"] <= f.e6[i - 1] and is_green(b) and b["c"] > e6):
        return None
    tol = s.touch_tol_pct / 100
    start = max(0, i - s.d_lookback_bars)
    touch = None
    for k in range(i - 1, start - 1, -1):
        lvl = [x for x in (f.e20[k], f.vwap[k]) if x is not None]
        if lvl and any(f.bars[k]["l"] <= x * (1 + tol) for x in lvl):
            touch = k
            break
    if touch is None:
        return None
    for k in range(touch, i):
        lvl = [x for x in (f.e20[k], f.vwap[k]) if x is not None]
        if not lvl or f.bars[k]["c"] < min(lvl) * (1 - tol):
            return None  # it did not hold
    return "pullback"


def match_d_hold20(f: Frame, i: int, s: Settings) -> Optional[str]:
    """Green hold of a rising 20 EMA (no stack / reclaim-6 required).

    Low within ``touch_tol_pct`` of the 20, close above it, and the prior bar not already more than
    ``d_hold20_extend_pct`` above the 20. Optional daily-4-EMA proximity gate uses the trigger.
    """
    if not s.d_hold20 or not _in(i, s.d_from, s.d_to) or i < 1:
        return None
    em, prev_em, e20pp = f.emas(i), f.emas(i - 1), f.e20_prev(i - 1)
    if em is None or e20pp is None or f.e20[i] is None:
        return None
    _e6, e20, _e50 = em
    if not (prev_em and prev_em[1] > e20pp):
        return None  # 20 must be rising into the setup bar
    b = f.bars[i]
    if not (is_green(b) and b["c"] > e20):
        return None
    tol = s.touch_tol_pct / 100
    if b["l"] > e20 * (1 + tol):
        return None  # this bar itself must touch the 20
    start = max(0, i - s.d_lookback_bars)
    if not any(
        f.e20[k] is not None and f.bars[k]["l"] <= f.e20[k] * (1 + tol)
        for k in range(i, start - 1, -1)
    ):
        return None
    prev, pe = f.bars[i - 1], f.e20[i - 1]
    if pe and prev["c"] > pe * (1 + s.d_hold20_extend_pct / 100) and prev["l"] > pe * (1 + tol):
        return None  # already extended above the 20 on the prior bar
    if s.d_hold20_daily_filter and f.ctx.daily_4_ema is not None and f.ctx.daily_4_ema > 0:
        trigger = round(float(b["h"]) + TICK, 2)
        dist = abs(trigger - f.ctx.daily_4_ema) / f.ctx.daily_4_ema * 100
        if dist > s.d_hold20_daily_pct:
            return None
    return "hold20"


def match_d(f: Frame, i: int, s: Settings) -> Optional[str]:
    """Classic pullback first; else hold20 when enabled."""
    return match_d_classic(f, i, s) or match_d_hold20(f, i, s)


def _e_pivot(f: Frame, i: int) -> Optional[int]:
    """Index of a higher low after the session low (before bar ``i``), or None."""
    if i < 3:
        return None
    lows = [f.bars[k]["l"] for k in range(i)]
    m = min(range(i), key=lambda k: (lows[k], k))
    for j in range(m + 1, i):
        nxt = f.bars[j + 1]["l"] if j + 1 <= i else None
        if lows[j] > lows[m] and lows[j] <= lows[j - 1] and nxt is not None and lows[j] < nxt:
            return j
    return None


def _far_below(price: float, e20: Optional[float], e50: Optional[float], pct: float) -> bool:
    """True when ``price`` is at least ``pct`` under both the 20 and the 50."""
    if e20 is None or e50 is None or e20 <= 0 or e50 <= 0:
        return False
    band = 1 - pct / 100
    return price <= e20 * band and price <= e50 * band


def match_e(f: Frame, i: int, s: Settings) -> Optional[str]:
    """Gap-down, or a washout far below the 20 and 50, then a higher low and the first close back over the 20.

    The open has to be at least ``gap_down_pct`` under the prior close, or the session low has to be at least
    that far under both the 20 and the 50. A wick under the open is not a washout. The higher low prints while
    price is still under the 20, and the setup bar is the first close back over it.
    """
    if not _in(i, s.e_from, s.e_to) or i < 1:
        return None
    open0 = f.bars[0]["o"]
    pc = f.ctx.prev_close
    gap = pc is not None and open0 <= pc * (1 - s.gap_down_pct / 100)
    lows = [f.bars[k]["l"] for k in range(i)]
    m = min(range(i), key=lambda k: (lows[k], k))
    e20_m = f.e20[m]
    # The reversal starts under the 20. The setup bar is the reclaim of it.
    if e20_m is None or not lows[m] < e20_m:
        return None
    washout = _far_below(lows[m], e20_m, f.e50[m], s.gap_down_pct)
    if not (gap or washout):
        return None
    j = _e_pivot(f, i)
    b, e20 = f.bars[i], f.e20[i]
    if j is None or e20 is None or f.e20[j] is None or not (is_green(b) and b["c"] > e20):
        return None
    if lows[j] >= f.e20[j] or b["l"] <= lows[m]:
        return None  # higher low is already back over the 20, or this bar undercuts the low
    for k in range(m, i):
        if f.e20[k] is not None and f.bars[k]["c"] > f.e20[k]:
            return None  # not the first close back over the 20 since the low
    return "gap" if gap else "washout"


def match_f(f: Frame, i: int, s: Settings) -> Optional[str]:
    if not _in(i, s.f_from, s.f_to):
        return None
    n = max(1, s.f_bunched_minutes // 5)
    if i < n:
        return None
    window = range(i - n, i)
    for k in window:
        em = f.emas(k)
        if em is None or not bunched(em, s):
            return None
    first, last = f.e20[i - n], f.e20[i - 1]
    if first is None or last is None or abs(last - first) / first * 100 > s.bunched_pct:
        return None  # not flat
    b, em = f.bars[i], f.emas(i)
    r = _range(b)
    if em is None or r <= 0 or not is_green(b) or (b["c"] - b["o"]) < r * s.f_full_body_pct / 100:
        return None
    if not (b["c"] > max(f.bars[k]["h"] for k in window) and b["c"] > max(em)):
        return None
    avg = f.ctx.vol_avg.get(i)
    if not avg or f.ctx.vol_sessions < s.vol_min_sessions:
        return None
    v = float(b.get("v") or 0)
    if v >= s.f_volume_mult * avg:
        return "squeeze"
    # IEX volume is often thin on the first breakout bar; a near-marubozu at a slightly
    # lower multiple is still the squeeze resolution (see PLTR 2026-10-27 08:40 Phx).
    body_pct = (b["c"] - b["o"]) / r * 100
    if s.f_soft_volume_mult > 0 and body_pct >= s.f_soft_body_pct and v >= s.f_soft_volume_mult * avg:
        return "squeeze"
    return None


MATCHERS = {"A": match_a, "B": match_b, "C": match_c, "D": match_d, "E": match_e, "F": match_f}


def tag_bar(f: Frame, i: int, s: Settings) -> Optional[tuple[str, str]]:
    for setup in CHECK_ORDER:
        variant = MATCHERS[setup](f, i, s)
        if variant:
            return setup, variant
    return None


def volume_check(f: Frame, i: int, s: Settings) -> tuple[bool, Optional[float]]:
    avg = f.ctx.vol_avg.get(i)
    if not avg or f.ctx.vol_sessions < s.vol_min_sessions:
        return True, None
    ratio = float(f.bars[i].get("v") or 0) / avg
    return ratio >= s.vol_mult, ratio


def extension(f: Frame, i: int, s: Settings) -> Optional[dict]:
    """Distance of the last hour's low and the setup bar's close from the 5-minute EMA 360, in percent."""
    e = f.e360[i]
    if e is None or e <= 0:
        return None
    lo = min(float(f.bars[k]["l"]) for k in range(max(0, i - max(1, s.ext_lookback_bars) + 1), i + 1))
    return {"ema360": e, "low_pct": (lo - e) / e * 100, "close_pct": (float(f.bars[i]["c"]) - e) / e * 100}


def not_extended(f: Frame, i: int, s: Settings) -> tuple[bool, Optional[dict]]:
    """(passes, distances). Passes when the filter is off or the EMA 360 is not known yet."""
    x = extension(f, i, s)
    if not s.ext_filter or x is None:
        return True, x
    return x["low_pct"] <= s.ext_low_pct and x["close_pct"] <= s.ext_close_pct, x


def levels(f: Frame, i: int, setup: str, s: Settings) -> tuple[float, float, bool]:
    """(trigger, stop, too_wide). A wide A bar gets a 2% stop instead of being skipped."""
    b = f.bars[i]
    trigger = round(b["h"] + TICK, 2)
    stop = round(b["l"] - TICK, 2)
    pct = (trigger - stop) / trigger * 100
    if pct > s.max_stop_pct:
        if setup == "A":
            return trigger, round(trigger * (1 - s.max_stop_pct / 100), 2), False
        return trigger, stop, True
    return trigger, stop, False


# --------------------------------------------------------------------------------------------- outcomes


def _close_trade(a: Alert, price: float, at: datetime, reason: str, status: str) -> None:
    a.exit_price = price
    a.exit_at = at
    a.exit_reason = reason
    a.status = status
    risk = (a.fill_price or a.trigger) - a.stop
    a.r_multiple = (price - (a.fill_price or a.trigger)) / risk if risk > 0 else None


def step(a: Alert, bar: Mapping, e20: Optional[float], s: Settings) -> None:
    """Advance one active alert by one completed bar (the bars after its setup bar, in order)."""
    end = bar["t"] + BAR
    if a.status == "pending":
        a.bars_waited += 1
        if bar["h"] >= a.trigger:
            a.filled = True
            a.fill_price = max(a.trigger, float(bar["o"]))
            a.fill_at = bar["t"]
            a.status = "triggered"
            a.current_stop = a.stop
            a.running_high = float(bar["h"])
            a.high_reached = float(bar["h"])
            if bar["l"] <= a.stop:  # stop and fill in one bar: the stop counts first
                a.stop_hit = True
                _close_trade(a, a.stop, end, "stop", "stopped")
                return
            if e20 is not None and bar["c"] < e20:
                _close_trade(a, float(bar["c"]), end, "close_under_20ema", "exited")
            return
        if bar["c"] < a.setup_low:
            a.status = "cancelled"
            a.exit_reason = "close_under_setup_low"
            a.exit_at = end
            return
        if a.bars_waited >= s.entry_valid_bars:
            a.status = "expired"
            a.exit_at = end
            a.exit_reason = "not_triggered"
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
    if e20 is not None and bar["c"] < e20:
        _close_trade(a, float(bar["c"]), end, "close_under_20ema", "exited")


def finish_session(a: Alert, last_bar: Mapping) -> None:
    """The session is over: a pending entry expires and an open trade is closed at the last close."""
    end = last_bar["t"] + BAR
    if a.status == "pending":
        a.status = "expired"
        a.exit_at = end
        a.exit_reason = "session_end"
    elif a.status == "triggered":
        _close_trade(a, float(last_bar["c"]), end, "session_end", "exited")


# --------------------------------------------------------------------------------------------- driver


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
) -> Optional["Alert"]:
    """Re-walk outcomes for an alert that already fired, without re-matching the setup.

    Live polls re-run ``simulate`` from scratch. When SIP later replaces IEX prices on bars
    before the setup, ``match_*`` can stop reproducing the alert; ``save_session`` would then
    leave the stored row stuck (e.g. forever ``pending``). Call this for ACTIVE rows missing
    from the new simulate run so fills / expiry / stops still update from the frozen levels.
    """
    s = settings or Settings()
    if not bars:
        return None
    setup_i = None
    for i, b in enumerate(bars):
        if b["t"] == setup_bar or _iso(b["t"]) == _iso(setup_bar):
            setup_i = i
            break
    if setup_i is None:
        return None
    a = Alert(
        symbol=symbol,
        session=session,
        setup=setup,
        origin_bar=origin_bar,
        setup_bar=setup_bar,
        setup_index=setup_i,
        trigger=trigger,
        stop=stop,
        setup_low=setup_low,
        setup_high=setup_high,
        ref_price=ref_price,
        details=dict(details or {}),
    )
    f = Frame(bars, ctx)
    for i in range(setup_i + 1, len(bars)):
        if a.status not in ACTIVE:
            break
        step(a, bars[i], f.e20[i], s)
    if a.status in ACTIVE and ctx.session_bars and len(bars) >= ctx.session_bars:
        finish_session(a, bars[-1])
    return a


def simulate(
    symbol: str,
    session: str,
    bars: Sequence[Mapping],
    ctx: Context,
    settings: Optional[Settings] = None,
    skipped: Optional[list] = None,
) -> list[Alert]:
    """Alerts for one symbol and day, oldest first, with outcomes through the last bar given.

    ``bars`` are that day's completed regular-session bars in order, starting with the opening bar.
    When ``skipped`` is a list, tagged bars that a filter rejected are appended to it (for replays).
    """
    s = settings or Settings()
    if not bars:
        return []
    f = Frame(bars, ctx)
    alerts: list[Alert] = []
    for i, bar in enumerate(f.bars):
        for a in alerts:
            if a.status in ACTIVE and a.setup_index < i:
                if a.status == "pending" and sum(1 for x in alerts if x.filled) >= s.max_attempts:
                    a.status, a.exit_at, a.exit_reason = "expired", bar["t"], "max_attempts"
                    continue
                step(a, bar, f.e20[i], s)
        tag = tag_bar(f, i, s)
        if not tag:
            continue
        same = [a for a in alerts if a.status in ACTIVE and a.setup == tag[0]]
        if same:
            # Same setup already live on this name: no duplicate. A C tight run that keeps going moves its
            # pending entry to the newest tight bar instead.
            a = same[-1]
            if (
                tag[1] == "tight" and a.status == "pending" and a.details.get("variant") == "tight"
                and setup_bar_ok(bar, s) and volume_check(f, i, s)[0] and not_extended(f, i, s)[0]
            ):
                trigger, stop, wide = levels(f, i, "C", s)
                if not wide:
                    a.setup_bar, a.setup_index = bar["t"], i
                    a.trigger, a.stop, a.current_stop = trigger, stop, stop
                    a.setup_low, a.setup_high, a.ref_price = float(bar["l"]), float(bar["h"]), float(bar["c"])
                    a.bars_waited = 0
                    a.details["rearmed"] = a.details.get("rearmed", 0) + 1
            continue
        if sum(1 for a in alerts if a.filled) >= s.max_attempts:
            continue
        setup, variant = tag
        reason = None
        ok_vol, ratio = volume_check(f, i, s)
        ok_ext, ext = not_extended(f, i, s)
        if not setup_bar_ok(bar, s):
            reason = "setup bar not green / doji"
        elif not ok_vol:
            reason = "volume under %.1fx" % s.vol_mult
        elif not ok_ext:
            reason = "extended: hour low %+.2f%%, close %+.2f%% vs 5m EMA 360 (max %.1f%% / %.1f%%)" % (
                ext["low_pct"], ext["close_pct"], s.ext_low_pct, s.ext_close_pct)
        trigger, stop, wide = levels(f, i, setup, s)
        if reason is None and wide:
            reason = "stop over %.1f%%" % s.max_stop_pct
        if reason:
            if skipped is not None:
                skipped.append({"symbol": symbol, "bar": _iso(bar["t"]), "setup": setup, "reason": reason})
            continue
        em = f.emas(i)
        alerts.append(
            Alert(
                symbol=symbol, session=session, setup=setup, origin_bar=bar["t"], setup_bar=bar["t"], setup_index=i,
                trigger=trigger, stop=stop, setup_low=float(bar["l"]), setup_high=float(bar["h"]),
                ref_price=float(bar["c"]), current_stop=stop,
                details={
                    "variant": variant,
                    "volume_ratio": None if ratio is None else round(ratio, 2),
                    "ema6": None if f.e6[i] is None else round(f.e6[i], 4),
                    "ema20": None if f.e20[i] is None else round(f.e20[i], 4),
                    "ema50": None if em is None else round(em[2], 4),
                    "vwap": None if f.vwap[i] is None else round(f.vwap[i], 4),
                    "a_stop_capped": setup == "A" and round(bar["l"] - TICK, 2) != stop,
                    "ema360": None if ext is None else round(ext["ema360"], 4),
                    "ema360_close_pct": None if ext is None else round(ext["close_pct"], 2),
                    "ema360_low_pct": None if ext is None else round(ext["low_pct"], 2),
                },
            )
        )
    if len(f.bars) >= ctx.session_bars:
        for a in alerts:
            finish_session(a, f.bars[-1])
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
