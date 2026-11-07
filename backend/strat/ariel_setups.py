"""RealSimpleAriel swing setups (the "Real Simple" playbook), replacing The Strat setups.

Source: https://www.tradezella.com/strategies/real-simple-strategy
(also https://www.chartfanatics.com/strategies/real-simple-strategy)

The playbook is a repeatable swing system built around institutional buying,
sector strength and clean technical structure. The setup decision is always
made on the **daily** chart; the entry chart is only for timing the entry
(the playbook uses 5-minute bars — this scanner uses **15-minute** bars,
per the owner's request — see ``ENTRY_TF``).

The six setups, in the order they are checked:

1. **Episodic Pivot (EP)** — a large gap up, typically on earnings or news,
   with volume significantly above the average daily volume. Entry is an
   Opening Range Break on the entry chart, above the high of the first
   entry bar. Stop: low of the gap day.
2. **Delayed High Volume Close (HVC)** — the second chance at an EP: draw a
   line at the gap-day closing price and enter as price breaks back through
   that close on any day after, with no daily-close confirmation. Stop: low
   of the entry day.
3. **Flat Base Breakout** — a horizontal consolidation over multiple weeks
   after a strong prior trend, with the 10/20-day averages tightening near
   price and progressively smaller daily ranges. Entry: above the prior
   day's high, clearing the flat-base resistance. Stop: the prior day's low
   when the breakout candle is tight, otherwise the low of the breakout day.
4. **Undercut and Rally (U&R)** — price dips below a major support level /
   swing low, shakes out weak holders, then immediately reclaims it. Entry:
   on the reclaim of the prior low. Stop: the new swing low formed during
   the undercut.
5. **Moving Average Undercut and Rally (MA U&R)** — like U&R but against a
   key daily moving average (10/20/50-day): price moves below the average,
   then reclaims it with strength, ideally on increased volume. Entry: as
   price rallies back through the average. Stop: low of the reclaim day.
6. **High Tight Flag** — after a 50–100% run-up in a short period, price
   moves sideways in a tight range for 2–5 weeks, holding near the highs
   while volume contracts. Entry: a break through the upper half of the
   tight range. Stop: low of the breakout day.

General rules from the playbook, also applied here:

* Only take a setup when the market and the stock's group/sector support
  the direction (the scanner already gates on leadership / theme strength
  and trend; a setup on its own never scores).
* Defined risk on every setup (each setup below carries its stop).
* Typical risk is 0.5% to 1% of equity per trade (``RISK_PCT_MIN`` /
  ``RISK_PCT_MAX``).
* Take partial profits into strength, especially after 3–5 strong days,
  and trail the remainder with the rising 10/20-day average
  (``PARTIAL_AFTER_DAYS``, ``TRAIL_MA_PERIODS``).

Thresholds: the playbook states the patterns in words, not numbers, so the
scanner thresholds below (gap size, volume multiples, base depth, run-up)
are the scanner's own concrete readings of those words, chosen to be
conservative and documented here — they are not claimed to be Ariel's.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from .candles import Setup

# The timeframe the setup decision is made on, and the one used only to time the entry.
SETUP_TF = "D"
ENTRY_TF = "15m"
ENTRY_BAR_MINUTES = 15

# General playbook rules (see the module docstring).
RISK_PCT_MIN = 0.005
RISK_PCT_MAX = 0.01
PARTIAL_AFTER_DAYS = (3, 5)
TRAIL_MA_PERIODS = (10, 20)

# Scanner thresholds — the playbook's words, made concrete (see docstring).
EP_MIN_GAP_PCT = 0.02  # gap up of at least 2% over the prior close
EP_MIN_VOLUME_X = 1.5  # gap-day volume at least 1.5x the 20-day average
HVC_LOOKBACK_DAYS = 10  # an EP gap day counts for a delayed entry for this long
FLAT_BASE_MIN_BARS = 15  # consolidation length, in sessions (multiple weeks)
FLAT_BASE_MAX_DEPTH_PCT = 0.10  # base high to base low, % of the base high
FLAT_BASE_MA_SPREAD_PCT = 0.03  # 10/20-day averages within this of each other
FLAT_BASE_TIGHT_RANGE_PCT = 0.02  # a "tight" breakout candle: range <= 2% of price
UR_LOOKBACK_BARS = 20  # swing low is the lowest low of roughly the last month
MA_UR_PERIODS = (20, 50, 10)  # in the order they are tried
HTF_MIN_RUNUP_PCT = 0.50  # 50–100% run-up before the flag
HTF_FLAG_MIN_BARS = 10  # flag lasts 2–5 weeks (10–25 sessions)
HTF_FLAG_MAX_BARS = 25
HTF_FLAG_MAX_DEPTH_PCT = 0.10  # flag holds near the highs

# Display/scoring points per setup kind. These order the setups for the
# trigger display only — the setups do not score (leadership does). Pending
# (not yet triggered) setups rank first, like the old Strat points did.
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
    """One RealSimpleAriel setup detected on completed daily bars."""

    kind: str  # machine key, e.g. "episodic-pivot"
    label: str  # human label, e.g. "Episodic Pivot"
    trigger: float  # price to break to enter (daily level; the 15m ORB refines it)
    stop: float  # defined-risk stop from the playbook
    triggered: bool  # True once the entry break already happened on a completed bar
    detail: str = ""
    # Entry instruction for the 15-minute chart (the playbook's 5-minute ORB, on 15m bars).
    entry_instruction: str = ""
    # The daily bar the setup is anchored on (its date, YYYY-MM-DD), when known.
    anchor_date: Optional[str] = None

    def to_setup(self) -> Setup:
        """The scanner's shared ``Setup`` row (API shape unchanged)."""
        return Setup(
            self.kind,
            self.label,
            self.trigger,
            self.triggered,
            self.detail,
            stop=self.stop,
            entry_tf=ENTRY_TF,
        )


def _sma(values: pd.Series, period: int) -> pd.Series:
    return values.rolling(period, min_periods=period).mean()


def _avg_volume(df: pd.DataFrame, end: int, lookback: int = 20) -> float:
    """Mean volume of the ``lookback`` bars ending before position ``end`` (exclusive)."""
    window = df["volume"].iloc[max(0, end - lookback) : end]
    return float(window.mean()) if len(window) else 0.0


def _volume_ok(df: pd.DataFrame, pos: int, multiple: float) -> bool:
    """Volume at ``pos`` is at least ``multiple``x its 20-day average, or the check is skipped when there is no volume data."""
    avg = _avg_volume(df, pos)
    if avg <= 0:
        return True
    return float(df["volume"].iloc[pos]) >= multiple * avg


def _gap_pct(df: pd.DataFrame, pos: int) -> float:
    """(open - prior close) / prior close at ``pos``."""
    prev_close = float(df["close"].iloc[pos - 1])
    return (float(df["open"].iloc[pos]) - prev_close) / prev_close if prev_close > 0 else 0.0


def _is_ep_gap_day(df: pd.DataFrame, pos: int) -> bool:
    """A gap day the playbook would call an Episodic Pivot: a large gap up on heavy volume, closing in the upper half."""
    if pos < 1 or pos >= len(df):
        return False
    if _gap_pct(df, pos) < EP_MIN_GAP_PCT:
        return False
    if not _volume_ok(df, pos, EP_MIN_VOLUME_X):
        return False
    bar = df.iloc[pos]
    span = float(bar["high"] - bar["low"])
    if span <= 0:
        return False
    if float(bar["close"]) < float(bar["low"]) + 0.5 * span:
        return False
    return float(bar["close"]) > float(bar["open"])


def detect_episodic_pivot(df: pd.DataFrame) -> Optional[ArielSetup]:
    """The last completed bar is an EP gap day."""
    if len(df) < 22:
        return None
    pos = len(df) - 1
    if not _is_ep_gap_day(df, pos):
        return None
    bar = df.iloc[pos]
    gap = _gap_pct(df, pos) * 100
    vol_x = float(bar["volume"]) / _avg_volume(df, pos) if _avg_volume(df, pos) > 0 else 0.0
    return ArielSetup(
        kind="episodic-pivot",
        label=SETUP_LABELS["episodic-pivot"],
        trigger=float(bar["high"]),
        stop=float(bar["low"]),
        triggered=False,
        detail=f"gap +{gap:.1f}% on {vol_x:.1f}x volume; enter above the first 15-min bar high, stop at the gap-day low",
        entry_instruction="Opening Range Break on the 15-min chart: enter above the high of the first 15-min bar; stop at the gap-day low",
        anchor_date=str(df.index[pos].date()) if hasattr(df.index[pos], "date") else None,
    )


def detect_delayed_hvc(df: pd.DataFrame) -> Optional[ArielSetup]:
    """The last bar breaks back through an EP gap day's close from the last ``HVC_LOOKBACK_DAYS`` sessions."""
    if len(df) < 22:
        return None
    last = len(df) - 1
    for j in range(max(1, last - HVC_LOOKBACK_DAYS), last):
        if not _is_ep_gap_day(df, j):
            continue
        level = float(df["close"].iloc[j])
        if float(df["close"].iloc[last - 1]) <= level < float(df["close"].iloc[last]):
            bar = df.iloc[last]
            return ArielSetup(
                kind="delayed-hvc",
                label=SETUP_LABELS["delayed-hvc"],
                trigger=level,
                stop=float(bar["low"]),
                triggered=True,
                detail=f"broke back through the gap-day close {level:.2f} (gap day {df.index[j].date()}); stop at the entry-day low",
                entry_instruction="Already broken on the daily close — enter on the break; stop at the entry-day low",
                anchor_date=str(df.index[j].date()) if hasattr(df.index[j], "date") else None,
            )
    return None


def detect_flat_base_breakout(df: pd.DataFrame) -> Optional[ArielSetup]:
    """The last bar breaks out of a tight multi-week flat base."""
    if len(df) < FLAT_BASE_MIN_BARS + 6:
        return None
    last = len(df) - 1
    base = df.iloc[last - FLAT_BASE_MIN_BARS : last]
    base_high = float(base["high"].max())
    base_low = float(base["low"].min())
    if base_high <= 0 or (base_high - base_low) / base_high > FLAT_BASE_MAX_DEPTH_PCT:
        return None
    # The 10/20-day averages tighten up near the price at the end of the base.
    closes = df["close"]
    ma10 = _sma(closes, 10).iloc[last - 1]
    ma20 = _sma(closes, 20).iloc[last - 1]
    if pd.isna(ma10) or pd.isna(ma20) or abs(float(ma10) - float(ma20)) / float(ma20) > FLAT_BASE_MA_SPREAD_PCT:
        return None
    bar = df.iloc[last]
    if float(bar["close"]) <= base_high:
        return None
    tight = (float(bar["high"]) - float(bar["low"])) <= FLAT_BASE_TIGHT_RANGE_PCT * float(bar["close"])
    stop = float(df["low"].iloc[last - 1]) if tight else float(bar["low"])
    return ArielSetup(
        kind="flat-base-breakout",
        label=SETUP_LABELS["flat-base-breakout"],
        trigger=base_high,
        stop=stop,
        triggered=True,
        detail=(
            f"broke the {FLAT_BASE_MIN_BARS}-session flat base at {base_high:.2f}; "
            f"stop at the {'prior-day' if tight else 'breakout-day'} low"
        ),
        entry_instruction="Enter above the prior day's high (the base resistance); stop at the prior-day low when the breakout candle is tight, else the breakout-day low",
        anchor_date=str(df.index[last].date()) if hasattr(df.index[last], "date") else None,
    )


def detect_undercut_rally(df: pd.DataFrame) -> Optional[ArielSetup]:
    """The last bar reclaims a swing low that an earlier bar undercut."""
    if len(df) < UR_LOOKBACK_BARS + 2:
        return None
    last = len(df) - 1
    # The swing low is the lowest low of the window before the last two bars.
    window = df.iloc[last - UR_LOOKBACK_BARS - 1 : last - 1]
    level = float(window["low"].min())
    undercut_low = min(float(df["low"].iloc[last - 1]), float(df["low"].iloc[last]))
    if undercut_low >= level:
        return None  # no undercut of the swing low
    if float(df["close"].iloc[last]) <= level:
        return None  # not reclaimed yet
    return ArielSetup(
        kind="undercut-rally",
        label=SETUP_LABELS["undercut-rally"],
        trigger=level,
        stop=undercut_low,
        triggered=True,
        detail=f"undercut the swing low {level:.2f} to {undercut_low:.2f}, then reclaimed it; stop at the undercut low",
        entry_instruction="Enter on the reclaim of the prior low; stop at the new swing low formed during the undercut",
        anchor_date=str(df.index[last].date()) if hasattr(df.index[last], "date") else None,
    )


def detect_ma_undercut_rally(df: pd.DataFrame) -> Optional[ArielSetup]:
    """The last bar reclaims a key daily moving average it had dipped below."""
    if len(df) < 55:
        return None
    last = len(df) - 1
    closes = df["close"]
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
        bar = df.iloc[last]
        return ArielSetup(
            kind="ma-undercut-rally",
            label=f"{SETUP_LABELS['ma-undercut-rally']} ({period}-day)",
            trigger=float(cur_ma),
            stop=float(bar["low"]),
            triggered=True,
            detail=f"reclaimed the {period}-day average at {float(cur_ma):.2f}; stop at the reclaim-day low",
            entry_instruction="Enter as price rallies back through the moving average; stop at the low of the reclaim day",
            anchor_date=str(df.index[last].date()) if hasattr(df.index[last], "date") else None,
        )
    return None


def detect_high_tight_flag(df: pd.DataFrame) -> Optional[ArielSetup]:
    """The last bar breaks out of a tight flag after a 50–100% run-up."""
    if len(df) < 31:  # at least a 20-bar run, a 10-bar flag and the breakout bar
        return None
    last = len(df) - 1
    # The flag is the window before the breakout bar; try 2–5 weeks (10–25 sessions), longest first.
    for flag_len in range(HTF_FLAG_MAX_BARS, HTF_FLAG_MIN_BARS - 1, -1):
        flag = df.iloc[last - flag_len : last]
        run = df.iloc[: last - flag_len]
        if len(run) < 20:
            continue
        run_start_close = float(run["close"].iloc[0])
        run_high = float(run["high"].max())
        if run_start_close <= 0 or (run_high / run_start_close - 1) < HTF_MIN_RUNUP_PCT:
            continue
        flag_high = float(flag["high"].max())
        flag_low = float(flag["low"].min())
        if flag_high <= 0 or (flag_high - flag_low) / flag_high > HTF_FLAG_MAX_DEPTH_PCT:
            continue
        if float(flag["close"].min()) < 0.90 * run_high:
            continue  # the flag gave back too much of the run
        if _avg_volume(df, last - flag_len) > 0 and float(flag["volume"].mean()) >= float(run["volume"].mean()):
            continue  # volume did not contract in the flag
        bar = df.iloc[last]
        if float(bar["close"]) <= flag_high:
            continue
        return ArielSetup(
            kind="high-tight-flag",
            label=SETUP_LABELS["high-tight-flag"],
            trigger=flag_high,
            stop=float(bar["low"]),
            triggered=True,
            detail=f"broke the {flag_len}-session tight flag at {flag_high:.2f} after a {(run_high / run_start_close - 1) * 100:.0f}% run-up; stop at the breakout-day low",
            entry_instruction="Enter on the break through the upper half of the tight range; stop at the low of the breakout day",
            anchor_date=str(df.index[last].date()) if hasattr(df.index[last], "date") else None,
        )
    return None


_DETECTORS = (
    detect_episodic_pivot,
    detect_delayed_hvc,
    detect_flat_base_breakout,
    detect_undercut_rally,
    detect_ma_undercut_rally,
    detect_high_tight_flag,
)


def find_ariel_setups(df: pd.DataFrame) -> list[ArielSetup]:
    """Every RealSimpleAriel setup on the last completed daily bar of ``df`` (pass completed bars only)."""
    if df is None or len(df) < 22:
        return []
    out: list[ArielSetup] = []
    for detect in _DETECTORS:
        try:
            found = detect(df)
        except (KeyError, TypeError, ValueError, IndexError):
            found = None
        if found is not None:
            out.append(found)
    return out


def to_scored_setups(df: pd.DataFrame) -> list[Setup]:
    """Ariel setups as the scanner's shared ``Setup`` rows, best points first."""
    setups = [s.to_setup() for s in find_ariel_setups(df)]
    return sorted(setups, key=lambda s: SETUP_POINTS.get(s.kind, 0.0), reverse=True)
