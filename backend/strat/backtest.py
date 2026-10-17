"""Leaders backtest: cut the local price cache off at historical dates and compare the old Strat-first score with the
leadership-first score on what happened over the next month.

    python -m strat.backtest                       # default dates, markdown report on stdout
    python -m strat.backtest --dates 2026-08-13    # chosen dates
    python -m strat.backtest --timeline            # weekly rank/status of the reference leaders (breakdown check)

For each cut-off date only bars up to that date are used (prices, returns, averages, themes and relative-strength
percentiles are all recomputed from that history), then the picks are measured against the next calendar month. The
universe is today's S&P 500 + Nasdaq-100 list (survivorship bias: names that left the indexes are missing), filtered to
liquid stocks (price and average dollar volume at the cut-off date). Old picks are names with a weekly setup, ranked by
the old score; new picks are the leaders-only list ranked by the new score.
"""

from __future__ import annotations

import argparse
import statistics
import sys
from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence

import pandas as pd

from . import config, data
from .members import effective_universe
from .scanner import LEADERS, LEGACY, ScanResult, scan_all
from .themes import ThemeMap, load_themes
from .universe import load_universe

REFERENCE = ("HPE", "DELL", "MU", "SNDK", "ARM", "NBIS", "AMD", "PLTR")

# Different market conditions: the April 2025 tariff crash and its rebound, a steady uptrend, a winter rotation, a
# March 2026 pullback, then the April to September 2026 leadership run of the reference names.
DEFAULT_DATES = (
    "2025-04-21",
    "2025-10-17",
    "2026-01-16",
    "2026-03-20",
    "2026-04-24",
    "2026-05-15",
    "2026-06-18",
    "2026-07-17",
    "2026-08-13",
    "2026-09-11",
)
RUN_START, RUN_END = "2026-04-24", "2026-09-11"  # the reference names led the market in this window

TOP_SIZES = (10, 30)
WINNER_FRACTION = 0.20
FORWARD_MONTHS = 1
END_TOLERANCE_DAYS = 5

MEMBER_VARIANTS = ("old", "old_mw", "new", "new_mw", "new_setup")
VARIANT_LABELS = {
    "old": "Old: weekly-setup list, old score",
    "old_mw": "Old, default view (setup + Monthly & Weekly green)",
    "new": "New: leaders-only list, new score",
    "new_mw": "New, leaders also Monthly & Weekly green",
    "new_setup": "New, leaders that also have a weekly setup",
}


def cut_off(daily_by_symbol: Mapping[str, pd.DataFrame], as_of: pd.Timestamp) -> dict[str, pd.DataFrame]:
    """Every symbol's bars up to and including ``as_of`` (symbols with no bars yet are dropped)."""
    out = {}
    for sym, df in daily_by_symbol.items():
        sub = df.loc[:as_of]
        if len(sub):
            out[sym] = sub
    return out


def forward_return(daily: pd.DataFrame, as_of: pd.Timestamp, months: int = FORWARD_MONTHS) -> Optional[float]:
    """Percent return from the last close on or before ``as_of`` to the last close on or before one month later.

    None when the history does not run to the end of that window (or the symbol had no bars at ``as_of``).
    """
    close = daily["close"].dropna()
    end = as_of + pd.DateOffset(months=months)
    if close.empty or close.index[0] > as_of or close.index[-1] < end - pd.Timedelta(days=END_TOLERANCE_DAYS):
        return None
    base = float(close[:as_of].iloc[-1])
    final = float(close[:end].iloc[-1])
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


@dataclass
class ListStats:
    count: int
    top: dict[int, Optional[float]] = field(default_factory=dict)  # N -> mean forward return of the first N
    hit: dict[int, Optional[float]] = field(default_factory=dict)  # N -> share of the first N in the winners
    winners_in_top30: Optional[int] = None  # of the 30 biggest winners, how many are in the first 30


def list_stats(picks: Sequence[dict], forward: Mapping[str, float], winners: set[str], big30: set[str]) -> ListStats:
    st = ListStats(len(picks))
    for n in TOP_SIZES:
        top = [r["symbol"] for r in picks[:n] if r["symbol"] in forward]
        st.top[n] = statistics.fmean(forward[s] for s in top) if top else None
        st.hit[n] = sum(s in winners for s in top) / len(top) if top else None
    st.winners_in_top30 = len({r["symbol"] for r in picks[:30]} & big30)
    return st


@dataclass
class Snapshot:
    """One cut-off date: how each list did, and where the reference names stood."""

    as_of: str
    universe: int
    median: float
    winners: int
    variants: dict[str, ListStats]
    ref_old: dict[str, Optional[int]]  # rank in the old list (None = no weekly setup)
    ref_new: dict[str, Optional[int]]  # rank in the new leaders list (None = filtered out)
    ref_status: dict[str, str]  # leader / broken / laggard / n/a
    ref_fwd: dict[str, Optional[float]]
    ref_rs: dict[str, Optional[float]] = field(default_factory=dict)  # blended RS percentile, 0..1


def run_date(
    daily_by_symbol: Mapping[str, pd.DataFrame],
    members,
    themes: Optional[ThemeMap],
    as_of: str,
    reference: Sequence[str] = REFERENCE,
    with_old: bool = True,
) -> Snapshot:
    ts = pd.Timestamp(as_of)
    cut = cut_off(daily_by_symbol, ts)
    new = scan_all(members, cut, themes, method=LEADERS)
    old = scan_all(members, cut, themes, method=LEGACY) if with_old else None

    liquid = liquid_stocks(new.rows)
    forward = {}
    for r in liquid:
        f = forward_return(daily_by_symbol[r["symbol"]], ts)
        if f is not None:
            forward[r["symbol"]] = f
    ordered = sorted(forward, key=lambda s: (-forward[s], s))
    winners = set(ordered[: max(1, round(len(ordered) * WINNER_FRACTION))])
    big30 = set(ordered[:30])
    median = statistics.median(forward.values()) if forward else float("nan")

    lists = {
        "new": new_list(new),
        "new_mw": new_list(new, mw_green=True),
        "new_setup": new_list(new, setup=True),
    }
    if old is not None:
        lists["old"] = old_list(old)
        lists["old_mw"] = old_list(old, mw_green=True)
    variants = {k: list_stats(v, forward, winners, big30) for k, v in lists.items()}

    def rank_of(picks: Sequence[dict], sym: str) -> Optional[int]:
        return next((i for i, r in enumerate(picks, start=1) if r["symbol"] == sym), None)

    by_sym = {r["symbol"]: r for r in new.rows}
    return Snapshot(
        as_of=as_of,
        universe=len(forward),
        median=median,
        winners=len(winners),
        variants=variants,
        ref_old={s: rank_of(lists["old"], s) for s in reference} if old is not None else {},
        ref_new={s: rank_of(lists["new"], s) for s in reference},
        ref_status={s: by_sym[s]["leader_status"] if s in by_sym else "n/a" for s in reference},
        ref_fwd={s: forward.get(s) for s in reference},
        ref_rs={s: by_sym[s]['rs'] if s in by_sym else None for s in reference},
    )


def _pct(v: Optional[float], digits: int = 1) -> str:
    return "—" if v is None or v != v else f"{v:+.{digits}f}%"


def _share(v: Optional[float]) -> str:
    return "—" if v is None else f"{v * 100:.0f}%"


def _mean(values: Sequence[Optional[float]]) -> Optional[float]:
    have = [v for v in values if v is not None and v == v]
    return statistics.fmean(have) if have else None


def render_report(snaps: Sequence[Snapshot], reference: Sequence[str] = REFERENCE) -> str:
    """Markdown report: per-date old vs new table, averages, and the reference leaders' ranks."""
    out: list[str] = []
    out.append("### Old vs new scoring, forward 1-month return of the picks\n")
    out.append(
        "Top-10 / Top-30 are the average forward 1M return of the first 10 / 30 names of each list; "
        "*Median* is the median forward 1M return of all liquid stocks. Hit rate is the share of the first 30 that were "
        f"in the top {WINNER_FRACTION:.0%} of forward winners (a random pick scores {WINNER_FRACTION:.0%}). "
        "Winners-in-top-30 counts how many of the 30 biggest forward winners the first 30 caught.\n"
    )
    out.append("| Cut-off | Stocks | Median | Old top 10 | New top 10 | Old top 30 | New top 30 | Old hit-30 | New hit-30 | Old winners/30 | New winners/30 | Old list | New list |")
    out.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for s in snaps:
        o, n = s.variants.get("old"), s.variants["new"]
        out.append(
            f"| {s.as_of} | {s.universe} | {_pct(s.median)} | {_pct(o.top[10]) if o else '—'} | {_pct(n.top[10])} | "
            f"{_pct(o.top[30]) if o else '—'} | {_pct(n.top[30])} | {_share(o.hit[30]) if o else '—'} | {_share(n.hit[30])} | "
            f"{o.winners_in_top30 if o else '—'} | {n.winners_in_top30} | {o.count if o else '—'} | {n.count} |"
        )
    avg = lambda f: _mean([f(s) for s in snaps])  # noqa: E731
    o_ok = [s for s in snaps if "old" in s.variants]
    out.append(
        f"| **Average** | | **{_pct(avg(lambda s: s.median))}** | "
        f"**{_pct(_mean([s.variants['old'].top[10] for s in o_ok]))}** | **{_pct(avg(lambda s: s.variants['new'].top[10]))}** | "
        f"**{_pct(_mean([s.variants['old'].top[30] for s in o_ok]))}** | **{_pct(avg(lambda s: s.variants['new'].top[30]))}** | "
        f"**{_share(_mean([s.variants['old'].hit[30] for s in o_ok]))}** | **{_share(avg(lambda s: s.variants['new'].hit[30]))}** | "
        f"**{_mean([s.variants['old'].winners_in_top30 for s in o_ok]) or 0:.1f}** | **{avg(lambda s: s.variants['new'].winners_in_top30):.1f}** | | |"
    )

    out.append("\n### Averages across the dates, by list variant (the setup and continuity gates)\n")
    out.append("| List | Top 10 | Top 30 | Top-30 excess vs median | Hit-30 | Winners/30 |")
    out.append("|---|---|---|---|---|---|")
    for key in MEMBER_VARIANTS:
        have = [s for s in snaps if key in s.variants]
        if not have:
            continue
        t10 = _mean([s.variants[key].top[10] for s in have])
        t30 = _mean([s.variants[key].top[30] for s in have])
        med = _mean([s.median for s in have])
        exc = None if t30 is None or med is None else t30 - med
        out.append(
            f"| {VARIANT_LABELS[key]} | {_pct(t10)} | {_pct(t30)} | {_pct(exc)} | "
            f"{_share(_mean([s.variants[key].hit[30] for s in have]))} | "
            f"{_mean([s.variants[key].winners_in_top30 for s in have]) or 0:.1f} |"
        )

    out.append("\n### Reference leaders: rank on each date (new leaders list; old weekly-setup list in square brackets)\n")
    out.append(
        "Each cell is the rank on the new leaders-only list with the name's blended 1M/3M/6M relative-strength percentile "
        "(`P97`). `—` means filtered out of the new list: *laggard* (RS below P90) or *broken* (RS high but the trend is "
        "lost). `[no setup]` means the old scanner did not list it at all.\n"
    )
    out.append("| Cut-off | " + " | ".join(reference) + " |")
    out.append("|---|" + "---|" * len(reference))
    for s in snaps:
        cells = []
        for sym in reference:
            new_rank = s.ref_new.get(sym)
            old_rank = s.ref_old.get(sym)
            rs = s.ref_rs.get(sym)
            rs_txt = "" if rs is None else f" P{rs * 100:.0f}"
            new_txt = f"**#{new_rank}**{rs_txt}" if new_rank else f"—{rs_txt} {s.ref_status.get(sym, 'n/a')}"
            old_txt = f"#{old_rank}" if old_rank else "no setup"
            cells.append(f"{new_txt} [{old_txt}]" if s.ref_old else new_txt)
        out.append(f"| {s.as_of} | " + " | ".join(cells) + " |")
    n_run = [s for s in snaps if RUN_START <= s.as_of <= RUN_END]
    if n_run:
        out.append(f"\nInside the {RUN_START} to {RUN_END} run (new list size shown per date above):\n")
        out.append("| Name | Dates on the new list | Dates in its top 10 | Dates in the old list | Avg forward 1M |")
        out.append("|---|---|---|---|---|")
        for sym in reference:
            new_ranks = [s.ref_new.get(sym) for s in n_run]
            old_ranks = [s.ref_old.get(sym) for s in n_run]
            out.append(
                f"| {sym} | {sum(r is not None for r in new_ranks)}/{len(n_run)} | "
                f"{sum(r is not None and r <= 10 for r in new_ranks)}/{len(n_run)} | "
                f"{sum(r is not None for r in old_ranks) if s.ref_old else '—'}/{len(n_run)} | "
                f"{_pct(_mean([s.ref_fwd.get(sym) for s in n_run]))} |"
            )
    return "\n".join(out)


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
) -> dict[str, list[TimelinePoint]]:
    """Weekly new-score rank/status of each reference name between ``start`` and ``end`` (breakdown detection)."""
    series: dict[str, list[TimelinePoint]] = {s: [] for s in reference}
    last_bar = max(df.index[-1] for df in daily_by_symbol.values())
    for ts in pd.date_range(start, min(pd.Timestamp(end), last_bar), freq=freq):
        cut = cut_off(daily_by_symbol, ts)
        result = scan_all(members, cut, themes, method=LEADERS)
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
    parser = argparse.ArgumentParser(description="Backtest the leadership score against the old Strat-first score")
    parser.add_argument("--dates", nargs="+", default=list(DEFAULT_DATES), help="cut-off dates (YYYY-MM-DD)")
    parser.add_argument("--reference", nargs="+", default=list(REFERENCE), help="symbols whose ranks are reported")
    parser.add_argument("--timeline", action="store_true", help="also report weekly ranks/demotion over the leadership run")
    parser.add_argument("--timeline-start", default=RUN_START)
    parser.add_argument("--timeline-end", default="2099-12-31", help="defaults to the last cached bar")
    parser.add_argument("--no-old", action="store_true", help="skip the old-score comparison")
    args = parser.parse_args(argv)

    daily = data.load_all_daily()
    if not daily:
        print("The price cache is empty. Run `npm run refresh` first.", file=sys.stderr)
        return 1
    members = effective_universe(load_universe())
    try:
        themes = load_themes()
    except Exception:  # themes are optional for the comparison
        themes = None

    snaps = []
    for d in args.dates:
        print(f"[backtest] {d}", file=sys.stderr, flush=True)
        snaps.append(run_date(daily, members, themes, d, tuple(args.reference), with_old=not args.no_old))
    print(render_report(snaps, tuple(args.reference)))
    if args.timeline:
        print()
        series = run_timeline(daily, members, themes, args.timeline_start, args.timeline_end, tuple(args.reference))
        print(render_timeline(series))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
