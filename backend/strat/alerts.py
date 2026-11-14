"""Intraday entries for daily setups on 15-minute bars.

Default (``entry_trigger=1``): a completed 15-minute bar that closes **above** the configurable
cross EMA (default 6) after the prior bar closed at or below it. The cross candle must also be
green (close > open) with body at least ``cross_min_body_pct`` percent of its range (default 50;
0 disables; a zero-range candle fails), and close above the 15-minute ``cross_above_ema`` EMA
(default 20; 0 disables). Buy = that candle's high + $0.01;
stop = that candle's low - $0.01; a stop closer than ``min_stop_pct`` (default 0.5%) or wider than
``max_stop_pct`` is not armed. The order does not re-arm. While pending it fills at the buy or
cancels if price trades the candle low - $0.01; the trade cutoff (``trade_window_minutes`` after the
open, default 10:45 ET) and session end still apply (no ``watch_bars`` expiry). After the fill, once ``trail_stop_bars`` (3) 15-minute bars have completed after
the trigger candle, the stop moves up to the lowest low of those bars - $0.01 (``trail_stop_bars=0``: the
old break-even after ``breakeven_after_bars``). Each stop move is recorded in ``details["stops"]`` so the
local order app can replace its stop order.

The position is sold in thirds on a daily-chart check one minute before the close (15:59 ET,
``Context.close_mark``): the first third at the entry day's check, the next when that price is under the
daily ``trim_daily_ema_1`` (6) EMA, the last when it is under the daily ``trim_daily_ema_2`` (20) EMA.
The daily EMAs count the 15:59 price as today's close. Each step fires once and in order; one check can
take several thirds. The position is held overnight (no session-end exit) until the ladder or the stop
closes it: :func:`carry_alert` / :func:`advance_carried` walk it on later sessions. Partial exits use
weighted R. Same cross rules apply to inverse-ETF longs.

Legacy (``entry_trigger=0``): pullback to a rising 120 / 240 / 480 EMA with re-arm and ``stop_mode``.

The setup decision is daily: ``alert_symbols`` / ``alert_short_symbols`` pick names. Short exposure
is taken by longing a mapped single-stock inverse ETF when the underlying has EMA Crossback Short
(see ``inverse_etfs``); the old direct-short ``s120`` / ``s240`` / ``s480`` path is not used for new
alerts. Direct-short simulate remains for tests and historical rows.

Everything here is pure: :func:`simulate` takes one symbol's completed regular-session bars for one
day plus context and returns alerts with outcomes. The live poll and replay call the same function.

Bars are dicts ``{"t": datetime (bar start, UTC), "o", "h", "l", "c", "v"}``. EMAs are of
regular-session 15-minute closes, seeded from prior sessions (``Context.ma_tail``).
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass, field, fields
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Mapping, Optional, Sequence
from zoneinfo import ZoneInfo

from .earnings import DEFAULT_WARNING_WINDOW_DAYS

log = logging.getLogger(__name__)

SKIP_EXT_CAP = "ext_cap"
SKIP_MA120_SHORT = "ma120_short_disabled"

_skip_lock = threading.Lock()
_skip_session: Optional[str] = None
_skip_counts: dict[str, int] = {SKIP_EXT_CAP: 0, SKIP_MA120_SHORT: 0}

TICK = 0.01
BAR_MINUTES = 15
BAR = timedelta(minutes=BAR_MINUTES)
SESSION_BARS = 390 // BAR_MINUTES  # bars in a full regular session
# Trade window: from the 09:30 ET open for ``Settings.trade_window_minutes`` (default 75 = 10:45 ET, year-round:
# 08:45 Arizona in winter, 07:45 in summer). No new alert on a bar that ends after the cutoff and no new entry
# on a bar that starts at or after it. Open trades are still managed to their exit.
TRADE_CUTOFF_TZ = ZoneInfo("America/New_York")
SESSION_OPEN = time(9, 30)
TRADE_WINDOW_MINUTES = 75
MA_PERIODS = (120, 240, 480)
EMA_LONG = MA_PERIODS[-1]
ENTRY_MA_TOUCH = 0
ENTRY_EMA_CROSS = 1
TRIM_FRAC = 1.0 / 3.0  # each ladder step exits one third of the original position
# Daily trim ladder: checked once per session one minute before the 16:00 ET close.
CLOSE_CHECK_AT = time(15, 59)
TRIM_DAY_CLOSE = "trim_day_close"  # step 1: the entry day's 15:59 check
TRIM_DAILY_PREFIX = "trim_daily_ema_"  # steps 2 and 3: 15:59 price under the daily EMA
STOP_EXIT_REASONS = ("stop", "breakeven_stop", "trail_stop")
LONG_SETUPS = tuple(str(p) for p in MA_PERIODS)
SHORT_SETUPS = tuple(f"s{p}" for p in MA_PERIODS)
# Cross setups use the period string (e.g. "6"); keep common ones listed for live orphan checks.
CROSS_SETUPS = ("6",)
SETUPS = LONG_SETUPS + SHORT_SETUPS + CROSS_SETUPS
SETUP_NAMES = {
    **{str(p): f"Pullback to rising {p} EMA" for p in MA_PERIODS},
    **{f"s{p}": f"Short: rally to falling {p} EMA" for p in MA_PERIODS},
    "6": "15-min 6 EMA crossback",
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

    # Which names: a stock or ETF with a daily setup, highest scan score first, at most this many.
    max_symbols: int = 150
    # 1 = longs only in a top-ranked theme, shorts only in a bottom-ranked theme.
    theme_gate: int = 1
    theme_top_pct: float = 25.0  # top this percent for longs, bottom this percent for shorts
    # Short side: a stock or ETF with an allowed short daily setup, weakest RS first, at most this many.
    shorts: int = 1  # 1 = alert short setups too, 0 = longs only
    max_short_symbols: int = 75
    # 1 = allow short entries on the 15-minute 120 EMA (s120). 0 = skip every s120 short
    # (including names that qualified via overcut-fail or any other short daily setup). 240/480 shorts are unchanged.
    shorts_ma120_enabled: int = 0
    # Which averages (1 = on, 0 = off) for ``entry_trigger=0`` (MA touch). Cross mode ignores these.
    ma_120: int = 1
    ma_240: int = 0
    ma_480: int = 0
    # 1 = 15-min EMA crossback (default). 0 = pullback to rising 120/240/480 EMA.
    entry_trigger: int = ENTRY_EMA_CROSS
    cross_ema_period: int = 6  # 15-min EMA period for the crossback entry
    # Cross candle strength: green body must be at least this % of (high-low). 0 = off. Default 50.
    cross_min_body_pct: float = 50.0
    # Cross candle must also close above this 15-minute EMA (a bounce under it is against the intraday trend).
    # 0 = off. An EMA with no history yet does not block.
    cross_above_ema: int = 20
    # No new alert on a bar ending after this many minutes from the 09:30 ET open, and no entry on a bar
    # starting at or after it. 75 = 10:45 ET (150 = the old 12:00 ET).
    trade_window_minutes: int = TRADE_WINDOW_MINUTES
    # Cross mode trim ladder, checked at 15:59 ET on the daily chart (each third once, in order):
    # 1/3 at the entry day's check, 1/3 under the daily trim_daily_ema_1, the last 1/3 under trim_daily_ema_2.
    trim_daily_ema_1: int = 6
    trim_daily_ema_2: int = 20
    # Cross mode: once this many 15-minute bars have completed after the trigger candle, raise the
    # stop to their lowest low - $0.01. 0 = the old break-even after ``breakeven_after_bars``.
    trail_stop_bars: int = 3
    # Cross mode with trail_stop_bars=0: raise the stop to the fill after this many completed bars after the fill.
    breakeven_after_bars: int = 4
    # 1 = short side via longing mapped inverse ETFs when the underlying has EMA Crossback Short.
    inverse_etf_shorts: int = 1
    # Longs: skip when the buy trigger is more than this percent above the prior session's daily EMA
    # of ``long_ext_ema_period``. 0 disables the cap. The rule lives in ``long_extension_skip``.
    # Not applied to inverse-ETF (short-proxy) alerts.
    long_max_ext_vs_d10ema_pct: float = 2.0
    long_ext_ema_period: int = 10  # daily EMA period for the long extension cap (default 10)
    # 1 = do not skip when the trigger/fill is at or under the prior-day daily 4 EMA, even if over the cap.
    long_ext_waive_at_d4ema: int = 1
    # 0 = lowest low since the touch. 1 = the candle that owns the buy. 2 = fixed percent.
    # Used only for ``entry_trigger=0``. Cross mode always uses the cross candle's low - 1c.
    stop_mode: int = 2
    fixed_stop_pct: float = 1.0
    max_stop_pct: float = 1.0  # do not arm an order wider than this (default 1%; +0.05 slack in apply_order)
    # Do not arm an order whose stop is closer than this percent of the buy (inside 15-minute noise). 0 = off.
    min_stop_pct: float = 0.5
    # 1 = a long name needs a daily setup that has not broken yet.
    long_pending_only: int = 0
    # 1 = the post-close watchlist reset also removes names you added yourself. 0 = keep those.
    reset_manual: int = 0
    # 1 = also check names you added to the watchlist, long side, even with no daily setup and
    # outside the theme gate. They do not count toward max_symbols. A name that already qualifies
    # as a short stays a short. Those names are exempt from the dollar-volume and ATR slider filters,
    # but not from the hard ATR floor (MIN_ALERT_ATR_PCT).
    alert_manual_watchlist: int = 1
    # Daily-scan gates, applied before the name caps. Same scale as the scanner sliders.
    # Slider left end is $10M; default is $100M. ATR 0–12 means the full range ("Any"): no ATR cut, and 12 is "12%+".
    min_avg_dollar_volume: float = 100_000_000
    atr_pct_min: float = 0.0
    atr_pct_max: float = 12.0
    # Short daily setups (1 = on, 0 = off). Default: only EMA Crossback Short (via inverse ETFs).
    short_hvc: int = 0
    short_crossback: int = 1
    short_ma10: int = 0
    short_ma20: int = 0
    short_ma50: int = 0
    short_overcut: int = 0
    short_wedge: int = 0
    short_flat: int = 0
    short_flag: int = 0
    short_gap: int = 0
    touch_tol_pct: float = 0.1  # a low this close above the EMA counts as a touch (MA touch mode)
    hold_pct: float = 0.3  # a close more than this under the EMA has lost it
    rising_bars: int = 4  # rising = higher than this many bars earlier (4 bars = 1 hour)
    watch_bars: int = 4  # MA touch: bars after the touch the buy stop stays live
    max_attempts: int = 2
    breakeven_after_new_highs: int = 3  # MA touch: BE after this many new-high bars
    exit_close_under_ma: int = 1  # MA touch only: full exit on close under the setup EMA
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

    def uses_ema_cross(self) -> bool:
        return int(self.entry_trigger) == ENTRY_EMA_CROSS

    def daily_trim_emas(self) -> tuple[int, int]:
        return (int(self.trim_daily_ema_1), int(self.trim_daily_ema_2))

    def atr_filter_off(self) -> bool:
        """True when the ATR slider is the full 0–12%+ range, which filters nothing."""
        return self.atr_pct_min <= 0 and self.atr_pct_max >= 12


def known_setup(setup: str) -> bool:
    """True when ``setup`` is a legacy MA-touch / short key or a cross-period long setup."""
    if setup in SETUPS:
        return True
    if str(setup).startswith("s"):
        return False
    try:
        return 2 <= int(setup) <= 50
    except ValueError:
        return False


def ema_periods_for(settings: Optional["Settings"] = None) -> tuple[int, ...]:
    """15-minute EMA periods to seed and continue (MA-touch set, cross entry)."""
    s = settings or Settings()
    found = set(MA_PERIODS)
    found.add(int(s.cross_ema_period))
    found.add(int(s.cross_above_ema))
    return tuple(sorted(p for p in found if p > 0))


# Hard floor: a name needs a 14-day ATR above this percent of price to go on the auto watchlist or to
# alert at all, manual watchlist names included. At or below it (or with no ATR yet) there is no alert.
MIN_ALERT_ATR_PCT = 3.0


def above_atr_floor(row: Optional[Mapping]) -> bool:
    """True when the row's ATR % is strictly above ``MIN_ALERT_ATR_PCT``."""
    atr = row.get("atr_pct") if row else None
    return isinstance(atr, (int, float)) and float(atr) > MIN_ALERT_ATR_PCT


def passes_name_screen(row: Mapping, settings: Settings) -> bool:
    """Daily-scan dollar volume and ATR % gates. Manual watchlist names are not run through this.

    Every name must first be above the hard ATR floor (> ``MIN_ALERT_ATR_PCT``).
    The slider at 0–12 ("Any") adds no further ATR cut; a tighter range narrows it. 12%+ means no upper limit.
    """
    if not above_atr_floor(row):
        return False
    volume = row.get("avg_dollar_volume")
    if not isinstance(volume, (int, float)) or float(volume) < float(settings.min_avg_dollar_volume):
        return False
    if settings.atr_filter_off():
        return True
    atr = row.get("atr_pct")
    if not isinstance(atr, (int, float)):
        return False
    if float(atr) < float(settings.atr_pct_min):
        return False
    return settings.atr_pct_max >= 12 or float(atr) <= float(settings.atr_pct_max)


STOP_WIDEN = 0
STOP_CANDLE = 1
STOP_FIXED = 2

SETTING_LIMITS: dict[str, tuple[float, float]] = {
    "max_symbols": (1, 1000),
    "theme_gate": (0, 1), "theme_top_pct": (1, 50),
    "shorts": (0, 1), "max_short_symbols": (0, 1000), "shorts_ma120_enabled": (0, 1),
    "ma_120": (0, 1), "ma_240": (0, 1), "ma_480": (0, 1),
    "entry_trigger": (0, 1), "cross_ema_period": (2, 50), "cross_min_body_pct": (0, 100),
    "cross_above_ema": (0, 200), "trade_window_minutes": (15, 390),
    "trim_daily_ema_1": (2, 200), "trim_daily_ema_2": (2, 200), "trail_stop_bars": (0, 20),
    "breakeven_after_bars": (1, 50), "inverse_etf_shorts": (0, 1),
    "long_max_ext_vs_d10ema_pct": (0, 100), "long_ext_ema_period": (1, 200),
    "long_ext_waive_at_d4ema": (0, 1),
    "stop_mode": (0, 2), "fixed_stop_pct": (0.1, 5), "max_stop_pct": (0.1, 10), "min_stop_pct": (0, 5),
    "long_pending_only": (0, 1), "reset_manual": (0, 1), "alert_manual_watchlist": (0, 1),
    "min_avg_dollar_volume": (10_000_000, 5_000_000_000),
    "atr_pct_min": (0, 12), "atr_pct_max": (0, 12),
    "short_hvc": (0, 1), "short_crossback": (0, 1),
    "short_ma10": (0, 1), "short_ma20": (0, 1), "short_ma50": (0, 1),
    "short_overcut": (0, 1), "short_wedge": (0, 1), "short_flat": (0, 1),
    "short_flag": (0, 1), "short_gap": (0, 1),
    "touch_tol_pct": (0, 5), "hold_pct": (0, 5), "rising_bars": (1, TAIL_KEEP - 1), "watch_bars": (1, 26),
    "max_attempts": (1, 20), "breakeven_after_new_highs": (1, 50),
    "exit_close_under_ma": (0, 1),
    "top_names": (0, 50), "earnings_window_days": (0, 30), "auto_archive": (0, 1),
}


@dataclass
class Context:
    """Per symbol, per day inputs that are not today's bars."""

    # Per period: the EMA after each of the prior session's last few regular bars, oldest first.
    ma_tail: Mapping[int, Sequence[float]] = field(default_factory=dict)
    prev_close: Optional[float] = None  # last regular-session close before today
    session_bars: int = SESSION_BARS  # bars in a full session (fewer on a half day)
    # Daily bars (or closes) through the previous session only — input to ``long_extension_skip``.
    prior_daily_bars: Sequence[Any] = field(default_factory=tuple)
    # Finished daily closes before today, oldest first: the daily trim EMAs (today's close is the mark price).
    daily_closes: Sequence[float] = field(default_factory=tuple)
    # Today's 15:59 ET price for the daily trim check: {"price", "at" (UTC ISO), "late"}. None until taken.
    close_mark: Optional[Mapping[str, Any]] = None


def context_from_closes(
    closes: Sequence[float],
    session_bars: int = SESSION_BARS,
    periods: Optional[Sequence[int]] = None,
) -> Context:
    """Context from prior sessions' regular 15-minute closes (oldest first). Periods without enough closes stay unknown."""
    tails = {}
    for p in (periods if periods is not None else ema_periods_for()):
        series = [v for v in ema_series(closes, int(p)) if v is not None]
        if series:
            tails[int(p)] = series[-TAIL_KEEP:]
    return Context(ma_tail=tails, prev_close=float(closes[-1]) if closes else None, session_bars=session_bars)


@dataclass
class Alert:
    symbol: str
    session: str
    setup: str  # MA touch: "120"/"240"/"480" or "s…"; cross: period string e.g. "6"
    origin_bar: datetime  # the signal bar (the key)
    setup_bar: datetime  # the candle whose high + $0.01 is the buy stop (moves while waiting in MA-touch)
    setup_index: int
    trigger: float
    stop: float
    setup_low: float  # pullback / cross candle low
    setup_high: float  # high of ``setup_bar``
    ref_price: float  # signal bar close
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
    bars_since_fill: int = 0
    remaining_frac: float = 1.0
    realized_r: float = 0.0
    trims_done: int = 0  # cross ladder: 0..3 thirds taken
    post_fill_lows: list = field(default_factory=list)  # lows of the bars after the trigger candle (trail stop)

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
    def is_cross(self) -> bool:
        return bool(self.details.get("entry_trigger") == ENTRY_EMA_CROSS)

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
        self.details["remaining_frac"] = self.remaining_frac
        self.details["realized_r"] = round(self.realized_r, 4)
        self.details["bars_since_fill"] = self.bars_since_fill
        self.details["trims_done"] = self.trims_done
        if self.filled:
            self.details["current_stop"] = round(self.current_stop, 4)
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


def trade_cutoff(ts: datetime, settings: Optional["Settings"] = None) -> datetime:
    """The trade cutoff on the trading day of ``ts``: ``trade_window_minutes`` after the 09:30 ET open
    (a naive ``ts`` is read as UTC)."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    minutes = int(settings.trade_window_minutes) if settings is not None else TRADE_WINDOW_MINUTES
    day = ts.astimezone(TRADE_CUTOFF_TZ).date()
    wall = datetime.combine(day, SESSION_OPEN) + timedelta(minutes=minutes)
    return wall.replace(tzinfo=TRADE_CUTOFF_TZ)


def cutoff_label(settings: Optional["Settings"] = None) -> str:
    """The cutoff as an ET clock time, e.g. ``10:45``."""
    minutes = int(settings.trade_window_minutes) if settings is not None else TRADE_WINDOW_MINUTES
    return (datetime.combine(date(2000, 1, 3), SESSION_OPEN) + timedelta(minutes=minutes)).strftime("%H:%M")


def after_cutoff(ts: datetime, settings: Optional["Settings"] = None) -> bool:
    """True when ``ts`` is at or past the trade-window cutoff."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts >= trade_cutoff(ts, settings)


def _close_window(a: "Alert", bar: Mapping, settings: Optional["Settings"] = None) -> bool:
    """A waiting alert expires at the cutoff instead of filling on a bar that starts after it."""
    if a.status != "pending" or not after_cutoff(bar["t"], settings):
        return False
    a.status = "expired"
    a.exit_at = trade_cutoff(bar["t"], settings).astimezone(timezone.utc)
    a.exit_reason = "trade_window"
    return True


def _iso(ts: Optional[datetime]) -> Optional[str]:
    if ts is None:
        return None
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------------------------- indicators


def skip_counts() -> dict[str, int]:
    """In-memory skipped-today counts by reason (``ext_cap``, ``ma120_short_disabled``)."""
    with _skip_lock:
        return dict(_skip_counts)


def reset_skip_counts(session: Optional[str] = None) -> None:
    """Clear skipped-today counts (daily rollover / archive)."""
    global _skip_session
    with _skip_lock:
        _skip_session = session
        for key in _skip_counts:
            _skip_counts[key] = 0


def record_skip(
    session: str,
    reason: str,
    *,
    symbol: str,
    setup: str,
    side: str,
    trigger: Optional[float] = None,
    prior_d10_ema: Optional[float] = None,
    ext_pct: Optional[float] = None,
    prior_d4_ema: Optional[float] = None,
    ext_vs_d4_pct: Optional[float] = None,
    waived: Optional[bool] = None,
) -> None:
    """Bump the in-memory skip counter and emit a structured skip log line."""
    global _skip_session
    with _skip_lock:
        if _skip_session != session:
            _skip_session = session
            for key in _skip_counts:
                _skip_counts[key] = 0
        if reason in _skip_counts:
            _skip_counts[reason] += 1
    log.info(
        "alert_skip symbol=%s setup=%s side=%s trigger=%s prior_d10_ema=%s ext_pct=%s "
        "prior_d4_ema=%s ext_vs_d4_pct=%s waived=%s reason=%s",
        symbol,
        setup,
        side,
        None if trigger is None else round(float(trigger), 4),
        None if prior_d10_ema is None else round(float(prior_d10_ema), 4),
        None if ext_pct is None else round(float(ext_pct), 4),
        None if prior_d4_ema is None else round(float(prior_d4_ema), 4),
        None if ext_vs_d4_pct is None else round(float(ext_vs_d4_pct), 4),
        waived,
        reason,
    )


def ewm_last(values: Sequence[float], period: int) -> Optional[float]:
    """Last EMA over ``values`` (pandas ``ewm(span=period, adjust=False)`` with ``min_periods=period``)."""
    if period <= 0 or len(values) < period:
        return None
    k = 2.0 / (period + 1)
    value = float(values[0])
    for v in values[1:]:
        value += k * (float(v) - value)
    return value


def _closes_from_daily_bars(daily_bars: Sequence[Any]) -> list[float]:
    """Extract closes from a sequence of floats or bar mappings with a ``close`` field."""
    out: list[float] = []
    for bar in daily_bars or ():
        try:
            if isinstance(bar, Mapping):
                out.append(float(bar["close"]))
            else:
                out.append(float(bar))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def prior_daily_bars_from_frame(daily: Any, session: date) -> list[dict]:
    """Daily ``{close}`` bars through the session before ``session``; bars on ``session`` or later are ignored."""
    if daily is None:
        return []
    try:
        if getattr(daily, "empty", True):
            return []
    except (TypeError, ValueError):
        return []
    out: list[dict] = []
    for ts, row in daily.iterrows():
        try:
            d = ts.date() if hasattr(ts, "date") else date.fromisoformat(str(ts)[:10])
        except ValueError:
            continue
        if d >= session:
            continue
        try:
            out.append({"close": float(row["close"])})
        except (KeyError, TypeError, ValueError):
            continue
    return out


def prior_daily_ema(closes: Sequence[float], period: int) -> Optional[float]:
    """Daily EMA of ``closes`` for ``period``. Caller must end at the previous session (no today's bar)."""
    return ewm_last(closes, period)


def long_extension_skip(
    price: float,
    daily_bars: Sequence[Any],
    settings: Settings,
) -> tuple[bool, dict]:
    """Long extension cap with optional daily-4 EMA waiver: ``(skip, details)``.

    Skip when ``price`` is more than ``long_max_ext_vs_d10ema_pct`` percent above the prior-session
    daily EMA of ``long_ext_ema_period``. When ``long_ext_waive_at_d4ema`` is on and ``price`` is at
    or under the prior-session daily 4 EMA, do not skip even if over the cap. ``daily_bars`` must
    already exclude today's partial bar. Cap of 0 (or missing EMA) does not skip.
    """
    cap = float(settings.long_max_ext_vs_d10ema_pct)
    if cap <= 0 or not isinstance(price, (int, float)) or float(price) <= 0:
        return False, {}
    period = int(settings.long_ext_ema_period)
    closes = _closes_from_daily_bars(daily_bars)
    ema = prior_daily_ema(closes, period)
    if ema is None or ema <= 0:
        return False, {}
    px = float(price)
    ext_pct = (px - ema) / ema * 100.0
    d4 = prior_daily_ema(closes, 4)
    ext_vs_d4 = ((px - d4) / d4 * 100.0) if d4 is not None and d4 > 0 else None
    details = {
        "prior_d10_ema": ema,
        "ext_pct": ext_pct,
        "ema_period": period,
        "prior_d4_ema": d4,
        "ext_vs_d4_pct": ext_vs_d4,
        "waived": False,
        "reason": SKIP_EXT_CAP,
    }
    if ext_pct <= cap:
        return False, details
    if settings.long_ext_waive_at_d4ema and d4 is not None and d4 > 0 and px <= d4:
        details["waived"] = True
        return False, details
    return True, details


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

    def __init__(self, bars: Sequence[Mapping], ctx: Context, periods: Optional[Sequence[int]] = None):
        self.bars = list(bars)
        self.ctx = ctx
        closes = [float(b["c"]) for b in self.bars]
        period_list = list(periods) if periods is not None else list(ema_periods_for())
        for p in ctx.ma_tail:
            if int(p) not in period_list:
                period_list.append(int(p))
        self.periods = tuple(sorted(set(int(p) for p in period_list)))
        self.tail = {p: list(ctx.ma_tail.get(p) or ()) for p in self.periods}
        self.ma = {
            p: ema_continue(self.tail[p][-1] if self.tail[p] else None, closes, p)
            for p in self.periods
        }

    def ma_at(self, p: int, i: int) -> Optional[float]:
        if p not in self.ma:
            return None
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


def cross_body_ok(bar: Mapping, min_body_pct: float) -> bool:
    """Cross-candle strength: green with body >= ``min_body_pct``% of range (0 disables; zero range fails)."""
    if float(min_body_pct) <= 0:
        return True
    o, h, l, c = float(bar["o"]), float(bar["h"]), float(bar["l"]), float(bar["c"])
    if not (c > o):
        return False
    rng = h - l
    if rng <= 0:
        return False
    return (c - o) / rng * 100.0 >= float(min_body_pct)


def match_cross(f: Frame, i: int, period: int, s: Settings) -> Optional[dict]:
    """Bar ``i`` closes above the ``period`` EMA after the prior close was at or below it (strict).

    Also requires a green candle whose body is at least ``cross_min_body_pct`` of its range (unless 0), and a
    close above the ``cross_above_ema`` EMA (unless 0, or that EMA has no history yet).
    """
    m, mp = f.ma_at(period, i), f.ma_at(period, i - 1)
    pc = f.close_at(i - 1)
    if m is None or mp is None or pc is None or m <= 0:
        return None
    if not (pc <= mp):
        return None
    b = f.bars[i]
    if not (float(b["c"]) > m):
        return None
    if not cross_body_ok(b, s.cross_min_body_pct):
        return None
    above = int(s.cross_above_ema)
    if above > 0:
        trend = f.ma_at(above, i)
        if trend is not None and not (float(b["c"]) > trend):
            return None
    slope = ((mp - (f.ma_at(period, i - 2) or mp)) / mp * 100) if mp else 0.0
    return {"ma": m, "slope_pct": slope}


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


# --------------------------------------------------------------------------------------------- order levels


def apply_order(a: "Alert", high: float, low: float, s: Settings) -> bool:
    """Point the working order at this candle. False when the stop is past ``max_stop_pct``, closer than
    ``min_stop_pct``, or on the wrong side (:func:`stop_too_tight` tells the two size cases apart).

    Cross mode always uses this candle's high + 1c / low - 1c. MA-touch uses ``stop_mode``.
    """
    high, low = float(high), float(low)
    candle_only = a.is_cross or s.stop_mode in (STOP_CANDLE, STOP_FIXED)
    if a.short:
        trigger = round(low - TICK, 2)
        extreme = high if candle_only else max(a.setup_high, high)
        a.setup_high, a.setup_low = extreme, low
        if a.is_cross or s.stop_mode != STOP_FIXED:
            stop = round(extreme + TICK, 2)
        else:
            stop = round(trigger * (1 + s.fixed_stop_pct / 100), 2)
        wrong_side = stop <= trigger
    else:
        trigger = round(high + TICK, 2)
        extreme = low if candle_only else min(a.setup_low, low)
        a.setup_low, a.setup_high = extreme, high
        if a.is_cross or s.stop_mode != STOP_FIXED:
            stop = round(extreme - TICK, 2)
        else:
            stop = round(trigger * (1 - s.fixed_stop_pct / 100), 2)
        wrong_side = stop >= trigger
    if trigger <= 0 or stop <= 0 or wrong_side:
        return False
    a.trigger = trigger
    a.stop = a.current_stop = stop
    pct = abs(trigger - stop) / trigger * 100
    return pct <= s.max_stop_pct + 0.05 and not pct < float(s.min_stop_pct)


def stop_too_tight(a: "Alert", s: Settings) -> bool:
    """After :func:`apply_order` returned False: True when the stop was closer than ``min_stop_pct``."""
    return a.trigger > 0 and abs(a.trigger - a.stop) / a.trigger * 100 < float(s.min_stop_pct)


def _note_feed(a: "Alert", bar: Mapping) -> None:
    """Remember which feed priced the candle the working order sits on (sip, yahoo, or iex)."""
    src = bar.get("src")
    if src in ("sip", "yahoo", "iex"):
        a.details["bar_feed"] = src


def _rearm(a: "Alert", bar: Mapping, index: int, s: Settings, end: datetime) -> bool:
    """Move the working order onto ``bar``. False cancels the watch because the new stop is too wide."""
    a.setup_bar, a.setup_index = bar["t"], index
    if not apply_order(a, float(bar["h"]), float(bar["l"]), s):
        a.status = "cancelled"
        a.exit_reason = "stop_too_tight" if stop_too_tight(a, s) else "stop_too_wide"
        a.exit_at = end
        return False
    a.details["rearmed"] = a.details.get("rearmed", 0) + 1
    _note_feed(a, bar)
    return True


# --------------------------------------------------------------------------------------------- outcomes


def _risk_per_share(a: Alert) -> float:
    fill = a.fill_price or a.trigger
    return abs(fill - a.stop)


def _piece_r(a: Alert, price: float) -> Optional[float]:
    risk = _risk_per_share(a)
    if risk <= 0:
        return None
    fill = a.fill_price or a.trigger
    if a.short:
        return (fill - price) / risk
    return (price - fill) / risk


def _close_trade(a: Alert, price: float, at: datetime, reason: str, status: str, frac: Optional[float] = None) -> None:
    """Exit ``frac`` of the original size (default: all remaining). Weighted R across partials."""
    if frac is None:
        frac = a.remaining_frac
    frac = min(float(frac), a.remaining_frac)
    if frac <= 0:
        return
    piece = _piece_r(a, price)
    if piece is not None:
        a.realized_r += frac * piece
    a.remaining_frac = max(0.0, round(a.remaining_frac - frac, 6))
    a.details.setdefault("trims", []).append({
        "frac": round(frac, 4),
        "price": round(float(price), 4),
        "r": None if piece is None else round(piece, 4),
        "reason": reason,
        "at": _iso(at),
    })
    # Float thirds leave a tiny remainder; treat anything under a basis point of size as flat.
    if a.remaining_frac > 1e-5:
        return
    a.remaining_frac = 0.0
    a.exit_price = price
    a.exit_at = at
    a.exit_reason = reason
    a.status = status
    a.r_multiple = a.realized_r
    if reason in STOP_EXIT_REASONS:
        a.stop_hit = True


def _fill(a: Alert, bar: Mapping) -> None:
    a.filled = True
    a.fill_at = bar["t"]
    a.status = "triggered"
    a.current_stop = a.stop
    a.bars_since_fill = 0
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


def _close_through(bar: Mapping, ma: Optional[float], short: bool = False) -> bool:
    """Strict close through the EMA against the position (no hold_pct slack)."""
    if ma is None:
        return False
    if short:
        return float(bar["c"]) > ma
    return float(bar["c"]) < ma


def _move_stop(a: Alert, price: float, at: datetime, reason: str) -> None:
    """Raise the working stop and record the move, so the local order app can replace its stop order."""
    stops = a.details.setdefault("stops", [])
    stops.append({
        "step": len(stops) + 1,
        "price": round(float(price), 4),
        "from": round(float(a.current_stop), 4),
        "reason": reason,
        "at": _iso(at),
    })
    a.current_stop = float(price)


def _stop_out(a: Alert, bar: Mapping, end: datetime) -> None:
    """The bar traded the working stop (long): exit what remains there, or at the open on a gap through it."""
    price = min(a.current_stop, float(bar["o"]))
    fill = a.fill_price or a.trigger
    a.stop_hit = True
    if a.details.get("stops"):
        status = "stopped" if price < fill else ("breakeven" if price == fill else "exited")
        _close_trade(a, price, end, "trail_stop", status)
    elif a.breakeven_at is not None and a.current_stop >= fill:
        _close_trade(a, price, end, "breakeven_stop", "breakeven")
    else:
        _close_trade(a, price, end, "stop", "stopped")


def _mark_at(ctx: Context) -> Optional[datetime]:
    mark = ctx.close_mark
    if not mark or mark.get("price") is None or not mark.get("at"):
        return None
    return datetime.fromisoformat(str(mark["at"]).replace("Z", "+00:00")).astimezone(timezone.utc)


def daily_close_check(a: Alert, ctx: Context, s: Settings) -> None:
    """The 15:59 ET daily-chart trim check, once per session per alert (``details["close_checks"]``).

    Step 1 sells a third at the first check after the fill (the entry day). Step 2 sells a third when the
    price is under the daily ``trim_daily_ema_1``, step 3 the rest under ``trim_daily_ema_2``. The daily
    EMAs are of the finished daily closes plus the 15:59 price as today's close. Steps go in order and one
    check may take several. Crossback trades only; nothing without a mark.
    """
    at = _mark_at(ctx)
    if at is None or not a.is_cross or a.status != "triggered" or a.remaining_frac <= 0:
        return
    if a.fill_at is not None and a.fill_at >= at:
        return
    day = at.astimezone(TRADE_CUTOFF_TZ).date().isoformat()
    checks = a.details.setdefault("close_checks", {})
    if day in checks:
        return
    price = float(ctx.close_mark["price"])  # type: ignore[index]
    closes = [float(c) for c in ctx.daily_closes] + [price]
    emas = {p: ewm_last(closes, p) for p in s.daily_trim_emas()}
    checks[day] = {
        "price": round(price, 4),
        "at": _iso(at),
        "ema": {str(p): (None if v is None else round(v, 4)) for p, v in emas.items()},
        "late": bool(ctx.close_mark.get("late")),  # type: ignore[union-attr]
    }
    steps = [(TRIM_DAY_CLOSE, True)] + [
        (f"{TRIM_DAILY_PREFIX}{p}", _close_through({"c": price}, emas[p], short=a.short)) for p in s.daily_trim_emas()
    ]
    for step_i, (reason, hit) in enumerate(steps):
        if step_i < a.trims_done:
            continue
        if not hit:
            break
        _close_trade(a, price, at, reason, "exited", frac=min(TRIM_FRAC, a.remaining_frac))
        a.details["trims"][-1]["late"] = checks[day]["late"]
        a.trims_done = step_i + 1
        if a.status not in ACTIVE:
            return


def _close_check_before(alerts: Sequence[Alert], bar: Mapping, ctx: Context, s: Settings) -> None:
    """Run the 15:59 check ahead of the bar it falls in (the last bar of the day), so a later poll that
    has that bar complete takes the same trims the 15:59 poll reported."""
    at = _mark_at(ctx)
    if at is None or bar["t"] + BAR <= at:
        return
    for a in alerts:
        daily_close_check(a, ctx, s)


def _step_short(a: Alert, bar: Mapping, index: int, f: Frame, s: Settings) -> None:
    """``step`` for a short alert: every comparison mirrored (legacy MA-touch shorts)."""
    end = bar["t"] + BAR
    ma = f.ma_at(a.period, index)
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
        _rearm(a, bar, index, s, end)
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


def _step_cross(a: Alert, bar: Mapping, index: int, f: Frame, s: Settings) -> None:
    """Advance a crossback alert: fixed candle order, cancel on low break, thirds ladder after fill."""
    end = bar["t"] + BAR
    if a.status == "pending":
        a.bars_waited += 1
        # Fill if the buy is traded; else cancel if price breaks the cross candle's low - 1c.
        if bar["h"] >= a.trigger:
            _fill(a, bar)
            if bar["l"] <= a.current_stop:
                a.stop_hit = True
                _close_trade(a, a.current_stop, end, "stop", "stopped")
            else:
                # Same bar as fill: still run BE/ladder only on later bars; count starts after fill bar.
                pass
            return
        if bar["l"] <= a.stop:
            a.status = "cancelled"
            a.exit_reason = "broke_setup_low"
            a.exit_at = end
            return
        # No rearm, no watch_bars expiry — trade window / session end handle the rest.
        return
    if a.status != "triggered":
        return
    a.bars_since_fill += 1
    if bar["l"] <= a.current_stop:
        _stop_out(a, bar, end)
        return
    a.high_reached = max(a.high_reached or bar["h"], float(bar["h"]))
    if bar["h"] > a.running_high:
        a.running_high = float(bar["h"])
        a.new_highs += 1
    trail = int(s.trail_stop_bars)
    if trail > 0:
        if not a.details.get("trailed"):
            a.post_fill_lows.append(float(bar["l"]))
            if len(a.post_fill_lows) >= trail:
                a.details["trailed"] = True
                level = round(min(a.post_fill_lows[:trail]) - TICK, 4)
                if level > a.current_stop:
                    _move_stop(a, level, end, f"low_of_{trail}_bars")
    elif a.breakeven_at is None and a.bars_since_fill >= s.breakeven_after_bars:
        a.breakeven_at = end
        a.current_stop = max(a.current_stop, a.fill_price or a.trigger)


def step(a: Alert, bar: Mapping, index: int, f: Frame, s: Settings) -> None:
    """Advance one active alert by one completed bar (the bars after its signal bar, in order)."""
    if a.is_cross:
        _step_cross(a, bar, index, f, s)
        return
    if a.short:
        _step_short(a, bar, index, f, s)
        return
    end = bar["t"] + BAR
    ma = f.ma_at(a.period, index)
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
        _rearm(a, bar, index, s, end)
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


def check_forming(a: Alert, bar: Mapping, settings: Optional[Settings] = None) -> None:
    """Forming bar: fill on buy stop, or (cross) cancel if price breaks the setup low - 1c."""
    if a.status != "pending" or after_cutoff(bar["t"], settings):
        return
    if a.is_cross and not a.short and float(bar["l"]) <= a.stop and float(bar["h"]) < a.trigger:
        a.status = "cancelled"
        a.exit_reason = "broke_setup_low"
        a.exit_at = bar["t"] + BAR
        return
    through = float(bar["l"]) <= a.trigger if a.short else float(bar["h"]) >= a.trigger
    if through:
        _fill(a, bar)
        a.details["fill_on_forming_bar"] = True


def finish_session(a: Alert, last_bar: Mapping) -> None:
    """The session is over: a waiting alert expires. An open MA-touch trade is closed at the last close;
    an open crossback trade is held overnight for the daily trim ladder."""
    end = last_bar["t"] + BAR
    if a.status == "pending":
        a.status = "expired"
        a.exit_at = end
        a.exit_reason = "session_end"
    elif a.status == "triggered" and not a.is_cross:
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
    if not bars or not known_setup(setup):
        return None
    setup_i = _index_of(bars, setup_bar)
    origin_i = _index_of(bars, origin_bar)
    if setup_i is None:
        return None
    det = dict(details or {})
    a = Alert(
        symbol=symbol, session=session, setup=setup, origin_bar=origin_bar, setup_bar=setup_bar,
        setup_index=setup_i, trigger=trigger, stop=stop, setup_low=setup_low, setup_high=setup_high,
        ref_price=ref_price, details=det, current_stop=stop,
        bars_waited=setup_i - origin_i if origin_i is not None else 0,
        remaining_frac=float(det.get("remaining_frac", 1.0) or 1.0),
        realized_r=float(det.get("realized_r", 0.0) or 0.0),
        trims_done=int(det.get("trims_done", 0) or 0),
        bars_since_fill=int(det.get("bars_since_fill", 0) or 0),
    )
    f = Frame(bars, ctx, periods=ema_periods_for(s))
    for i in range(setup_i + 1, len(bars)):
        if a.status not in ACTIVE:
            break
        if _close_window(a, bars[i], s):
            break
        _close_check_before([a], bars[i], ctx, s)
        if a.status not in ACTIVE:
            break
        step(a, bars[i], i, f, s)
    daily_close_check(a, ctx, s)
    if a.status in ACTIVE and ctx.session_bars and len(bars) >= ctx.session_bars:
        finish_session(a, bars[-1])
    elif forming is not None:
        check_forming(a, forming, s)
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
    skip_extension_cap: bool = False,
) -> list[Alert]:
    """Alerts for one symbol and day, oldest first, with outcomes through the last bar given.

    With ``entry_trigger=1`` (default) and ``side="long"``, looks for a close above the cross EMA after
    a prior close at or below it. With ``entry_trigger=0``, uses the rising-EMA pullback (``touch``).
    ``side="short"`` is the legacy falling-EMA mirror (kept for tests / history; live shorts use inverse ETFs).

    ``bars`` are that day's completed regular-session bars in order, starting with the opening bar.
    ``forming`` is the bar still forming (live only): it can fill a waiting alert, nothing else.
    When ``skipped`` is a list, signals that were not alerted are appended to it (for replays).
    ``skip_extension_cap`` disables the long extension skip (inverse-ETF short proxies).
    """
    s = settings or Settings()
    if not bars:
        return []
    f = Frame(bars, ctx, periods=ema_periods_for(s))
    alerts: list[Alert] = []
    use_cross = s.uses_ema_cross() and side == "long"
    for i, bar in enumerate(f.bars):
        _close_check_before(alerts, bar, ctx, s)
        for a in alerts:
            if a.status in ACTIVE and a.setup_index < i and not _close_window(a, bar, s):
                step(a, bar, i, f, s)
        if use_cross:
            period = int(s.cross_ema_period)
            lv = match_cross(f, i, period, s)
            if not lv:
                continue
            touched = [period]
            setup_key = str(period)
        else:
            hit = touch(f, i, s, side)
            if not hit:
                continue
            period, lv, touched = hit
            setup_key = f"s{period}" if side == "short" else str(period)
        reason = None
        if i + 1 >= ctx.session_bars:
            reason = "last bar of the session"
        elif bar["t"] + BAR > trade_cutoff(bar["t"], s):
            reason = "after the %s ET trade cutoff" % cutoff_label(s)
        elif any(a.status in ACTIVE for a in alerts):
            reason = "an alert on this name is still live"
        elif sum(1 for a in alerts if a.filled) >= s.max_attempts:
            reason = "%d attempts already" % s.max_attempts
        if reason:
            if skipped is not None:
                skipped.append({"symbol": symbol, "bar": _iso(bar["t"]), "setup": setup_key, "reason": reason})
            continue
        alert = Alert(
            symbol=symbol, session=session, setup=setup_key, origin_bar=bar["t"], setup_bar=bar["t"],
            setup_index=i, trigger=0.0, stop=0.0, setup_low=float(bar["l"]),
            setup_high=float(bar["h"]), ref_price=float(bar["c"]), current_stop=0.0,
            details={
                "ma": round(lv["ma"], 4),
                "ma_slope_pct": round(lv["slope_pct"], 3),
                "touched": touched,
                "entry_trigger": ENTRY_EMA_CROSS if use_cross else ENTRY_MA_TOUCH,
                "ma_values": {
                    str(p): (None if f.ma_at(p, i) is None else round(f.ma_at(p, i), 4))  # type: ignore[arg-type]
                    for p in f.periods
                },
            },
        )
        if not apply_order(alert, float(bar["h"]), float(bar["l"]), s):
            if skipped is not None:
                skipped.append({"symbol": symbol, "bar": _iso(bar["t"]), "setup": setup_key, "reason": "stop tighter than the min" if stop_too_tight(alert, s) else "stop wider than the max"})
            continue
        if side == "short" and period == 120 and not s.shorts_ma120_enabled:
            record_skip(
                session, SKIP_MA120_SHORT,
                symbol=symbol, setup=setup_key, side=side, trigger=alert.trigger,
            )
            if skipped is not None:
                skipped.append({"symbol": symbol, "bar": _iso(bar["t"]), "setup": setup_key, "reason": SKIP_MA120_SHORT})
            continue
        if side == "long" and not skip_extension_cap:
            skip_ext, ext_details = long_extension_skip(alert.trigger, ctx.prior_daily_bars, s)
            if skip_ext:
                record_skip(
                    session, SKIP_EXT_CAP,
                    symbol=symbol, setup=setup_key, side=side,
                    trigger=alert.trigger,
                    prior_d10_ema=ext_details.get("prior_d10_ema"),
                    ext_pct=ext_details.get("ext_pct"),
                    prior_d4_ema=ext_details.get("prior_d4_ema"),
                    ext_vs_d4_pct=ext_details.get("ext_vs_d4_pct"),
                    waived=ext_details.get("waived"),
                )
                if skipped is not None:
                    skipped.append({
                        "symbol": symbol, "bar": _iso(bar["t"]), "setup": setup_key,
                        "reason": SKIP_EXT_CAP, "trigger": alert.trigger,
                        **{
                            k: ext_details[k]
                            for k in ("prior_d10_ema", "ext_pct", "ema_period", "prior_d4_ema", "ext_vs_d4_pct", "waived")
                            if k in ext_details
                        },
                    })
                continue
        _note_feed(alert, bar)
        alerts.append(alert)
    for a in alerts:
        daily_close_check(a, ctx, s)
    if len(f.bars) >= ctx.session_bars:
        for a in alerts:
            finish_session(a, f.bars[-1])
    elif forming is not None:
        for a in alerts:
            check_forming(a, forming, s)
    return alerts


# Row columns a carried position starts each session from (with ``details`` minus the snapshot itself).
_CARRY_COLUMNS = (
    "status", "filled", "fill_price", "fill_at", "high_reached", "stop_hit", "breakeven_at",
    "exit_price", "exit_at", "exit_reason", "r_multiple",
)


def _parse_iso(raw: Any) -> Optional[datetime]:
    if raw in (None, ""):
        return None
    if isinstance(raw, datetime):
        return raw.astimezone(timezone.utc)
    return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(timezone.utc)


def carry_alert(row: Mapping, day: str) -> Alert:
    """An open crossback position from an earlier session, as it stood at the start of ``day``.

    The first poll of ``day`` snapshots the stored row into ``details["carry"]``; every later poll that
    day restarts from that snapshot, so re-walking the day's bars never takes a trim or stop twice.
    """
    det = row.get("details") if isinstance(row.get("details"), dict) else json.loads(row.get("details") or "{}")
    det = dict(det or {})
    carry = det.get("carry") or {}
    if carry.get("day") != day:
        base = {k: row.get(k) for k in _CARRY_COLUMNS}
        base["details"] = {k: v for k, v in det.items() if k != "carry"}
        carry = {"day": day, "row": base}
    base = json.loads(json.dumps(carry["row"]))
    d = dict(base["details"])
    d["carry"] = carry
    d["trailed"] = True  # the intraday trail is an entry-day rule
    fill = None if base.get("fill_price") is None else float(base["fill_price"])
    stop = float(row["stop_price"])
    current = d.get("current_stop")
    if current is None:
        current = fill if base.get("breakeven_at") and fill is not None else stop
    parts = str(row["key"]).split("|")
    origin = _parse_iso(parts[3]) if len(parts) >= 4 else _parse_iso(row["fired_at"]) - BAR  # type: ignore[operator]
    high = base.get("high_reached")
    return Alert(
        symbol=row["symbol"], session=row["session"], setup=row["setup"], origin_bar=origin,  # type: ignore[arg-type]
        setup_bar=_parse_iso(row["setup_bar"]), setup_index=-1,  # type: ignore[arg-type]
        trigger=float(row["trigger_price"]), stop=stop, setup_low=float(row["setup_low"]),
        setup_high=float(row["setup_high"]), ref_price=float(row["ref_price"]),
        status=str(base["status"]), filled=bool(base.get("filled")), fill_price=fill,
        fill_at=_parse_iso(base.get("fill_at")), high_reached=high, stop_hit=bool(base.get("stop_hit")),
        breakeven_at=_parse_iso(base.get("breakeven_at")), exit_price=base.get("exit_price"),
        exit_at=_parse_iso(base.get("exit_at")), exit_reason=base.get("exit_reason"),
        r_multiple=base.get("r_multiple"), details=d, current_stop=float(current),
        running_high=float(high or fill or 0.0), bars_since_fill=int(d.get("bars_since_fill", 0) or 0),
        remaining_frac=float(d.get("remaining_frac", 1.0) if d.get("remaining_frac") is not None else 1.0),
        realized_r=float(d.get("realized_r", 0.0) or 0.0), trims_done=int(d.get("trims_done", 0) or 0),
    )


def advance_carried(a: Alert, bars: Sequence[Mapping], ctx: Context, settings: Optional[Settings] = None) -> Alert:
    """Walk a carried position through today's completed bars (stop) and today's 15:59 trim check."""
    s = settings or Settings()
    f = Frame(bars, ctx, periods=())
    for i, bar in enumerate(bars):
        if a.status != "triggered":
            break
        _close_check_before([a], bar, ctx, s)
        if a.status != "triggered":
            break
        _step_cross(a, bar, i, f, s)
    daily_close_check(a, ctx, s)
    return a


def open_r(row: Mapping, price: Optional[float]) -> Optional[float]:
    """Current R of a filled trade still open (status ``triggered``) at ``price``; None otherwise.

    1R is the fill minus the original stop (short: stop minus fill). With partial trims, returns
    realized weighted R plus remaining_frac times the open piece R.
    """
    if row.get("status") != "triggered" or not row.get("filled") or price is None:
        return None
    fill, stop = row.get("fill_price"), row.get("stop_price")
    if fill is None or stop is None:
        return None
    risk = abs(float(fill) - float(stop))
    if risk <= 0:
        return None
    if setup_side(str(row.get("setup"))) == "short":
        piece = (float(fill) - float(price)) / risk
    else:
        piece = (float(price) - float(fill)) / risk
    det = row.get("details")
    if isinstance(det, str):
        try:
            det = json.loads(det or "{}")
        except ValueError:
            det = {}
    if not isinstance(det, dict):
        det = {}
    rem = float(det.get("remaining_frac", 1.0) or 1.0)
    realized = float(det.get("realized_r", 0.0) or 0.0)
    return realized + rem * piece


def mark_top(rows: list[dict], top_names: int) -> set[str]:
    """First ``top_names`` distinct symbols of the day, by fire time (then symbol)."""
    names: list[str] = []
    for r in sorted(rows, key=lambda r: (r["fired_at"], r["symbol"])):
        if r["symbol"] not in names:
            names.append(r["symbol"])
        if len(names) >= top_names:
            break
    return set(names[:top_names])


_MA_SETUP_KINDS = ("ma-undercut-rally", "ma-overcut-fail")


def _ma_period(kind: str, label: str, explicit: Any = None) -> Optional[int]:
    """10 / 20 / 50 on a moving-average undercut or overcut, from the stored period or the label."""
    if kind not in _MA_SETUP_KINDS:
        return None
    if explicit is not None and str(explicit).isdigit():
        return int(explicit)
    if "(" in label and "-day" in label:
        chunk = label.rsplit("(", 1)[-1].split("-", 1)[0]
        if chunk.isdigit():
            return int(chunk)
    return None


# Stored on an alert that was checked because the user added the name, not because it qualified.
WATCHLIST_SETUP = {"kind": "watchlist", "label": "Watchlist", "side": "long"}


def daily_setup_ref(setup: Mapping) -> dict:
    """One scanner daily setup as stored on an alert: kind, friendly label, side, and the MA period when it has one."""
    kind = str(setup.get("kind") or "")
    label = str(setup.get("label") or kind)
    side = "short" if setup.get("side") == "short" else "long"
    ref = {"kind": kind, "label": label, "side": side}
    period = _ma_period(kind, label, setup.get("period"))
    if period is not None:
        ref["period"] = period
    return ref


def _daily_catalog() -> tuple[list[tuple[str, str, str]], dict[str, tuple[str, str]]]:
    """Display order of (key, friendly name, side), and friendly name -> (key, side)."""
    from .ariel_setups import LONG_KINDS, MA_UR_PERIODS, SETUP_LABELS, SHORT_MIRROR

    rows: list[tuple[str, str, str]] = []
    by_label: dict[str, tuple[str, str]] = {}

    def add(key: str, name: str, side: str) -> None:
        rows.append((key, name, side))
        by_label[name] = (key, side)

    for kind in LONG_KINDS:
        if kind == "ma-undercut-rally":
            base = SETUP_LABELS[kind]
            for period in sorted(MA_UR_PERIODS):
                add(f"{kind}:{period}", f"{base} ({period}-day)", "long")
        else:
            add(kind, SETUP_LABELS[kind], "long")
    for kind in LONG_KINDS:
        short_kind, short_name = SHORT_MIRROR[kind]
        if short_kind == "ma-overcut-fail":
            for period in sorted(MA_UR_PERIODS):
                add(f"{short_kind}:{period}", f"{short_name} ({period}-day)", "short")
        else:
            add(short_kind, short_name, "short")
    add(WATCHLIST_SETUP["kind"], WATCHLIST_SETUP["label"], WATCHLIST_SETUP["side"])
    return rows, by_label


def _row_details(row: Mapping) -> dict:
    raw = row.get("details")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "{}")
        except ValueError:
            raw = {}
    return raw if isinstance(raw, dict) else {}


def daily_setup_attributions(row: Mapping) -> list[tuple[str, str, Optional[str]]]:
    """Daily setups this alert counts under: ``(key, friendly name, side)``.

    A name can qualify on several daily setups, and the alert counts under each of them.
    The same setup is not counted twice on one alert. A row with nothing stored counts once as unknown.
    A plain label from an older row is matched to its setup when the name is one we know.
    """
    catalog, by_label = _daily_catalog()
    known = {key: (name, side) for key, name, side in catalog}
    raw = _row_details(row).get("daily_setups")
    if not isinstance(raw, list) or not raw:
        return [("unknown", "Unknown", None)]
    out: list[tuple[str, str, Optional[str]]] = []
    seen: set[str] = set()
    for item in raw:
        side: Optional[str]
        if isinstance(item, str):
            hit = by_label.get(item)
            if hit:
                key, side = hit
                name = known[key][0]
            else:
                key, name, side = f"label:{item}", item, None
        elif isinstance(item, dict) and item.get("kind"):
            kind = str(item["kind"])
            label = str(item.get("label") or "")
            period = _ma_period(kind, label, item.get("period"))
            key = f"{kind}:{period}" if period else kind
            stored_side = item.get("side")
            side = stored_side if stored_side in ("long", "short") else known.get(key, (None, None))[1]
            name = known.get(key, (label or kind, side))[0]
        else:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append((key, name, side))
    return out or [("unknown", "Unknown", None)]


def _metric_row(setup: str, name: str, side: Optional[str], group: Sequence[Mapping]) -> dict:
    filled = [r for r in group if r.get("filled")]
    closed = [r for r in filled if r.get("r_multiple") is not None]
    wins = [r for r in closed if round(r["r_multiple"], 2) > 0]  # a 1-cent scratch is not a win
    total = sum(r["r_multiple"] for r in closed)
    return {
        "setup": setup,
        "name": name,
        "side": side,
        "count": len(group),
        "filled": len(filled),
        "closed": len(closed),
        "open": len(filled) - len(closed),
        "fill_rate": round(len(filled) / len(group) * 100, 1) if group else None,
        "win_rate": round(len(wins) / len(closed) * 100, 1) if closed else None,
        "avg_r": round(total / len(closed), 2) if closed else None,
        "total_r": round(total, 2) if closed else None,
    }


def metrics(rows: Sequence[Mapping]) -> list[dict]:
    """Per daily setup: count, fill rate, win rate, average R, total R.

    Wins and R use closed filled trades (a win is R rounded to 2 decimals above 0). An alert is listed
    under every daily setup that qualified the name. ``All`` counts each alert once.
    """
    catalog, _ = _daily_catalog()
    buckets: dict[str, list[Mapping]] = {}
    labels = {key: (name, side) for key, name, side in catalog}
    order = [key for key, _, _ in catalog]
    for row in rows:
        for key, name, side in daily_setup_attributions(row):
            buckets.setdefault(key, []).append(row)
            labels.setdefault(key, (name, side))
            if key not in order:
                order.append(key)
    out = []
    for key in order:
        group = buckets.get(key) or []
        if not group:
            continue
        name, side = labels[key]
        out.append(_metric_row(key, name, side, group))
    # Unknown sits just above the total, after the named setups.
    if any(r["setup"] == "unknown" for r in out):
        out = [r for r in out if r["setup"] != "unknown"] + [r for r in out if r["setup"] == "unknown"]
    out.append(_metric_row("All", "All setups", None, list(rows)))
    return out
