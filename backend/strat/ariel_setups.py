"""Daily swing setups (the RealSimpleAriel "Real Simple" playbook) and their short mirrors.

THE RULES AND EVERY NUMBER ARE IN data/setups.yaml, in plain words. This module reads that file at import;
change a number there and detection changes with it. Keep the two in step when a rule changes.

Source playbook: https://www.tradezella.com/strategies/real-simple-strategy

Each setup is either *pending* (``triggered=False``: the level is set on completed bars and today's session
decides whether it breaks, see ``candles.apply_live_triggers``) or *triggered* on the last completed bar.
A setup whose stop is not below its entry (short: above) is dropped.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping, Optional

import pandas as pd
import yaml

from .candles import Setup

# Every rule's numbers live in data/setups.yaml (with the rules in plain words); this module reads them
# at import. Percent values there are percents; here they are fractions.
# STRAT_SETUPS_YAML points at another copy (tests use it to prove the file drives detection).
SETUPS_YAML = Path(os.environ.get("STRAT_SETUPS_YAML") or Path(__file__).resolve().parent.parent / "data" / "setups.yaml")


def load_config(path: Path = SETUPS_YAML) -> dict:
    with path.open() as fh:
        return yaml.safe_load(fh)


CONFIG = load_config()
_G, _EP, _HVC = CONFIG["general"], CONFIG["episodic_pivot"]["params"], CONFIG["delayed_hvc"]["params"]
_FB, _UR = CONFIG["flat_base"]["params"], CONFIG["undercut_rally"]["params"]
_MA, _HTF = CONFIG["ma_undercut_rally"]["params"], CONFIG["high_tight_flag"]["params"]

# The timeframe the setup decision is made on, and the one used only to time the entry.
SETUP_TF = "D"
ENTRY_BAR_MINUTES = int(_G["entry_chart_minutes"])
ENTRY_TF = f"{ENTRY_BAR_MINUTES}m"

# General playbook rules (shown, not enforced).
RISK_PCT_MIN = _G["risk_pct_min"] / 100
RISK_PCT_MAX = _G["risk_pct_max"] / 100
PARTIAL_AFTER_DAYS = tuple(_G["partial_profit_after_days"])
TRAIL_MA_PERIODS = tuple(_G["trail_ma_periods"])
MIN_HISTORY_DAYS = int(_G["min_history_days"])

# Episodic Pivot (live, today's bar).
EP_MIN_GAP_PCT = _EP["min_gap_pct"] / 100
EP_MIN_VOLUME_X = float(_EP["min_volume_x"])
EP_VOLUME_AVG_DAYS = int(_EP["volume_avg_days"])
EP_MIN_SESSION_FRACTION = _EP["min_session_pct"] / 100
# Delayed HVC: which completed day counts as the gap day, and for how long.
HVC_LOOKBACK_DAYS = int(_HVC["lookback_days"])
HVC_GAP_MIN_PCT = _HVC["gap_day_min_gap_pct"] / 100
HVC_GAP_MIN_VOLUME_X = float(_HVC["gap_day_min_volume_x"])
HVC_GAP_CLOSE_POSITION = _HVC["gap_day_close_position_pct"] / 100
HVC_MAX_BELOW_PCT = _HVC["max_below_pct"] / 100
# Flat base.
FLAT_BASE_MIN_BARS = int(_FB["base_days"])
FLAT_BASE_MAX_DEPTH_PCT = _FB["max_depth_pct"] / 100
FLAT_BASE_MA_SPREAD_PCT = _FB["ma_spread_pct"] / 100
FLAT_BASE_TIGHT_RANGE_PCT = _FB["tight_candle_pct"] / 100
FLAT_BASE_PRIOR_TREND_BARS = int(_FB["prior_trend_days"])
FLAT_BASE_PRIOR_RUN_PCT = _FB["prior_rise_pct"] / 100
FLAT_BASE_RESISTANCE_PCT = _FB["resistance_pct"] / 100
# Undercut and Rally.
UR_LOOKBACK_BARS = int(_UR["swing_lookback_days"])
# MA Undercut and Rally.
MA_UR_PERIODS = tuple(int(p) for p in _MA["ma_periods"])
MA_UR_CLOSE_POSITION = _MA["strong_close_position_pct"] / 100
MA_UR_MIN_HISTORY = int(_MA["min_history_days"])
# High Tight Flag.
HTF_MIN_RUNUP_PCT = _HTF["min_runup_pct"] / 100
HTF_RUN_MAX_BARS = int(_HTF["run_max_days"])
HTF_FLAG_MIN_BARS = int(_HTF["flag_min_days"])
HTF_FLAG_MAX_BARS = int(_HTF["flag_max_days"])
HTF_FLAG_MAX_DEPTH_PCT = _HTF["max_flag_depth_pct"] / 100
HTF_MAX_GIVEBACK = _HTF["max_giveback_pct"] / 100

# Display points per setup kind. These order the setups for the trigger display
# only — the setups do not score (leadership does).
# Section of data/setups.yaml for each setup kind.
_SECTION = {
    "episodic-pivot": "episodic_pivot",
    "delayed-hvc": "delayed_hvc",
    "flat-base-breakout": "flat_base",
    "undercut-rally": "undercut_rally",
    "ma-undercut-rally": "ma_undercut_rally",
    "high-tight-flag": "high_tight_flag",
}
SETUP_LABELS = {kind: str(CONFIG[sec]["name"]) for kind, sec in _SECTION.items()}


def overview() -> dict:
    """The Setups tab's header text and general rules from data/setups.yaml."""
    return {
        "how_it_works": [str(x) for x in CONFIG.get("how_it_works") or []],
        "short_setups": str(CONFIG.get("short_setups") or "").strip(),
        "general": dict(CONFIG.get("general") or {}),
    }


def describe() -> list[dict]:
    """Each setup as data/setups.yaml documents it (rules, entry, stop, numbers), for the UI's hover text."""
    out = []
    for kind, sec in _SECTION.items():
        c = CONFIG[sec]
        out.append({
            "kind": kind,
            "short_kind": _SHORT_KIND[kind],
            "name": str(c["name"]),
            "short_name": str(c["short_name"]),
            "rules": str(c.get("rules", "")).strip(),
            "entry": str(c.get("entry", "")).strip(),
            "stop": str(c.get("stop", "")).strip(),
            "params": dict(c.get("params") or {}),
        })
    return out

_RANK = CONFIG["display_rank"]
SETUP_POINTS = {
    "episodic-pivot": float(_RANK["episodic_pivot"]),
    "high-tight-flag": float(_RANK["high_tight_flag"]),
    "delayed-hvc": float(_RANK["delayed_hvc"]),
    "flat-base-breakout": float(_RANK["flat_base"]),
    "undercut-rally": float(_RANK["undercut_rally"]),
    "ma-undercut-rally": float(_RANK["ma_undercut_rally"]),
}

# Short-side mirrors of the six setups (not in the long-only playbook; the scanner's own reading, see
# ``find_short_setups``): long kind -> (short kind, label).
_SHORT_KIND = {
    "episodic-pivot": "gap-down-pivot",
    "delayed-hvc": "delayed-hvc-short",
    "flat-base-breakout": "flat-base-breakdown",
    "undercut-rally": "overcut-fail",
    "ma-undercut-rally": "ma-overcut-fail",
    "high-tight-flag": "low-tight-flag",
}
SHORT_MIRROR = {kind: (short, str(CONFIG[_SECTION[kind]]["short_name"])) for kind, short in _SHORT_KIND.items()}
SHORT_KINDS = tuple(k for k, _ in SHORT_MIRROR.values())
LONG_KINDS = tuple(SETUP_POINTS)
SETUP_POINTS.update({SHORT_MIRROR[k][0]: v for k, v in list(SETUP_POINTS.items())})

SETUP_KINDS = LONG_KINDS



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
    entry: Optional[float] = None  # for a triggered setup: max(trigger, breakout-day open) (short: min)
    side: str = "long"  # "short" for the mirrored setups: enter below the trigger, stop above

    def to_setup(self) -> Setup:
        """The scanner's shared ``Setup`` row."""
        return Setup(
            self.kind, self.label, self.trigger, self.triggered, self.detail, stop=self.stop, entry_tf=ENTRY_TF, side=self.side
        )


def _sma(values: pd.Series, period: int) -> pd.Series:
    return values.rolling(period, min_periods=period).mean()


def _avg_volume(df: pd.DataFrame, end: int, lookback: int = EP_VOLUME_AVG_DAYS) -> float:
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
    if _gap_pct(float(df["close"].iloc[pos - 1]), float(bar["open"])) < HVC_GAP_MIN_PCT:
        return False
    if not _volume_ok(df, pos, HVC_GAP_MIN_VOLUME_X):
        return False
    span = float(bar["high"] - bar["low"])
    if span <= 0 or float(bar["close"]) < float(bar["low"]) + HVC_GAP_CLOSE_POSITION * span:
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
    if today is None or len(df) < MIN_HISTORY_DAYS:
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
    pending when the last completed close is at or below it (today's session decides the break). Either way the
    close before the break stays within ``HVC_MAX_BELOW_PCT`` of the level, and no close since the gap day went
    below the gap day's low (the gap failed).
    """
    if len(df) < MIN_HISTORY_DAYS:
        return None
    last = len(df) - 1
    for j in range(last - 1, max(0, last - HVC_LOOKBACK_DAYS) - 1, -1):  # most recent gap day first
        if not _is_ep_gap_day(df, j):
            continue
        level = float(df["close"].iloc[j])
        floor = level * (1 - HVC_MAX_BELOW_PCT)
        gap_low = float(df["low"].iloc[j])
        bar = df.iloc[last]
        prev_close = float(df["close"].iloc[last - 1])
        gap_date = _date(df, j)
        # The day before the break must be after the gap day and have closed back at or below the level, but near it,
        # with no close under the gap day's low since the gap.
        if (
            j <= last - 2
            and floor <= prev_close <= level < float(bar["high"])
            and float(df["close"].iloc[j + 1 : last].min()) >= gap_low
        ):
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
        if floor <= float(bar["close"]) <= level and float(df["close"].iloc[j + 1 : last + 1].min()) >= gap_low:
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
    if len(df) < MA_UR_MIN_HISTORY:
        return None
    last = len(df) - 1
    closes = df["close"]
    bar = df.iloc[last]
    span = float(bar["high"] - bar["low"])
    # "With strength": an up day closing in the upper half of its range.
    if span <= 0 or float(bar["close"]) <= float(bar["open"]) or float(bar["close"]) < float(bar["low"]) + MA_UR_CLOSE_POSITION * span:
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
        if float(flag["close"].min()) < (1 - HTF_MAX_GIVEBACK) * run_high:
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
    if df is None or len(df) < MIN_HISTORY_DAYS:
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


# --- short side -------------------------------------------------------------------------------------------------
#
# Each short setup is its long setup on the price chart turned upside down: every price p becomes 1/p (high and
# low swap), so a gap down reads as a gap up, a 33% decline as a 50% run-up, a bounce into resistance as a dip
# to support. The long detectors then run unchanged and their levels are mapped back (1/level). Percent rules
# (gap size, base depth, range tightness) carry over exactly; moving averages differ slightly (the average of
# 1/p is not 1/average of p), so the MA trigger is re-read from the real chart. Volume is not inverted.

def _drop_pct(rise: float) -> str:
    """A rise of ``rise`` on the upside-down chart, as the drop it is on the real chart (20% -> 17%)."""
    return f"{(1 - 1 / (1 + rise)) * 100:.0f}%"


_SHORT_TEXT = {
    "gap-down-pivot": (
        "large gap down on heavy volume; enter below the first 15-min bar low, stop at the high of day",
        "Opening Range Break down on the 15-min chart: enter below the low of the first 15-min bar; stop at the high of day",
    ),
    "delayed-hvc-short": (
        "second chance at a gap-down day: enter as price breaks back below its close, stop at the entry-day high",
        "Enter on the break back below the gap-down day's close; stop at the high of the entry day",
    ),
    "flat-base-breakdown": (
        f"tight multi-week base after a {_drop_pct(FLAT_BASE_PRIOR_RUN_PCT)}+ decline; enter below the prior day's low",
        "Enter below the prior day's low (the base support)",
    ),
    "overcut-fail": (
        "popped above the swing high, then closed back below it; stop at the new high",
        "Enter on the failure back below the prior high; stop at the high made during the overcut",
    ),
    "ma-overcut-fail": (
        "closed above a falling daily average, then was rejected back below it on a weak day; stop at the rejection-day high",
        "Enter as price breaks back below the moving average; stop at the high of the rejection day",
    ),
    "low-tight-flag": (
        f"a {_drop_pct(HTF_MIN_RUNUP_PCT)}+ drop within ~{HTF_RUN_MAX_BARS // 5} weeks, then a tight "
        f"{HTF_FLAG_MIN_BARS // 5}-{HTF_FLAG_MAX_BARS // 5} week bounce on lighter volume; enter below the flag low",
        "Enter on the break below the bottom of the flag; stop at the high of the breakdown day",
    ),
}


def _invert_bars(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    out["open"] = 1.0 / df["open"]
    out["high"] = 1.0 / df["low"]
    out["low"] = 1.0 / df["high"]
    out["close"] = 1.0 / df["close"]
    out["volume"] = df["volume"]
    return out


def _inv(v: Optional[float]) -> Optional[float]:
    return None if v is None or v <= 0 else 1.0 / v


def _to_short(s: ArielSetup, df: pd.DataFrame) -> ArielSetup:
    kind, label = SHORT_MIRROR[s.kind]
    trigger = 1.0 / s.trigger
    if kind == "ma-overcut-fail":
        period = int(s.label.rsplit("(", 1)[1].split("-")[0])
        real = df["close"].rolling(period, min_periods=period).mean().iloc[-1]
        trigger = float(real) if pd.notna(real) else trigger
        label = f"{label} ({period}-day)"
    stop = _inv(s.stop)
    detail, instruction = _SHORT_TEXT[kind]
    if s.triggered:
        detail = f"broke below {trigger:.2f}; {detail}"
    elif kind == "gap-down-pivot" and "still forming" in s.detail:
        detail = f"{detail} (opening range still forming: trigger is the low so far)"
    return replace(
        s, kind=kind, label=label, trigger=trigger, stop=stop, detail=detail, entry_instruction=instruction,
        entry=_inv(s.entry), side="short",
    )


def find_short_setups(
    df: pd.DataFrame,
    today: Optional[Mapping[str, float]] = None,
    opening_low: Optional[float] = None,
    session_fraction: Optional[float] = None,
) -> list[ArielSetup]:
    """Short mirrors of the six setups on completed daily bars ``df`` (plus a live gap-down pivot from ``today``).

    Stops sit above the entry; a setup whose stop is not above its entry is dropped (checked on the inverted
    chart, where it is the long rule).
    """
    if df is None or len(df) < MIN_HISTORY_DAYS:
        return []
    try:
        inv_today = None if today is None else {
            "open": 1.0 / float(today["open"]), "high": 1.0 / float(today["low"]), "low": 1.0 / float(today["high"]),
            "close": 1.0 / float(today["close"]), "volume": float(today.get("volume") or 0.0),
        }
        found = find_ariel_setups(_invert_bars(df), inv_today, _inv(opening_low), session_fraction)
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return []
    return [_to_short(s, df) for s in found]


def to_scored_setups(df: pd.DataFrame, **live) -> list[Setup]:
    """Ariel setups as the scanner's shared ``Setup`` rows, best points first."""
    setups = [s.to_setup() for s in find_ariel_setups(df, **live)]
    return sorted(setups, key=lambda s: SETUP_POINTS.get(s.kind, 0.0), reverse=True)
