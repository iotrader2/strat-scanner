"""RealSimpleAriel swing setups (the "Real Simple" playbook), replacing The Strat setups.

Source: https://www.tradezella.com/strategies/real-simple-strategy

The playbook is a repeatable swing system built around institutional buying,
sector strength and clean technical structure. The setup decision is always
made on the **daily** chart; the entry chart is only for timing the entry
(the playbook uses 5-minute bars — this scanner uses **15-minute** bars,
per the owner's request — see ``ENTRY_TF``).

The six setups, in the order they are checked:

1. **Episodic Pivot (EP)** — a large gap up, typically on earnings or news,
   with volume significantly above the average daily volume. Entry is an
   Opening Range Break on the entry chart, above the high of the first
   entry bar. Stop: low of day. The EP is a *same-day* trade, so it is
   detected on today's forming bar (``today``), not on completed bars; once
   the gap day has closed, the second chance is the Delayed HVC.
2. **Delayed High Volume Close (HVC)** — the second chance at an EP: enter
   as price breaks back through the gap-day closing price on any day after.
   Stop: low of the day the entry triggers.
3. **Flat Base Breakout** — a horizontal consolidation over multiple weeks,
   after a strong prior trend, with progressively smaller daily ranges.
   Entry: above the prior day's high, which also clears the base resistance.
   The playbook gives no stop for this one; the scanner uses the prior-day
   low when the breakout candle is tight, else the breakout-day low.
4. **Undercut and Rally (U&R)** — price dips below a major support level /
   swing low, then immediately reclaims it. Entry: on the reclaim of the
   prior low. Stop: the new swing low formed during the undercut.
5. **Moving Average Undercut and Rally (MA U&R)** — like U&R but against a
   key daily moving average (10/20/50-day): price moves below the average,
   then reclaims it with strength. Entry: as price rallies back through the
   average. Stop: low of the reclaim day.
6. **High Tight Flag** — after a sharp 50–100% run-up, price moves sideways
   in a tight range for 2–5 weeks, holding near the highs while volume
   contracts. Entry: a break through the top of the tight range. Stop: low of
   the breakout day.

Each setup is either *pending* (``triggered=False``: the level is set on
completed bars and today's session decides whether it breaks — see
``candles.apply_live_triggers``) or *triggered* on the last completed bar.

Defined risk: a setup whose stop is not below its entry is dropped. For a
triggered setup the entry is the trigger, or the breakout day's open when the
day gapped above it (you cannot buy below the open).

Thresholds: the playbook states the patterns in words, not numbers, so the
scanner thresholds below (gap size, volume multiples, base depth, run-up)
are the scanner's own concrete readings of those words, chosen to be
conservative and documented here — they are not claimed to be Ariel's.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional

import pandas as pd

from .candles import Setup

# The timeframe the setup decision is made on, and the one used only to time the entry.
SETUP_TF = "D"
ENTRY_TF = "15m"
ENTRY_BAR_MINUTES = 15

# General playbook rules.
RISK_PCT_MIN = 0.005
RISK_PCT_MAX = 0.01
PARTIAL_AFTER_DAYS = (3, 5)
TRAIL_MA_PERIODS = (10, 20)

# Scanner thresholds — the playbook's words, made concrete (see docstring).
EP_MIN_GAP_PCT = 0.02  # gap up of at least 2% over the prior close
EP_MIN_VOLUME_X = 1.5  # gap-day volume at least 1.5x the 20-day average (projected while the day is live)
EP_MIN_SESSION_FRACTION = 0.1  # judge live volume only once ~40 minutes of the session have traded
HVC_LOOKBACK_DAYS = 10  # an EP gap day counts for a delayed entry for this long
FLAT_BASE_MIN_BARS = 15  # consolidation length, in sessions (multiple weeks)
FLAT_BASE_MAX_DEPTH_PCT = 0.10  # base high to base low, % of the base high
FLAT_BASE_MA_SPREAD_PCT = 0.03  # 10/20-day averages within this of each other
FLAT_BASE_TIGHT_RANGE_PCT = 0.02  # a "tight" breakout candle: range <= 2% of price
FLAT_BASE_PRIOR_TREND_BARS = 40  # the prior trend is measured over the ~2 months before the base
FLAT_BASE_PRIOR_RUN_PCT = 0.20  # base low at least 20% above the low before the base
FLAT_BASE_RESISTANCE_PCT = 0.01  # the prior-day high is within 1% of the base high
UR_LOOKBACK_BARS = 20  # swing low is the lowest low of roughly the last month
MA_UR_PERIODS = (20, 50, 10)  # in the order they are tried
HTF_MIN_RUNUP_PCT = 0.50  # 50–100% run-up before the flag
HTF_RUN_MAX_BARS = 40  # ... within about 8 weeks ("a sharp run-up")
HTF_FLAG_MIN_BARS = 10  # flag lasts 2–5 weeks (10–25 sessions)
HTF_FLAG_MAX_BARS = 25
HTF_FLAG_MAX_DEPTH_PCT = 0.10  # flag holds near the highs

# Display points per setup kind. These order the setups for the trigger display
# only — the setups do not score (leadership does).
SETUP_POINTS = {
    "episodic-pivot": 23.0,
    "high-tight-flag": 22.0,
    "delayed-hvc": 21.0,
    "flat-base-breakout": 20.0,
    "undercut-rally": 18.0,
    "ma-undercut-rally": 18.0,
}

SETUP_KINDS = tuple(SETUP_POINTS)

SETUP_LABELS = {
    "episodic-pivot": "Episodic Pivot",
    "delayed-hvc": "Delayed High Volume Close",
    "flat-base-breakout": "Flat Base Breakout",
    "undercut-rally": "Undercut and Rally",
    "ma-undercut-rally": "Moving Average Undercut and Rally",
    "high-tight-flag": "High Tight Flag",
}


@dataclass(frozen=True)
class ArielSetup:
    """One RealSimpleAriel setup."""

    kind: str  # machine key, e.g. "episodic-pivot"
    label: str  # human label, e.g. "Episodic Pivot"
    trigger: float  # price to break to enter
    stop: Optional[float]  # defined-risk stop; None while it is set by the day the entry triggers
    triggered: bool  # True once the entry break already happened on a completed bar
    detail: str = ""
    entry_instruction: str = ""
    anchor_date: Optional[str] = None  # the daily bar the setup is anchored on (YYYY-MM-DD)
    entry: Optional[float] = None  # for a triggered setup: max(trigger, breakout-day open)

    def to_setup(self) -> Setup:
        """The scanner's shared ``Setup`` row (API shape unchanged)."""
        return Setup(self.kind, self.label, self.trigger, self.triggered, self.detail, stop=self.stop, entry_tf=ENTRY_TF)


def _sma(values: pd.Series, period: int) -> pd.Series:
    return values.rolling(period, min_periods=period).mean()


def _avg_volume(df: pd.DataFrame, end: int, lookback: int = 20) -> float:
    """Mean volume of the ``lookback`` bars ending before position ``end`` (exclusive)."""
    window = df["volume"].iloc[max(0, end - lookback) : end].dropna()
    return float(window.mean()) if len(window) else 0.0


def _volume_ok(df: pd.DataFrame, pos: int, multiple: float) -> bool:
    """Volume at ``pos`` is at least ``multiple``x its 20-day average (skipped when there is no volume data)."""
    avg = _avg_volume(df, pos)
    if avg <= 0:
        return True
    return float(df["volume"].iloc[pos]) >= multiple * avg


def _gap_pct(prev_close: float, open_: float) -> float:
    return (open_ - prev_close) / prev_close if prev_close > 0 else 0.0


def _date(df: pd.DataFrame, pos: int) -> Optional[str]:
    ts = df.index[pos]
    return str(ts.date()) if hasattr(ts, "date") else None


def _is_ep_gap_day(df: pd.DataFrame, pos: int) -> bool:
    """A completed gap day the playbook would call an Episodic Pivot: a large gap up on heavy volume, closing strong."""
    if pos < 1 or pos >= len(df):
        return False
    bar = df.iloc[pos]
    if _gap_pct(float(df["close"].iloc[pos - 1]), float(bar["open"])) < EP_MIN_GAP_PCT:
        return False
    if not _volume_ok(df, pos, EP_MIN_VOLUME_X):
        return False
    span = float(bar["high"] - bar["low"])
    if span <= 0 or float(bar["close"]) < float(bar["low"]) + 0.5 * span:
        return False
    return float(bar["close"]) > float(bar["open"])


def _entry(trigger: float, open_: float) -> float:
    return max(trigger, open_)


def detect_episodic_pivot(
    df: pd.DataFrame,
    today: Optional[Mapping[str, float]] = None,
    opening_high: Optional[float] = None,
    session_fraction: Optional[float] = None,
) -> Optional[ArielSetup]:
    """Today's forming bar gaps up on heavy volume: a pending Opening Range Break.

    ``df`` is completed daily bars (the last one is yesterday). ``today`` is the forming bar (open / high / low /
    close / volume so far); ``opening_high`` is the high of the first entry-chart bar once it has closed;
    ``session_fraction`` is how much of the regular session has passed (0–1), used to project today's volume.
    """
    if today is None or len(df) < 21:
        return None
    prev_close = float(df["close"].iloc[-1])
    open_ = float(today["open"])
    gap = _gap_pct(prev_close, open_)
    if gap < EP_MIN_GAP_PCT:
        return None
    avg = _avg_volume(df, len(df))
    vol = float(today.get("volume") or 0.0)
    vol_note = "volume not confirmed yet"
    if avg > 0 and vol > 0 and session_fraction is not None and session_fraction >= EP_MIN_SESSION_FRACTION:
        projected = vol / min(1.0, session_fraction)
        if projected < EP_MIN_VOLUME_X * avg:
            return None
        vol_note = f"{projected / avg:.1f}x projected volume"
    low = float(today["low"])
    if opening_high is None:
        trigger = float(today["high"])
        where = "opening range still forming (trigger is the high so far)"
    else:
        trigger = float(opening_high)
        where = "enter above the first 15-min bar high"
    if low >= trigger:
        return None
    return ArielSetup(
        kind="episodic-pivot",
        label=SETUP_LABELS["episodic-pivot"],
        trigger=trigger,
        stop=low,
        triggered=False,
        detail=f"gap +{gap * 100:.1f}% ({vol_note}); {where}; stop at the low of day",
        entry_instruction="Opening Range Break on the 15-min chart: enter above the high of the first 15-min bar; stop at the low of day",
    )


def detect_delayed_hvc(df: pd.DataFrame) -> Optional[ArielSetup]:
    """Break back through a recent EP gap day's close.

    Triggered when the last completed bar traded back above the close after the prior close was at or below it;
    pending when the last completed close is at or below it (today's session decides the break).
    """
    if len(df) < 22:
        return None
    last = len(df) - 1
    for j in range(last - 1, max(0, last - HVC_LOOKBACK_DAYS) - 1, -1):  # most recent gap day first
        if not _is_ep_gap_day(df, j):
            continue
        level = float(df["close"].iloc[j])
        bar = df.iloc[last]
        prev_close = float(df["close"].iloc[last - 1])
        gap_date = _date(df, j)
        # The day before the break must be after the gap day and have closed back at or below the level.
        if j <= last - 2 and prev_close <= level < float(bar["high"]):
            return ArielSetup(
                kind="delayed-hvc",
                label=SETUP_LABELS["delayed-hvc"],
                trigger=level,
                stop=float(bar["low"]),
                triggered=True,
                detail=f"broke back through the gap-day close {level:.2f} (gap day {gap_date}); stop at the entry-day low",
                entry_instruction="Enter on the break of the gap-day close; stop at the low of the entry day",
                anchor_date=gap_date,
                entry=_entry(level, float(bar["open"])),
            )
        if float(bar["close"]) <= level:
            return ArielSetup(
                kind="delayed-hvc",
                label=SETUP_LABELS["delayed-hvc"],
                trigger=level,
                stop=None,
                triggered=False,
                detail=f"below the gap-day close {level:.2f} (gap day {gap_date}); enter on the break back through it, stop at that day's low",
                entry_instruction="Enter on the break of the gap-day close; stop at the low of the entry day",
                anchor_date=gap_date,
            )
        return None  # the most recent gap day decides
    return None


def _flat_base(df: pd.DataFrame, end: int) -> Optional[tuple[float, float]]:
    """(base high, base low) when the ``FLAT_BASE_MIN_BARS`` bars ending before ``end`` are a valid flat base."""
    start = end - FLAT_BASE_MIN_BARS
    if start - FLAT_BASE_PRIOR_TREND_BARS < 0:
        return None
    base = df.iloc[start:end]
    base_high, base_low = float(base["high"].max()), float(base["low"].min())
    if base_high <= 0 or (base_high - base_low) / base_high > FLAT_BASE_MAX_DEPTH_PCT:
        return None
    # A strong prior trend into the base.
    prior_low = float(df["low"].iloc[start - FLAT_BASE_PRIOR_TREND_BARS : start].min())
    if prior_low <= 0 or base_low / prior_low - 1 < FLAT_BASE_PRIOR_RUN_PCT:
        return None
    # Progressively smaller daily ranges: the last third of the base is tighter than the first third.
    ranges = (base["high"] - base["low"]).to_numpy()
    third = len(ranges) // 3
    if ranges[-third:].mean() >= ranges[:third].mean():
        return None
    # The 10/20-day averages tighten up near the price at the end of the base.
    closes = df["close"].iloc[:end]
    ma10, ma20 = _sma(closes, 10).iloc[-1], _sma(closes, 20).iloc[-1]
    if pd.isna(ma10) or pd.isna(ma20) or abs(float(ma10) - float(ma20)) / float(ma20) > FLAT_BASE_MA_SPREAD_PCT:
        return None
    return base_high, base_low


def detect_flat_base_breakout(df: pd.DataFrame) -> Optional[ArielSetup]:
    """A flat base: pending above the last bar's high, or triggered when the last bar broke the prior day's high."""
    if len(df) < FLAT_BASE_MIN_BARS + FLAT_BASE_PRIOR_TREND_BARS:
        return None
    last = len(df) - 1
    bar = df.iloc[last]
    # Triggered: the base ends at the prior day, and the last bar traded above the prior day's high.
    found = _flat_base(df, last)
    if found is not None:
        base_high, _ = found
        prior_high = float(df["high"].iloc[last - 1])
        trigger = max(prior_high, base_high)
        if float(bar["high"]) > trigger:
            tight = (float(bar["high"]) - float(bar["low"])) <= FLAT_BASE_TIGHT_RANGE_PCT * float(bar["close"])
            stop = float(df["low"].iloc[last - 1]) if tight else float(bar["low"])
            return ArielSetup(
                kind="flat-base-breakout",
                label=SETUP_LABELS["flat-base-breakout"],
                trigger=trigger,
                stop=stop,
                triggered=True,
                detail=f"broke the {FLAT_BASE_MIN_BARS}-session flat base at {trigger:.2f}; stop at the {'prior-day' if tight else 'breakout-day'} low",
                entry_instruction="Enter above the prior day's high (the base resistance)",
                anchor_date=_date(df, last),
                entry=_entry(trigger, float(bar["open"])),
            )
    # Pending: the base runs through the last bar, whose high sits at the base resistance.
    found = _flat_base(df, last + 1)
    if found is None:
        return None
    base_high, _ = found
    if float(bar["high"]) < base_high * (1 - FLAT_BASE_RESISTANCE_PCT):
        return None
    return ArielSetup(
        kind="flat-base-breakout",
        label=SETUP_LABELS["flat-base-breakout"],
        trigger=base_high,
        stop=float(bar["low"]),
        triggered=False,
        detail=f"{FLAT_BASE_MIN_BARS}-session flat base; enter above {base_high:.2f} (prior-day high / base resistance)",
        entry_instruction="Enter above the prior day's high (the base resistance)",
        anchor_date=_date(df, last),
    )


def detect_undercut_rally(df: pd.DataFrame) -> Optional[ArielSetup]:
    """The last bar reclaims a swing low that it or the bar before undercut."""
    if len(df) < UR_LOOKBACK_BARS + 2:
        return None
    last = len(df) - 1
    window = df.iloc[last - UR_LOOKBACK_BARS - 1 : last - 1]
    level = float(window["low"].min())
    undercut_low = min(float(df["low"].iloc[last - 1]), float(df["low"].iloc[last]))
    if undercut_low >= level:
        return None  # no undercut of the swing low
    if float(df["close"].iloc[last]) <= level:
        return None  # not reclaimed yet
    if float(df["close"].iloc[last - 1]) > level:
        return None  # already reclaimed the day before; "immediately" means this bar
    bar = df.iloc[last]
    return ArielSetup(
        kind="undercut-rally",
        label=SETUP_LABELS["undercut-rally"],
        trigger=level,
        stop=undercut_low,
        triggered=True,
        detail=f"undercut the swing low {level:.2f} to {undercut_low:.2f}, then reclaimed it; stop at the undercut low",
        entry_instruction="Enter on the reclaim of the prior low; stop at the new swing low formed during the undercut",
        anchor_date=_date(df, last),
        entry=_entry(level, float(bar["open"])),
    )


def detect_ma_undercut_rally(df: pd.DataFrame) -> Optional[ArielSetup]:
    """The last bar reclaims, with strength, a key daily moving average it had closed below."""
    if len(df) < 55:
        return None
    last = len(df) - 1
    closes = df["close"]
    bar = df.iloc[last]
    span = float(bar["high"] - bar["low"])
    # "With strength": an up day closing in the upper half of its range.
    if span <= 0 or float(bar["close"]) <= float(bar["open"]) or float(bar["close"]) < float(bar["low"]) + 0.5 * span:
        return None
    for period in MA_UR_PERIODS:
        ma = _sma(closes, period)
        prev_ma, cur_ma = ma.iloc[last - 1], ma.iloc[last]
        if pd.isna(prev_ma) or pd.isna(cur_ma):
            continue
        if float(closes.iloc[last - 1]) >= float(prev_ma):
            continue  # was not below the average
        if float(closes.iloc[last]) <= float(cur_ma):
            continue  # has not reclaimed it
        if float(cur_ma) < float(prev_ma):
            continue  # the average itself is still falling
        return ArielSetup(
            kind="ma-undercut-rally",
            label=f"{SETUP_LABELS['ma-undercut-rally']} ({period}-day)",
            trigger=float(cur_ma),
            stop=float(bar["low"]),
            triggered=True,
            detail=f"reclaimed the {period}-day average at {float(cur_ma):.2f}; stop at the reclaim-day low",
            entry_instruction="Enter as price rallies back through the moving average; stop at the low of the reclaim day",
            anchor_date=_date(df, last),
            entry=_entry(float(cur_ma), float(bar["open"])),
        )
    return None


def _high_tight_flag(df: pd.DataFrame, end: int) -> Optional[tuple[int, float, float]]:
    """(flag length, flag high, run-up %) for a tight flag in the bars before ``end`` after a sharp run-up."""
    for flag_len in range(HTF_FLAG_MAX_BARS, HTF_FLAG_MIN_BARS - 1, -1):  # longest first
        flag_start = end - flag_len
        run_start = flag_start - HTF_RUN_MAX_BARS
        if run_start < 0:
            continue
        flag = df.iloc[flag_start:end]
        run = df.iloc[run_start:flag_start]
        # The run-up: from the lowest low of the run window to the highest high after it, within ~8 weeks.
        low_pos = int(run["low"].to_numpy().argmin())
        run_low = float(run["low"].iloc[low_pos])
        run_high = float(run["high"].iloc[low_pos:].max())
        if run_low <= 0 or run_high / run_low - 1 < HTF_MIN_RUNUP_PCT:
            continue
        flag_high, flag_low = float(flag["high"].max()), float(flag["low"].min())
        if flag_high <= 0 or (flag_high - flag_low) / flag_high > HTF_FLAG_MAX_DEPTH_PCT:
            continue
        if float(flag["close"].min()) < 0.90 * run_high:
            continue  # the flag gave back too much of the run
        run_vol = run["volume"].iloc[low_pos:].dropna()
        flag_vol = flag["volume"].dropna()
        if len(run_vol) and len(flag_vol) and float(flag_vol.mean()) >= float(run_vol.mean()):
            continue  # volume did not contract in the flag
        return flag_len, flag_high, (run_high / run_low - 1) * 100
    return None


def detect_high_tight_flag(df: pd.DataFrame) -> Optional[ArielSetup]:
    """A high tight flag: triggered when the last bar broke out of it, pending while the last bar is still in it."""
    if len(df) < HTF_RUN_MAX_BARS + HTF_FLAG_MIN_BARS + 1:
        return None
    last = len(df) - 1
    bar = df.iloc[last]
    found = _high_tight_flag(df, last)
    if found is not None:
        flag_len, flag_high, run_pct = found
        if float(bar["high"]) > flag_high:
            return ArielSetup(
                kind="high-tight-flag",
                label=SETUP_LABELS["high-tight-flag"],
                trigger=flag_high,
                stop=float(bar["low"]),
                triggered=True,
                detail=f"broke the {flag_len}-session tight flag at {flag_high:.2f} after a {run_pct:.0f}% run-up; stop at the breakout-day low",
                entry_instruction="Enter on the break through the top of the tight range; stop at the low of the breakout day",
                anchor_date=_date(df, last),
                entry=_entry(flag_high, float(bar["open"])),
            )
    found = _high_tight_flag(df, last + 1)
    if found is None:
        return None
    flag_len, flag_high, run_pct = found
    return ArielSetup(
        kind="high-tight-flag",
        label=SETUP_LABELS["high-tight-flag"],
        trigger=flag_high,
        stop=None,
        triggered=False,
        detail=f"{flag_len}-session tight flag after a {run_pct:.0f}% run-up; enter above {flag_high:.2f}, stop at the breakout-day low",
        entry_instruction="Enter on the break through the top of the tight range; stop at the low of the breakout day",
        anchor_date=_date(df, last),
    )


_DAILY_DETECTORS = (
    detect_delayed_hvc,
    detect_flat_base_breakout,
    detect_undercut_rally,
    detect_ma_undercut_rally,
    detect_high_tight_flag,
)


def has_defined_risk(setup: ArielSetup) -> bool:
    """The stop is below the entry (the trigger, or the breakout-day open when it gapped above). No stop yet is fine."""
    if setup.stop is None:
        return True
    entry = setup.entry if setup.entry is not None else setup.trigger
    return setup.stop < entry


def find_ariel_setups(
    df: pd.DataFrame,
    today: Optional[Mapping[str, float]] = None,
    opening_high: Optional[float] = None,
    session_fraction: Optional[float] = None,
) -> list[ArielSetup]:
    """Every RealSimpleAriel setup on completed daily bars ``df``, plus a live EP from ``today``'s forming bar."""
    if df is None or len(df) < 22:
        return []
    out: list[ArielSetup] = []
    try:
        ep = detect_episodic_pivot(df, today, opening_high, session_fraction)
    except (KeyError, TypeError, ValueError, IndexError):
        ep = None
    if ep is not None:
        out.append(ep)
    for detect in _DAILY_DETECTORS:
        try:
            found = detect(df)
        except (KeyError, TypeError, ValueError, IndexError):
            found = None
        if found is not None:
            out.append(found)
    return [s for s in out if has_defined_risk(s)]


def to_scored_setups(df: pd.DataFrame, **live) -> list[Setup]:
    """Ariel setups as the scanner's shared ``Setup`` rows, best points first."""
    setups = [s.to_setup() for s in find_ariel_setups(df, **live)]
    return sorted(setups, key=lambda s: SETUP_POINTS.get(s.kind, 0.0), reverse=True)
