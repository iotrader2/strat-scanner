"""Rank-quality backtest of the Stock Scanner score.

    python -m strat.backtest                          # biweekly cut-offs over the whole cache, markdown on stdout
    python -m strat.backtest --dates 2026-08-13 ...   # chosen cut-off dates
    python -m strat.backtest --timeline               # weekly rank/status of the reference leaders (breakdown check)

The objective is that the highest scores go to the stocks that go up the most. For each cut-off date only bars up to
that date are used (prices, returns, averages, themes and relative-strength percentiles are all recomputed from that
history), then the list is measured against what happened next:

* forward 1M and 3M return of the top 1 / 5 / 10 of the list, minus the median liquid stock;
* Spearman rank correlation between score and forward 3M return inside the list;
* capture: how many of the eventual 10 best forward-3M performers were in the list's top 10 / top 30, and how many
  sessions after the start of their run each first reached the top 10;
* the rank of the reference leaders (SNDK on every date) and the Recent breakouts study.

Dates before ``TEST_START`` are the train period (where the weights were tuned), the rest is the test period. The
universe is today's S&P 500 + Nasdaq-100 list (survivorship bias: names that left the indexes are missing), filtered to
liquid stocks (price and average dollar volume at the cut-off date). The old list is names with a weekly setup, ranked
by the old Strat-first score; the new list is the leaders-only list (RS >= P90, trend unbroken) ranked by the new score.
"""

from __future__ import annotations

import argparse
import statistics
import sys
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from . import config, data
from .members import effective_universe
from .scanner import LEADERS, LEGACY, ScanResult, scan_all
from .themes import ThemeMap, load_themes
from .universe import load_universe

REFERENCE = ("SNDK", "MU", "NBIS", "AMD", "DELL", "HPE", "ARM", "PLTR")

RANK_START = "2024-05-10"  # first Friday with 6 months of cached history behind it
RANK_FREQ = "2W-FRI"
TEST_START = "2025-10-01"
SNDK_RUN_START = "2025-11-01"
RUN_START, RUN_END = "2026-04-24", "2026-09-11"  # the reference names led the market in this window

TOP_SIZES = (1, 5, 10)
CAPTURE_SIZES = (10, 30)
CAPTURE_TOP = 10  # "eventual best performers" = the 10 best forward-3M returns
RUN_GAP_STEPS = 3  # a name's runs are separate when it was out of the top 10 for this many dates
MIN_SPEARMAN_NAMES = 8
BECAME_LEADER_STEPS = (2, 3, 4)  # 4 to 8 weeks later on biweekly dates

FORWARD_MONTHS = 1
END_TOLERANCE_DAYS = 5

def cut_off(daily_by_symbol: Mapping[str, pd.DataFrame], as_of: pd.Timestamp) -> dict[str, pd.DataFrame]:
    """Every symbol's bars up to and including ``as_of`` (symbols with no bars yet are dropped)."""
    out = {}
    for sym, df in daily_by_symbol.items():
        sub = df.loc[:as_of]
        if len(sub):
            out[sym] = sub
    return out


def forward_return(
    daily: pd.DataFrame,
    as_of: pd.Timestamp,
    months: int = FORWARD_MONTHS,
    splits: Sequence[tuple] = (),
) -> Optional[float]:
    """Percent return from the last close on or before ``as_of`` to the last close on or before one month later.

    None when the history does not run to the end of that window (or the symbol had no bars at ``as_of``).
    """
    close = daily["close"].dropna()
    end = as_of + pd.DateOffset(months=months)
    if close.empty or close.index[0] > as_of or close.index[-1] < end - pd.Timedelta(days=END_TOLERANCE_DAYS):
        return None
    base = float(close[:as_of].iloc[-1])
    final = float(close[:end].iloc[-1])
    # A split inside the forward window would otherwise look like a crash. Adjust the base only
    # for splits that happen after the cut-off, so the cut-off price itself stays as it was then.
    factor = 1.0
    for ex_date, ratio in splits:
        ex = pd.Timestamp(ex_date)
        if as_of < ex <= end and ratio:
            factor *= float(ratio)
    if factor and factor != 1.0:
        base = base / factor
    return (final / base - 1.0) * 100.0 if base > 0 else None


def liquid_stocks(rows: Sequence[dict]) -> list[dict]:
    return [
        r for r in rows
        if r["kind"] == "stock" and r["price"] >= config.MIN_PRICE and r["avg_dollar_volume"] >= config.MIN_DOLLAR_VOLUME
    ]


def old_list(result: ScanResult, mw_green: bool = False) -> list[dict]:
    """What the old scanner showed: liquid stocks with a weekly setup, best old score first."""
    rows = [r for r in liquid_stocks(result.rows) if r["has_setup"] and (r["mw_green"] or not mw_green)]
    return sorted(rows, key=lambda r: (-r["score"], r["symbol"]))


def new_list(result: ScanResult, mw_green: bool = False, setup: bool = False) -> list[dict]:
    """What the new scanner shows by default: liquid stock leaders, best new score first."""
    rows = [
        r for r in liquid_stocks(result.rows)
        if r["is_leader"] and (r["mw_green"] or not mw_green) and (r["has_setup"] or not setup)
    ]
    return sorted(rows, key=lambda r: (-r["score"], r["symbol"]))




# --------------------------------------------------------------------------------------------------------------------
# Collecting one scan per cut-off date
# --------------------------------------------------------------------------------------------------------------------


def rank_dates(daily_by_symbol: Mapping[str, pd.DataFrame], start: str = RANK_START, freq: str = RANK_FREQ) -> list[str]:
    """Biweekly cut-off dates from ``start`` to the last cached bar."""
    last_bar = max(df.index[-1] for df in daily_by_symbol.values())
    return [d.strftime("%Y-%m-%d") for d in pd.date_range(start, last_bar, freq=freq)]


def slim_row(row: dict, daily: pd.DataFrame, ts: pd.Timestamp, listed: bool, splits: Sequence[tuple] = ()) -> dict:
    """The fields of a scan row the rank-quality metrics need, plus its forward 1M and 3M return."""
    return {
        "symbol": row["symbol"],
        "score": row["score"],
        "rs": row.get("rs"),
        "status": row.get("leader_status", "n/a"),
        "has_setup": row["has_setup"],
        "listed": listed,
        "breakout": row.get("breakout"),
        "failed": row.get("failed_breakout"),
        "fwd1": forward_return(daily, ts, splits=splits),
        "fwd3": forward_return(daily, ts, months=3, splits=splits),
    }


def _as_of_frames(daily_by_symbol: Mapping[str, pd.DataFrame], as_of: pd.Timestamp, splits: Optional[Mapping] = None):
    """Bars up to ``as_of``, split-adjusted only by splits that had already happened."""
    from .adjust import apply_splits

    sliced = cut_off(daily_by_symbol, as_of)
    if not splits:
        return sliced
    return {sym: apply_splits(df, splits.get(sym, ()), as_of) for sym, df in sliced.items()}


def collect(
    daily_by_symbol: Mapping[str, pd.DataFrame],
    members,
    themes: Optional[ThemeMap],
    dates: Sequence[str],
    method: str = LEADERS,
    progress: bool = False,
    splits: Optional[Mapping] = None,
) -> dict[str, list[dict]]:
    """Scan the market as of every date: liquid stocks with their score, status and what they did next.

    ``listed`` marks what the scanner shows by default: the leaders list for the new score, names with a weekly setup
    for the old one.
    """
    out: dict[str, list[dict]] = {}
    for d in dates:
        if progress:
            print(f"[backtest] {method} {d}", file=sys.stderr, flush=True)
        ts = pd.Timestamp(d)
        result = scan_all(members, _as_of_frames(daily_by_symbol, ts, splits), themes, method=method, changes=False)
        out[d] = [
            slim_row(
                r,
                daily_by_symbol[r["symbol"]],
                ts,
                bool(r["has_setup"] if method == LEGACY else r["is_leader"]),
                splits.get(r["symbol"], ()) if splits else (),
            )
            for r in liquid_stocks(result.rows)
        ]
    return out


# --------------------------------------------------------------------------------------------------------------------
# Rank quality
# --------------------------------------------------------------------------------------------------------------------


def spearman(scores: Sequence[float], forward: Sequence[float]) -> Optional[float]:
    """Spearman rank correlation (None with too few names or no variation)."""
    if len(scores) < MIN_SPEARMAN_NAMES:
        return None
    corr = pd.Series(scores).rank().corr(pd.Series(forward).rank())
    return None if corr != corr else float(corr)


@dataclass
class DateRank:
    """How well one list ranked the market as of one date."""

    as_of: str
    universe: int  # liquid stocks with a forward 1M return
    listed: int
    median: dict[int, Optional[float]]  # horizon in months -> median forward return of the universe
    excess: dict[tuple[int, int], Optional[float]]  # (top N, months) -> mean forward return minus the median
    spearman: Optional[float]  # score vs forward 3M return inside the list
    capture: dict[int, Optional[float]]  # list size -> share of the eventual best 10 (3M) inside its first N
    winners: frozenset  # the symbols of the 10 best forward-3M returns
    ranks: dict[str, int] = field(default_factory=dict)  # rank in the list
    rows: dict[str, dict] = field(default_factory=dict)


def _median(values: Iterable[float]) -> Optional[float]:
    values = list(values)
    return statistics.median(values) if values else None


def rank_date(as_of: str, rows: Sequence[dict]) -> DateRank:
    listed = sorted((r for r in rows if r["listed"]), key=lambda r: (-r["score"], r["symbol"]))
    ranks = {r["symbol"]: i for i, r in enumerate(listed, start=1)}
    median: dict[int, Optional[float]] = {}
    excess: dict[tuple[int, int], Optional[float]] = {}
    for months, key in ((1, "fwd1"), (3, "fwd3")):
        have = [r for r in rows if r[key] is not None]
        median[months] = _median(r[key] for r in have) if len(have) >= 100 else None
        for n in TOP_SIZES:
            picks = [r[key] for r in listed[:n] if r[key] is not None]
            excess[(n, months)] = statistics.fmean(picks) - median[months] if picks and median[months] is not None else None

    with_3m = [r for r in listed if r["fwd3"] is not None]
    rho = spearman([r["score"] for r in with_3m], [r["fwd3"] for r in with_3m]) if median[3] is not None else None
    winners = frozenset(
        r["symbol"] for r in sorted((r for r in rows if r["fwd3"] is not None), key=lambda r: (-r["fwd3"], r["symbol"]))[:CAPTURE_TOP]
    ) if median[3] is not None else frozenset()
    capture = {
        n: len(winners & {r["symbol"] for r in listed[:n]}) / CAPTURE_TOP if winners else None for n in CAPTURE_SIZES
    }
    return DateRank(
        as_of, sum(r["fwd1"] is not None for r in rows), len(listed), median, excess, rho, capture, winners, ranks,
        {r["symbol"]: r for r in rows},
    )


def rank_all(by_date: Mapping[str, Sequence[dict]]) -> list[DateRank]:
    return [rank_date(d, by_date[d]) for d in sorted(by_date)]


def split(ranks: Sequence[DateRank], test_start: str = TEST_START) -> dict[str, list[DateRank]]:
    return {
        "train": [r for r in ranks if r.as_of < test_start],
        "test": [r for r in ranks if r.as_of >= test_start],
        "all": list(ranks),
    }


def _mean(values: Iterable[Optional[float]]) -> Optional[float]:
    have = [v for v in values if v is not None and v == v]
    return statistics.fmean(have) if have else None


def summarize(ranks: Sequence[DateRank]) -> dict:
    """Averages over the dates (dates without a forward window for a measure are left out of it)."""
    out: dict = {"dates": len(ranks)}
    for months in (1, 3):
        for n in TOP_SIZES:
            out[f"top{n}_{months}m"] = _mean(r.excess.get((n, months)) for r in ranks)
    out["spearman"] = _mean(r.spearman for r in ranks)
    for n in CAPTURE_SIZES:
        out[f"capture{n}"] = _mean(r.capture.get(n) for r in ranks)
    out["listed"] = _mean(r.listed for r in ranks)
    return out


@dataclass
class RunLag:
    symbol: str
    run_start: str
    first_top10: Optional[str]
    sessions: Optional[int]


def capture_lags(ranks: Sequence[DateRank], top: int = 10, within_steps: int = 6) -> list[RunLag]:
    """For each run of a name among the eventual best 3M performers, how many sessions after the run's first date it
    first stood in the list's top ``top`` (None when it never did within ``within_steps`` dates).

    A run starts at the first cut-off whose forward 3M return puts the name in the best 10; it ends when the name has
    been out of them for ``RUN_GAP_STEPS`` dates.
    """
    dates = [r.as_of for r in ranks]
    by_name: dict[str, list[int]] = {}
    for i, r in enumerate(ranks):
        for sym in r.winners:
            by_name.setdefault(sym, []).append(i)
    runs: list[RunLag] = []
    for sym, idx in sorted(by_name.items()):
        starts = [idx[0]] + [b for a, b in zip(idx, idx[1:]) if b - a > RUN_GAP_STEPS]
        for s in starts:
            hit = next(
                (t for t in range(s, min(len(ranks), s + within_steps + 1)) if ranks[t].ranks.get(sym, 10**9) <= top), None
            )
            sessions = None if hit is None else int(np.busday_count(dates[s], dates[hit]))
            runs.append(RunLag(sym, dates[s], None if hit is None else dates[hit], sessions))
    return runs


def lag_summary(runs: Sequence[RunLag]) -> dict:
    caught = [r for r in runs if r.sessions is not None]
    return {
        "runs": len(runs),
        "caught": len(caught),
        "at_start": sum(r.sessions == 0 for r in caught),
        "within_4w": sum(r.sessions <= 10 for r in caught),
        "median_sessions": statistics.median(r.sessions for r in caught) if caught else None,
    }


# --------------------------------------------------------------------------------------------------------------------
# Recent breakouts
# --------------------------------------------------------------------------------------------------------------------


def is_breakout_pick(row: dict) -> bool:
    """What the scanner's Recent breakouts view lists: a breakout, RS at least P50 and an unbroken trend."""
    return bool(row.get("breakout")) and not row.get("failed") and (row.get("rs") or 0) >= 0.5 and row.get("status") != "broken"


@dataclass
class BreakoutStats:
    events: int
    fwd1: Optional[float]  # mean forward 1M return minus the date's median
    fwd3: Optional[float]
    beat_1m: Optional[float]  # share that beat the date's median
    beat_3m: Optional[float]
    became_leader: Optional[float]  # share that were RS >= P90 (a leader) 4 to 8 weeks later
    baseline_became_leader: Optional[float]  # same for every mid-pack name (RS P50-P90, unbroken)
    leader_events: int = 0  # events that already were leaders when they broke out (left out of became_leader)


def breakout_stats(
    by_date: Mapping[str, Sequence[dict]], dates: Optional[Sequence[str]] = None, steps: Sequence[int] = BECAME_LEADER_STEPS
) -> BreakoutStats:
    """Pooled over the dates: forward returns of the Recent breakouts versus the median stock, and how many mid-pack
    breakouts became leaders (RS >= P90, unbroken) within 4 to 8 weeks, against all mid-pack names."""
    ordered = sorted(by_date)
    wanted = set(dates) if dates is not None else set(ordered)
    ex1: list[float] = []
    ex3: list[float] = []
    became: list[bool] = []
    base: list[bool] = []
    already = 0
    events = 0
    for i, d in enumerate(ordered):
        if d not in wanted:
            continue
        rows = by_date[d]
        med1 = _median(r["fwd1"] for r in rows if r["fwd1"] is not None)
        med3 = _median(r["fwd3"] for r in rows if r["fwd3"] is not None)
        later = [{r["symbol"]: r for r in by_date[ordered[i + k]]} for k in steps if i + k < len(ordered)]
        has_later = len(later) == len(steps)

        def became_leader(sym: str) -> bool:
            return any(sym in m and m[sym]["status"] == "leader" for m in later)

        for r in rows:
            mid = 0.5 <= (r["rs"] or 0) < 0.9 and r["status"] != "broken"
            if mid and has_later:
                base.append(became_leader(r["symbol"]))
            if not is_breakout_pick(r):
                continue
            events += 1
            if r["fwd1"] is not None and med1 is not None:
                ex1.append(r["fwd1"] - med1)
            if r["fwd3"] is not None and med3 is not None:
                ex3.append(r["fwd3"] - med3)
            if r["status"] == "leader":
                already += 1
            elif has_later and mid:
                became.append(became_leader(r["symbol"]))
    share = lambda xs: sum(xs) / len(xs) if xs else None  # noqa: E731
    return BreakoutStats(
        events,
        statistics.fmean(ex1) if ex1 else None,
        statistics.fmean(ex3) if ex3 else None,
        share([x > 0 for x in ex1]),
        share([x > 0 for x in ex3]),
        share(became),
        share(base),
        already,
    )


@dataclass
class BreakoutExample:
    symbol: str
    breakouts: list[str]  # cut-offs at which it was listed in Recent breakouts
    leader_entries: list[str]  # cut-offs at which it turned from not-a-leader into a leader
    caught: list[tuple[str, str]]  # (breakout cut-off, leader entry within 4-8 weeks after) pairs
    fwd3_after: Optional[float]  # forward 3M return from the first caught breakout


def breakout_examples(
    by_date: Mapping[str, Sequence[dict]], symbols: Sequence[str], steps: Sequence[int] = BECAME_LEADER_STEPS
) -> list[BreakoutExample]:
    """When each name showed up in Recent breakouts, when it turned into a leader, and the breakouts that preceded a
    leader entry by 4 to 8 weeks."""
    ordered = sorted(by_date)
    index = {d: {r["symbol"]: r for r in by_date[d]} for d in ordered}
    out = []
    for sym in symbols:
        rows = [index[d].get(sym) for d in ordered]
        breakouts = [d for d, r in zip(ordered, rows) if r and is_breakout_pick(r)]
        entries = [
            d
            for i, (d, r) in enumerate(zip(ordered, rows))
            if r and r["status"] == "leader" and (i == 0 or not rows[i - 1] or rows[i - 1]["status"] != "leader")
        ]
        caught = []
        for d in breakouts:
            i = ordered.index(d)
            if rows[i]["status"] == "leader":
                continue
            later = [ordered[i + k] for k in steps if i + k < len(ordered)]
            hit = next((e for e in later if index[e].get(sym) and index[e][sym]["status"] == "leader"), None)
            if hit:
                caught.append((d, hit))
        fwd3 = rows[ordered.index(caught[0][0])]["fwd3"] if caught else None
        out.append(BreakoutExample(sym, breakouts, entries, caught, fwd3))
    return out


def caught_leaders(by_date: Mapping[str, Sequence[dict]], limit: int = 10) -> list[tuple[str, str, str, float, float]]:
    """The biggest winners among breakouts that became leaders: (symbol, breakout cut-off, RS then, leader entry, fwd 3M)."""
    symbols = sorted({r["symbol"] for rows in by_date.values() for r in rows if is_breakout_pick(r)})
    best = []
    for e in breakout_examples(by_date, symbols):
        for d, entry in e.caught:
            row = next(r for r in by_date[d] if r["symbol"] == e.symbol)
            if row["fwd3"] is not None:
                best.append((e.symbol, d, f"P{(row['rs'] or 0) * 100:.0f}", entry, row["fwd3"]))
    return sorted(best, key=lambda t: -t[4])[:limit]


# --------------------------------------------------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------------------------------------------------


def _pct(v: Optional[float], digits: int = 1) -> str:
    return "—" if v is None or v != v else f"{v:+.{digits}f}"


def _share(v: Optional[float]) -> str:
    return "—" if v is None else f"{v * 100:.0f}%"


def _num(v: Optional[float], digits: int = 2) -> str:
    return "—" if v is None or v != v else f"{v:+.{digits}f}"


def render_rank_quality(variants: Mapping[str, Sequence[DateRank]], test_start: str = TEST_START) -> str:
    """Summary table per period: how well each variant's list ranks the eventual big winners."""
    out = [
        "### Rank quality: do the highest scores go to the biggest winners?\n",
        "Biweekly cut-off dates; *excess* is the mean forward return of the list's top N minus the median liquid stock. "
        "*Spearman* is the rank correlation of score and forward 3M return inside the list. *Capture* is the share of "
        "the 10 best forward-3M performers (of all liquid stocks) inside the list's first 10 / 30. "
        f"Train = cut-offs before {test_start} (where the weights were tuned), test = {test_start} onwards.\n",
    ]
    names = list(variants)
    for period in ("train", "test", "all"):
        subsets = {n: split(variants[n], test_start)[period] for n in names}
        sums = {n: summarize(s) for n, s in subsets.items()}
        lags = {n: lag_summary(capture_lags(s)) for n, s in subsets.items()}
        first = next(iter(sums.values()))
        out.append(f"\n**{period.capitalize()}** ({first['dates']} cut-off dates)\n")
        out.append("| Metric | " + " | ".join(names) + " |")
        out.append("|---|" + "---|" * len(names))

        def row(label, fmt, key):
            out.append(f"| {label} | " + " | ".join(fmt(sums[n][key]) for n in names) + " |")

        for months in (1, 3):
            for n in TOP_SIZES:
                row(f"Top {n} forward {months}M excess (pts)", _pct, f"top{n}_{months}m")
        row("Spearman(score, fwd 3M)", _num, "spearman")
        row("Capture in top 10", _share, "capture10")
        row("Capture in top 30", _share, "capture30")
        out.append(
            "| Runs caught in top 10 / runs | " + " | ".join(f"{lags[n]['caught']}/{lags[n]['runs']}" for n in names) + " |"
        )
        out.append(
            "| Median sessions from run start to top 10 | "
            + " | ".join("—" if lags[n]["median_sessions"] is None else f"{lags[n]['median_sessions']:g}" for n in names)
            + " |"
        )
        out.append("| List size (avg) | " + " | ".join(f"{sums[n]['listed'] or 0:.0f}" for n in names) + " |")
    return "\n".join(out)


def _cell(rank: Optional[int], row: Optional[dict]) -> str:
    if row is None:
        return "n/a"
    rs = "" if row["rs"] is None else f" P{row['rs'] * 100:.0f}"
    if rank:
        return f"**#{rank}**{rs}"
    return f"—{rs} {row['status']}" if row["status"] != "n/a" else f"—{rs}"


def render_reference(
    variants: Mapping[str, Sequence[DateRank]], symbols: Sequence[str] = REFERENCE, start: str = SNDK_RUN_START
) -> str:
    """Rank of every reference name on every cut-off date from ``start`` (SNDK's run); other variants in brackets."""
    names = list(variants)
    main = variants[names[-1]]
    out = [
        f"### Reference leaders: rank on every cut-off from {start} ({names[-1]} list; "
        + (f"{names[0]} rank in brackets, [-] = not listed" if len(names) > 1 else "—")
        + ")\n",
        "A cell is the rank with the blended 1M/3M/6M relative-strength percentile; `—` means off the list "
        "(*laggard* below P90, or *broken*).\n",
        "| Cut-off | " + " | ".join(symbols) + " |",
        "|---|" + "---|" * len(symbols),
    ]
    other = {r.as_of: r for r in variants[names[0]]} if len(names) > 1 else {}
    for dr in main:
        if dr.as_of < start:
            continue
        cells = []
        for sym in symbols:
            c = _cell(dr.ranks.get(sym), dr.rows.get(sym))
            if other:
                o = other.get(dr.as_of)
                rank = o.ranks.get(sym) if o else None
                c += f" [{rank if rank else '-'}]"
            cells.append(c)
        out.append(f"| {dr.as_of} | " + " | ".join(cells) + " |")
    return "\n".join(out)


def render_breakouts(
    by_date: Mapping[str, Sequence[dict]],
    examples: Sequence[BreakoutExample],
    test_start: str = TEST_START,
) -> str:
    out = [
        "### Recent breakouts: do they surface future leaders?\n",
        "Breakout = latest weekly closes above a tight 3-10 week base on heavy volume (RS at least P50, unbroken trend, "
        "no kill candle). Returns are pooled over all breakout events and measured against the median liquid stock of "
        "the same date. *Became leader* is the share of breakouts that were not yet leaders and were RS >= P90 (unbroken) "
        "4 to 8 weeks later; the baseline is the same rate for every mid-pack name (RS P50-P90).\n",
        "| Period | Events | Fwd 1M vs median (pts) | Beat median 1M | Fwd 3M vs median (pts) | Beat median 3M | Became leader | Baseline |",
        "|---|---|---|---|---|---|---|---|",
    ]
    ordered = sorted(by_date)
    periods = {
        "Train": [d for d in ordered if d < test_start],
        "Test": [d for d in ordered if d >= test_start],
        "All": ordered,
    }
    for label, ds in periods.items():
        s = breakout_stats(by_date, ds)
        out.append(
            f"| {label} | {s.events} | {_pct(s.fwd1)} | {_share(s.beat_1m)} | {_pct(s.fwd3)} | {_share(s.beat_3m)} | "
            f"{_share(s.became_leader)} | {_share(s.baseline_became_leader)} |"
        )
    out.append("\n| Name | Listed in Recent breakouts (cut-offs) | Turned into a leader (cut-offs) | Breakouts that preceded a leader entry by 4-8 weeks |")
    out.append("|---|---|---|---|")
    shown = lambda xs: ", ".join(xs[:4]) + (f" (+{len(xs) - 4})" if len(xs) > 4 else "") if xs else "never"  # noqa: E731
    for e in examples:
        pairs = "; ".join(f"{d} → {entry}" for d, entry in e.caught[:3]) or "none"
        out.append(f"| {e.symbol} | {shown(e.breakouts)} | {shown(e.leader_entries)} | {pairs} |")
    best = caught_leaders(by_date)
    if best:
        out.append("\nBiggest winners among breakouts that went on to become leaders:\n")
        out.append("| Name | Breakout cut-off | RS then | Became a leader | Forward 3M from the breakout |")
        out.append("|---|---|---|---|---|")
        for sym, d, rs, entry, f3 in best:
            out.append(f"| {sym} | {d} | {rs} | {entry} | {_pct(f3)}% |")
    return "\n".join(out)


# --------------------------------------------------------------------------------------------------------------------
# Weekly setups
# --------------------------------------------------------------------------------------------------------------------


def is_setup_pick(row: dict, min_rs: float = 0.9) -> bool:
    """What the scanner's Weekly setups view lists: a leader (RS at least ``min_rs``, unbroken trend) with a weekly setup."""
    return bool(row.get("has_setup")) and (row.get("rs") or 0) >= min_rs and row.get("status") != "broken"


def is_failed_pick(row: dict) -> bool:
    """What the scanner's Failed breakouts view lists: a breakout of the last 8 weeks that lost its level, RS at least P50."""
    return bool(row.get("failed")) and (row.get("rs") or 0) >= 0.5


FRESH_FAILURE_SESSIONS = 10


def is_fresh_failed_pick(row: dict) -> bool:
    """A failed breakout that lost its level within the last 10 sessions (the warning is still new)."""
    return is_failed_pick(row) and row["failed"]["sessions_below"] <= FRESH_FAILURE_SESSIONS


def is_leader_pick(row: dict, min_rs: float = 0.9) -> bool:
    return (row.get("rs") or 0) >= min_rs and row.get("status") != "broken"


@dataclass
class SetupStats:
    names: int  # pooled (date, name) picks
    per_date: Optional[float]  # mean number of picks per cut-off
    fwd1_median: Optional[float]  # mean forward 1M return minus the date's median liquid stock
    fwd3_median: Optional[float]
    fwd1_qqq: Optional[float]  # mean forward 1M return minus QQQ's over the same window
    fwd3_qqq: Optional[float]
    beat_qqq_1m: Optional[float]
    beat_qqq_3m: Optional[float]


def setup_stats(
    by_date: Mapping[str, Sequence[dict]],
    benchmark: Mapping[str, tuple[Optional[float], Optional[float]]],
    pick=is_setup_pick,
    dates: Optional[Sequence[str]] = None,
) -> SetupStats:
    """Pooled over the dates: forward 1M/3M return of the rows ``pick`` selects, minus the date's median stock and minus
    QQQ. ``benchmark`` maps a cut-off to QQQ's forward (1M, 3M) return."""
    wanted = set(dates) if dates is not None else set(by_date)
    m1: list[float] = []
    m3: list[float] = []
    q1: list[float] = []
    q3: list[float] = []
    names = 0
    n_dates = 0
    for d in sorted(by_date):
        if d not in wanted:
            continue
        rows = by_date[d]
        n_dates += 1
        med1 = _median(r["fwd1"] for r in rows if r["fwd1"] is not None)
        med3 = _median(r["fwd3"] for r in rows if r["fwd3"] is not None)
        b1, b3 = benchmark.get(d, (None, None))
        for r in rows:
            if not pick(r):
                continue
            names += 1
            if r["fwd1"] is not None and med1 is not None:
                m1.append(r["fwd1"] - med1)
            if r["fwd3"] is not None and med3 is not None:
                m3.append(r["fwd3"] - med3)
            if r["fwd1"] is not None and b1 is not None:
                q1.append(r["fwd1"] - b1)
            if r["fwd3"] is not None and b3 is not None:
                q3.append(r["fwd3"] - b3)
    mean = lambda xs: statistics.fmean(xs) if xs else None  # noqa: E731
    share = lambda xs: sum(x > 0 for x in xs) / len(xs) if xs else None  # noqa: E731
    return SetupStats(names, names / n_dates if n_dates else None, mean(m1), mean(m3), mean(q1), mean(q3), share(q1), share(q3))


def benchmark_returns(
    daily: pd.DataFrame,
    dates: Sequence[str],
    splits: Sequence[tuple] = (),
) -> dict[str, tuple[Optional[float], Optional[float]]]:
    """QQQ's forward 1M and 3M return from every cut-off date."""
    return {
        d: (
            forward_return(daily, pd.Timestamp(d), splits=splits),
            forward_return(daily, pd.Timestamp(d), months=3, splits=splits),
        )
        for d in dates
    }


def render_setups(
    by_date: Mapping[str, Sequence[dict]],
    benchmark: Mapping[str, tuple[Optional[float], Optional[float]]],
    test_start: str = TEST_START,
) -> str:
    out = [
        "### Weekly setups: leaders with a long-side weekly Strat setup\n",
        "Pooled over every cut-off: the forward 1M / 3M return of the names in the Weekly setups view (RS >= P90, unbroken "
        "trend, a long-side weekly setup on the latest weekly candle) minus the median liquid stock and minus QQQ, against "
        "all Leaders without a setup and all Leaders (the same names with or without a setup).\n",
        "| Period | List | Picks / date | Fwd 1M vs median (pts) | Fwd 3M vs median (pts) | Fwd 1M vs QQQ (pts) | Fwd 3M vs QQQ (pts) | Beat QQQ 3M |",
        "|---|---|---|---|---|---|---|---|",
    ]
    ordered = sorted(by_date)
    periods = {
        "Train": [d for d in ordered if d < test_start],
        "Test": [d for d in ordered if d >= test_start],
        "All": ordered,
    }
    lists = {
        "Weekly setups": is_setup_pick,
        "Leaders, no setup": lambda r: is_leader_pick(r) and not r.get("has_setup"),
        "Leaders": is_leader_pick,
    }
    for period, ds in periods.items():
        for name, pick in lists.items():
            s = setup_stats(by_date, benchmark, pick, ds)
            out.append(
                f"| {period} | {name} | {"—" if s.per_date is None else f"{s.per_date:.1f}"} | {_pct(s.fwd1_median)} | {_pct(s.fwd3_median)} | "
                f"{_pct(s.fwd1_qqq)} | {_pct(s.fwd3_qqq)} | {_share(s.beat_qqq_3m)} |"
            )
    return "\n".join(out)


def render_failed(
    by_date: Mapping[str, Sequence[dict]],
    benchmark: Mapping[str, tuple[Optional[float], Optional[float]]],
    test_start: str = TEST_START,
) -> str:
    out = [
        "### Failed breakouts: a warning signal?\n",
        "Failed breakout = a breakout (same detection as Recent breakouts) from the last 8 weeks whose base high the stock "
        "has since closed below (RS at least P50, any trend). *Fresh* = it lost the level within the last 10 sessions. "
        "Pooled over every cut-off: forward 1M / 3M return minus the median liquid stock of the date and minus QQQ. "
        "Negative numbers mean the names lagged, which is what a warning signal should show.\n",
        "| Period | List | Picks / date | Fwd 1M vs median (pts) | Fwd 3M vs median (pts) | Fwd 1M vs QQQ (pts) | Fwd 3M vs QQQ (pts) | Beat QQQ 3M |",
        "|---|---|---|---|---|---|---|---|",
    ]
    ordered = sorted(by_date)
    periods = {
        "Train": [d for d in ordered if d < test_start],
        "Test": [d for d in ordered if d >= test_start],
        "All": ordered,
    }
    lists = {
        "Failed breakouts": is_failed_pick,
        "Fresh failures": is_fresh_failed_pick,
        "Recent breakouts": is_breakout_pick,
    }
    for period, ds in periods.items():
        for name, pick in lists.items():
            s = setup_stats(by_date, benchmark, pick, ds)
            out.append(
                f"| {period} | {name} | {'—' if s.per_date is None else f'{s.per_date:.1f}'} | {_pct(s.fwd1_median)} | "
                f"{_pct(s.fwd3_median)} | {_pct(s.fwd1_qqq)} | {_pct(s.fwd3_qqq)} | {_share(s.beat_qqq_3m)} |"
            )
    return "\n".join(out)


def render_report(
    variants: Mapping[str, Sequence[DateRank]],
    breakouts: Optional[Mapping[str, Sequence[dict]]] = None,
    reference: Sequence[str] = REFERENCE,
    test_start: str = TEST_START,
    benchmark: Optional[Mapping[str, tuple[Optional[float], Optional[float]]]] = None,
) -> str:
    parts = [render_rank_quality(variants, test_start), render_reference(variants, reference)]
    if breakouts:
        parts.append(render_breakouts(breakouts, breakout_examples(breakouts, reference), test_start))
        if benchmark is not None:
            parts.append(render_setups(breakouts, benchmark, test_start))
            parts.append(render_failed(breakouts, benchmark, test_start))
    return "\n\n".join(parts)



@dataclass
class TimelinePoint:
    as_of: str
    rank: Optional[int]
    status: str
    score: float
    price: float
    off_6m_high_pct: Optional[float]


def run_timeline(
    daily_by_symbol: Mapping[str, pd.DataFrame],
    members,
    themes: Optional[ThemeMap],
    start: str,
    end: str,
    reference: Sequence[str] = REFERENCE,
    freq: str = "W-FRI",
    splits: Optional[Mapping] = None,
) -> dict[str, list[TimelinePoint]]:
    """Weekly new-score rank/status of each reference name between ``start`` and ``end`` (breakdown detection)."""
    series: dict[str, list[TimelinePoint]] = {s: [] for s in reference}
    last_bar = max(df.index[-1] for df in daily_by_symbol.values())
    for ts in pd.date_range(start, min(pd.Timestamp(end), last_bar), freq=freq):
        cut = _as_of_frames(daily_by_symbol, ts, splits)
        result = scan_all(members, cut, themes, method=LEADERS, changes=False)
        picks = new_list(result)
        by_sym = {r["symbol"]: r for r in result.rows}
        for sym in reference:
            row = by_sym.get(sym)
            if row is None:
                continue
            rank = next((i for i, r in enumerate(picks, start=1) if r["symbol"] == sym), None)
            series[sym].append(
                TimelinePoint(
                    ts.strftime("%Y-%m-%d"), rank, row["leader_status"], row["score"], row["price"],
                    row["leadership"]["off_6m_high_pct"],
                )
            )
    return series


def demotion(points: Sequence[TimelinePoint], top: int = 30) -> Optional[dict]:
    """First week a name that had been a top-``top`` leader stopped being on the leaders list, and how far price had
    already fallen from its highest weekly close by then."""
    seen = False
    peak = 0.0
    for p in points:
        peak = max(peak, p.price)
        if p.rank is not None and p.rank <= top:
            seen = True
        elif seen and p.rank is None:
            return {"date": p.as_of, "status": p.status, "below_peak_pct": (peak - p.price) / peak * 100.0, "peak": peak}
    return None


def render_timeline(series: Mapping[str, Sequence[TimelinePoint]]) -> str:
    out = ["### Reference leaders: weekly rank on the new leaders list (— = off the list), and demotion\n"]
    dates = sorted({p.as_of for pts in series.values() for p in pts})
    out.append("| Week | " + " | ".join(series) + " |")
    out.append("|---|" + "---|" * len(series))
    by = {s: {p.as_of: p for p in pts} for s, pts in series.items()}
    for d in dates:
        cells = []
        for s in series:
            p = by[s].get(d)
            cells.append("n/a" if p is None else (f"#{p.rank}" if p.rank else {"broken": "broken", "laggard": "—"}.get(p.status, "—")))
        out.append(f"| {d} | " + " | ".join(cells) + " |")
    out.append("\n| Name | Was a top-30 leader | First week demoted off the list | Status then | Price vs its peak close by then |")
    out.append("|---|---|---|---|---|")
    for s, pts in series.items():
        led = any(p.rank is not None and p.rank <= 30 for p in pts)
        dm = demotion(pts)
        if dm:
            out.append(f"| {s} | yes | {dm['date']} | {dm['status']} | {-dm['below_peak_pct']:.1f}% |")
        else:
            out.append(f"| {s} | {'yes' if led else 'no'} | {'still listed' if led else 'never a top-30 leader'} | | |")
    return "\n".join(out)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Rank-quality backtest of the leadership score against the old Strat-first score")
    parser.add_argument("--dates", nargs="+", help="cut-off dates (YYYY-MM-DD); default: every other Friday over the cache")
    parser.add_argument("--start", default=RANK_START, help="first default cut-off date")
    parser.add_argument("--test-start", default=TEST_START, help="cut-offs from this date on are the test period")
    parser.add_argument("--reference", nargs="+", default=list(REFERENCE), help="symbols whose ranks are reported")
    parser.add_argument("--timeline", action="store_true", help="also report weekly ranks/demotion over the leadership run")
    parser.add_argument("--timeline-start", default=RUN_START)
    parser.add_argument("--timeline-end", default="2099-12-31", help="defaults to the last cached bar")
    parser.add_argument("--no-old", action="store_true", help="skip the old-score comparison")
    args = parser.parse_args(argv)

    daily = data.load_all_daily(adjust=False)
    splits = data.load_splits()
    if not daily:
        print("The price cache is empty. Run `npm run refresh` first.", file=sys.stderr)
        return 1
    members = effective_universe(load_universe())
    try:
        themes = load_themes()
    except Exception:  # themes are optional for the comparison
        themes = None

    dates = args.dates or rank_dates(daily, args.start)
    new_rows = collect(daily, members, themes, dates, LEADERS, progress=True, splits=splits)
    variants: dict[str, list[DateRank]] = {}
    if not args.no_old:
        variants["Old"] = rank_all(collect(daily, members, themes, dates, LEGACY, progress=True, splits=splits))
    variants["New"] = rank_all(new_rows)
    print(render_report(
        variants, new_rows, tuple(args.reference), args.test_start,
        benchmark_returns(daily["QQQ"], dates, splits.get("QQQ", ())),
    ))
    if args.timeline:
        print()
        series = run_timeline(
            daily, members, themes, args.timeline_start, args.timeline_end, tuple(args.reference), splits=splits,
        )
        print(render_timeline(series))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
