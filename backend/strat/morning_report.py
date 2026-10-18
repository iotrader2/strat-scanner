"""Write the morning-leader backtest report from the local database.

``python -m strat.morning_report`` prints the summary and writes ``backend/data/morning_report.md``.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from . import config
from .intraday import YAHOO_15M_LOOKBACK_DAYS
from .morning import WINDOW_IDS, definition_text
from .morning_api import cached_stats
from .morning_store import counts

HORIZON_LABEL = {"eod": "EOD", "d1": "+1d", "d2": "+2d", "d3": "+3d", "d4": "+4d", "d5": "+5d"}


def _r(value, digits: int = 2) -> str:
    if value is None:
        return "—"
    text = f"{abs(value):.{digits}f}"
    if float(text) == 0:
        return f"{0:.{digits}f}R"
    return f"{'+' if value > 0 else '-'}{text}R"


def _rate(value) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.1f}%"


def _count(value) -> str:
    if value is None:
        return "—"
    return f"{value:.1f}"


def _dist(value) -> str:
    if value is None:
        return "—"
    return f"{abs(value):.2f}%"


def _pct(value, digits: int = 2) -> str:
    if value is None:
        return "—"
    text = f"{abs(value):.{digits}f}"
    if float(text) == 0:
        return f"{0:.{digits}f}%"
    return f"{'+' if value > 0 else '-'}{text}%"


def _num(value) -> str:
    if value is None:
        return "—"
    return str(int(value))


_SINGLE_METRICS = (
    ("n_days", "days", _num),
    ("n_trades", "fills", _num),
    ("avg_pct", "avg %", _pct),
    ("avg_r", "avg R", _r),
    ("win_rate", "win", _rate),
    ("stop_hit_rate", "stop", _rate),
    ("gap_count", "gaps", _num),
    ("total_r", "total R", lambda value: _r(value, 1)),
    ("expectancy", "expectancy", _r),
    ("avg_mfe", "avg MFE", _r),
    ("median_r", "median R", _r),
    ("best_r", "best R", _r),
    ("worst_r", "worst R", _r),
    ("median_pct", "median %", _pct),
    ("best_pct", "best %", _pct),
    ("worst_pct", "worst %", _pct),
    ("vs_qqq", "vs QQQ", _pct),
)

_STRAT_METRICS = _SINGLE_METRICS + (("vs_rma_first", "vs 10:30 first", _r),)
_STRAT_PATTERNS = ("2d-2u", "2d-1-2u", "3-1-2u", "1-2d-2u")


def render(stats: dict, meta: dict) -> str:
    lines = [
        "# Morning leaders",
        "",
        "Which of the five morning check-ins is the best time to buy the leaders that have qualified.",
        "Leaders are the scanner's top 10 stocks as of the **prior close**. A name is bought only after a",
        "5-minute bar has closed above its 20-period RMA. Nothing here looks ahead.",
        "",
        definition_text(),
        "",
        "## What was collected",
        "",
        f"- Leader sessions stored: {meta['leader_days']} ({meta['leader_rows']} rows).",
        f"- 5-minute bars stored: {meta.get('bar_rows_5m', 0)} "
        f"({meta.get('bar_start_5m') or '—'} → {meta.get('bar_end_5m') or '—'}).",
        f"- 15-minute bars stored: {meta.get('bar_rows_15m', meta['bar_rows'])} "
        f"({meta.get('bar_start_15m') or meta['bar_start'] or '—'} → {meta.get('bar_end_15m') or meta['bar_end'] or '—'}).",
        f"- Bar sources: {meta['bar_sources'] or 'none yet'}.",
        f"- Sessions with entry results: {meta['result_days']}.",
        f"- Yahoo 5-minute and 15-minute history is about the last {YAHOO_15M_LOOKBACK_DAYS} calendar days "
        f"(`period=60d`, 60 sessions). Older sessions keep their leader snapshot.",
        "",
        "Sample-size caveat: the names bought in one morning move together, so 40 mornings are not 400 independent bets.",
        "Average R gives each morning one vote. Expectancy is the mean R per fill. Win rate and the stop-hit rate are per fill.",
        "Mornings when nobody had crossed are left out of the return columns and included in the qualified average.",
        "A split inside the hold is adjusted out; it is not a loss.",
        "",
        "## By check-in",
        "",
        "1R is 1% of the entry. Qualified is the average number of the top 10 that had closed above the 20 RMA, including mornings when the count was zero.",
        "EOD through +5d are stop-aware: a trade that has been stopped counts as −1R from the stop day on.",
        "The stop is 1% under the entry. A later 5-minute bar at or below that price stops the trade. Gaps are fills whose stopping bar opened below the stop; they still book −1R.",
        "A morning stays out of a horizon until that hold is finished: some name has the close stored, or every name is already stopped.",
        "Days, fills, total R, win rate, stop-hit rate, gaps and expectancy are the +3 day sample. Each horizon's average uses the mornings finished through that horizon, so EOD can include a morning that does not yet have a day-3 close.",
        "Avg MFE is the best R reached before the stop or the end of the +5 day hold, averaged over fills resolved by day 3.",
        "9:45 is the earliest buy. QQQ is the same clock-time hold, without a stop.",
        "",
    ]
    header = "| Window | Days | Fills | Qualified | EOD | +1d | +2d | +3d | +4d | +5d | Win | Stop | Gaps | Total R | Expectancy | Avg MFE |"
    sep = "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
    lines.extend([header, sep])
    for window in WINDOW_IDS:
        block = (stats.get("windows") or {}).get(window)
        if not block:
            continue
        h = block["horizons"]
        primary = h["d3"] if h["d3"]["n_days"] else h["eod"]
        lines.append(
            "| "
            + " | ".join(
                [
                    window,
                    str(primary["n_days"]),
                    str(primary["n_trades"]),
                    _count(block.get("avg_qualified")),
                    _r(h["eod"]["avg"]),
                    _r(h["d1"]["avg"]),
                    _r(h["d2"]["avg"]),
                    _r(h["d3"]["avg"]),
                    _r(h["d4"]["avg"]),
                    _r(h["d5"]["avg"]),
                    _rate(primary["win_rate"]),
                    _rate(primary["stop_hit_rate"]),
                    str(primary.get("gap_count") if primary.get("gap_count") is not None else "—"),
                    _r(primary.get("total_r"), 1),
                    _r(primary.get("expectancy")),
                    _r(primary.get("avg_mfe")),
                ]
            )
            + " |"
        )
    best = stats.get("best")
    lines.extend(["", "## Best time to buy leaders", ""])
    if not best:
        lines.append("Not enough completed holds to choose a check-in yet.")
    else:
        horizon = HORIZON_LABEL.get(best["horizon"], best["horizon"])
        lines.append(
            f"**{best['window']}** has the highest average {horizon} result: "
            f"{_r(best['avg'])} per morning "
            f"({_rate(best['win_rate'])} of fills ahead, "
            f"n = {best['n_days']} mornings / {best['n_trades']} fills, total {_r(best.get('total_r'), 1)})."
        )
        lines.append("")
        lines.append(
            f"On average {_count(best.get('avg_qualified'))} of the ten leaders had closed above the 20 RMA by {best['window']}."
        )
        lines.append("")
        lines.append(
            f"A 1% stop was hit {_rate(best['stop_hit_rate'])} of the time by {horizon}. "
            f"{best.get('gap_count', 0)} of those fills gapped through the stop and still booked −1R. "
            f"Expectancy is {_r(best['expectancy'])} per trade. "
            f"The average trade reached {_r(best.get('avg_mfe'))} in its favor before the stop or day 5."
        )
        lines.append("")
        lines.append(f"Against holding QQQ from the same minute: {_r(best.get('vs_qqq'))}.")
        lines.append("")
        lines.append(
            "That is a description of this sample, not a promise. Overlapping holds, a short window, and "
            "today's index membership (survivorship) all apply."
        )
    _append_single(lines, stats)
    _append_strat(lines, stats)
    _append_cross(lines, stats)
    _append_reclaim(lines, stats)
    lines.append("")
    return "\n".join(lines)


def _append_single(lines: list[str], stats: dict) -> None:
    single = stats.get("single_entry") or {}
    books = single.get("books") or {}
    order = [book_id for book_id in (single.get("order") or []) if book_id in books]
    lines.extend(["", "## Single entry: 10:30 RMA and the 20 EMA", ""])
    if single.get("definition"):
        lines.append(single["definition"])
        lines.append("")
    ready = [
        book_id
        for book_id in order
        if (books[book_id].get("horizons") or {}).get("eod", {}).get("n_days")
    ]
    if not ready:
        lines.append("Not enough completed holds for the single-entry study yet.")
        return
    bits = []
    for book_id in order:
        book = books[book_id]
        when = book.get("avg_entry") or "—"
        median = book.get("median_entry")
        clock = when if not median or median == when else f"{when} on average (median {median})"
        bits.append(
            f"**{book['label']}** enters at {clock} "
            f"with an average stop {_dist(book.get('avg_stop_pct'))} under the entry"
        )
    lines.append("Average entry time and average stop distance, per fill: " + "; ".join(bits) + ".")
    lines.append("")
    lines.append(
        "Average % and average R give each morning one vote. Expectancy, win rate, the stop-hit rate, "
        "and best, median, and worst are per fill. Total R sums those fills. From the stop day on the "
        "result is the exit: the stop price, or the open when the bar gapped through. vs QQQ is that "
        "morning's stop-aware percent minus QQQ held from the same minute, with no stop on QQQ. "
        "MFE is the best R reached before the stop or the end of the +5 day hold."
    )
    lines.append("")
    labels = [books[book_id]["label"] for book_id in order]
    lines.append("| | " + " | ".join(labels) + " |")
    lines.append("| --- | " + " | ".join("---:" for _ in labels) + " |")
    for name, title in HORIZON_LABEL.items():
        for key, metric, fmt in _SINGLE_METRICS:
            cells = [fmt((books[book_id].get("horizons") or {}).get(name, {}).get(key)) for book_id in order]
            lines.append(f"| {title} {metric} | " + " | ".join(cells) + " |")


def _append_strat(lines: list[str], stats: dict) -> None:
    strat = stats.get("strat_reversal") or {}
    books = strat.get("books") or {}
    panels = strat.get("panels") or []
    lines.extend(["", "## Strat reversal: 15-minute and 30-minute", ""])
    if strat.get("definition"):
        lines.append(strat["definition"])
        lines.append("")
    lines.append(
        "The entry does not wait for the candle to close. If the completed candle takes out the prior "
        "low as well and finishes as a 3, the trade is kept. The pattern label is the prefix, and the "
        "share that finished as a 2U is below. A 2D followed by an inside is 1-2d-2u only, not also 2d-2u. "
        "A 2D with anything else before it, including a 3, is 2d-2u."
    )
    lines.append("")
    lines.append(
        "The stop is fixed when the trade is filled: the lower of the prior candle's low and the lows of "
        "the 5-minute bars in the entry candle that had already closed. The trigger bar's own low is not "
        "included, and the stop is not moved down to the entry candle's final low. A later 5-minute bar "
        "at or below the stop exits at the stop. A bar that opens below the stop exits at the open and "
        "can book worse than −1R. A trigger whose stop is not below the entry is skipped, and the scan "
        "continues for a later reversal that day. A through-trade may use the trigger bar's close for the "
        "20 RMA check. A gap fill at the open uses only bars that had already closed."
    )
    lines.append("")
    best = strat.get("best")
    benchmark = strat.get("benchmark") or {}
    if not best:
        lines.append("Not enough completed holds for the Strat reversal study yet.")
    else:
        bench = _r(benchmark.get("avg_r"))
        paired = _r(best.get("vs_rma_first"))
        lines.append(
            f"**{best['label']}** is the best of these books by day 3 at {_r(best['avg_r'])} per morning "
            f"(n = {best['n_days']} mornings / {best['n_trades']} fills). "
            f"The 10:30 first-name RMA book, the benchmark, is {bench} by day 3. "
            f"On the mornings both books have a day-3 result, this book is {paired} versus that one."
        )
        lines.append("")
    if not panels:
        return
    lines.append(
        "Average % and average R give each morning one vote. Expectancy, win rate, the stop-hit rate, "
        "and best, median, and worst are per fill. vs QQQ is that morning's stop-aware percent minus QQQ "
        "held from the same minute, with no stop on QQQ. vs 10:30 first is the paired excess in R against "
        "the 10:30 first-name RMA book."
    )
    for panel in panels:
        ids = [book_id for book_id in panel.get("books") or [] if book_id in books]
        if not ids:
            continue
        lines.extend(["", f"### {panel['title']}", ""])
        bits = []
        for book_id in ids:
            book = books[book_id]
            when = book.get("avg_entry") or "—"
            median = book.get("median_entry")
            clock = when if not median or median == when else f"{when} on average (median {median})"
            counts = book.get("pattern_counts") or {}
            mix = ", ".join(f"{name} {counts.get(name, 0)}" for name in _STRAT_PATTERNS)
            share = "—" if book.get("finished_2u_rate") is None else f"{book['finished_2u_rate'] * 100:.0f}%"
            bits.append(
                f"**{book['label']}** enters at {clock} with an average stop {_dist(book.get('avg_stop_pct'))} "
                f"under the entry ({mix}; finished as 2U {share})"
            )
        lines.append("; ".join(bits) + ".")
        lines.append("")
        labels = [books[book_id]["label"] for book_id in ids]
        lines.append("| | " + " | ".join(labels) + " |")
        lines.append("| --- | " + " | ".join("---:" for _ in labels) + " |")
        for name, title in HORIZON_LABEL.items():
            for key, metric, fmt in _STRAT_METRICS:
                cells = [fmt((books[book_id].get("horizons") or {}).get(name, {}).get(key)) for book_id in ids]
                lines.append(f"| {title} {metric} | " + " | ".join(cells) + " |")


def _append_cross(lines: list[str], stats: dict) -> None:
    cross = stats.get("cross_trigger") or {}
    books = cross.get("books") or {}
    order = [book_id for book_id in (cross.get("order") or []) if book_id in books]
    lines.extend(["", "## RMA cross trigger", ""])
    if cross.get("definition"):
        lines.append(cross["definition"])
        lines.append("")
    lines.append(
        "Opened above means the open of the first regular-session bar, the 9:30 print, is strictly "
        "above the average carried in from the prior session, before today's bars update it. Those "
        "names are still bought at the first bar at or after 9:45 that closes above the average. "
        "They are counted below. A name that never closes above the average is not bought."
    )
    lines.append("")
    lines.append(
        "The stop is the low of that entry bar, which is final once the bar has closed. The entry bar "
        "is not a stop. A later 5-minute bar at or below the stop exits at the stop. A bar that opens "
        "below the stop exits at the open and can book worse than −1R. A bar whose low is not strictly "
        "under its close has no risk, so it is skipped and the scan keeps looking for a later bar that day. "
        "Trades per day includes tape sessions where nobody triggered."
    )
    lines.append("")
    best = cross.get("best")
    benchmark = cross.get("benchmark") or {}
    ready = [
        book_id
        for book_id in order
        if (books[book_id].get("horizons") or {}).get("eod", {}).get("n_days")
    ]
    if not best or not ready:
        lines.append("Not enough completed holds for the cross-trigger study yet.")
        return
    bench = _r(benchmark.get("avg_r"))
    paired = _r(best.get("vs_rma_first"))
    lines.append(
        f"**{best['label']}** is the best of these books by day 3 at {_r(best['avg_r'])} per morning "
        f"(n = {best['n_days']} mornings / {best['n_trades']} fills). "
        f"The 10:30 first-name RMA book, the benchmark, is {bench} by day 3. "
        f"On the mornings both books have a day-3 result, this book is {paired} versus that one."
    )
    lines.append("")
    lines.append(
        "Average % and average R give each morning one vote. Expectancy, win rate, the stop-hit rate, "
        "and best, median, and worst are per fill. vs QQQ is that morning's stop-aware percent minus QQQ "
        "held from the same minute, with no stop on QQQ. vs 10:30 first is the paired excess in R against "
        "the 10:30 first-name RMA book."
    )
    lines.append("")
    bits = []
    for book_id in order:
        book = books[book_id]
        when = book.get("avg_entry") or "—"
        median = book.get("median_entry")
        clock = when if not median or median == when else f"{when} on average (median {median})"
        opened = book.get("opened_above")
        fills = book.get("n_fills")
        per = book.get("trades_per_day")
        per_text = "—" if per is None else f"{per:.1f}"
        bits.append(
            f"**{book['label']}** enters at {clock} with an average stop {_dist(book.get('avg_stop_pct'))} "
            f"under the entry ({opened} of {fills} opened above the average; {per_text} trades per tape day)"
        )
    lines.append("; ".join(bits) + ".")
    lines.append("")
    labels = [books[book_id]["label"] for book_id in order]
    lines.append("| | " + " | ".join(labels) + " |")
    lines.append("| --- | " + " | ".join("---:" for _ in labels) + " |")
    for name, title in HORIZON_LABEL.items():
        for key, metric, fmt in _STRAT_METRICS:
            cells = [fmt((books[book_id].get("horizons") or {}).get(name, {}).get(key)) for book_id in order]
            lines.append(f"| {title} {metric} | " + " | ".join(cells) + " |")


def _append_reclaim(lines: list[str], stats: dict) -> None:
    reclaim = stats.get("ema_reclaim") or {}
    books = reclaim.get("books") or {}
    panels = reclaim.get("panels") or []
    lines.extend(["", "## EMA pullback reclaim", ""])
    if reclaim.get("definition"):
        lines.append(reclaim["definition"])
        lines.append("")
    lines.append(
        "A pullback is a 5-minute bar in today's session whose close is strictly below the 20 EMA. "
        "The reclaim is the next bar whose close is strictly back above it. Close equal to the EMA is "
        "neither. The pullback can start before 9:45, including on the 9:35 bar. The reclaim bar itself "
        "has to end at 9:45 or later. A reclaim before 9:45 is not stored for later: that episode is over, "
        "and a name that stays above the EMA after it is not bought."
    )
    lines.append("")
    lines.append(
        "The pullback stop is the lowest low from the first close-below bar of that episode through the "
        "reclaim bar, including the reclaim bar. The low-of-day stop is the lowest low from 9:30 through "
        "the entry bar, so a low from before the pullback counts. The entry bar is not a stop. A later "
        "5-minute bar at or below the stop exits at the stop. A bar that opens below the stop exits at "
        "the open and can book worse than −1R. A stop that is not strictly under the entry is dropped "
        "for that variant only. Trades per day includes tape sessions where nobody reclaimed. The first "
        "name is the earliest reclaim, then the symbol."
    )
    lines.append("")
    best = reclaim.get("best")
    benchmark = reclaim.get("benchmark") or {}
    if not best:
        lines.append("Not enough completed holds for the EMA pullback-reclaim study yet.")
    else:
        bench = _r(benchmark.get("avg_r"))
        paired = _r(best.get("vs_rma_first"))
        lines.append(
            f"**{best['label']}** is the best of these books by day 3 at {_r(best['avg_r'])} per morning "
            f"(n = {best['n_days']} mornings / {best['n_trades']} fills). "
            f"The 10:30 first-name RMA book, the benchmark, is {bench} by day 3. "
            f"On the mornings both books have a day-3 result, this book is {paired} versus that one."
        )
        lines.append("")
    if not panels:
        return
    lines.append(
        "Average % and average R give each morning one vote. Expectancy, win rate, the stop-hit rate, "
        "and best, median, and worst are per fill. vs QQQ is that morning's stop-aware percent minus QQQ "
        "held from the same minute, with no stop on QQQ. vs 10:30 first is the paired excess in R against "
        "the 10:30 first-name RMA book."
    )
    for panel in panels:
        ids = [book_id for book_id in panel.get("books") or [] if book_id in books]
        if not ids:
            continue
        lines.extend(["", f"### {panel['title']}", ""])
        bits = []
        for book_id in ids:
            book = books[book_id]
            when = book.get("avg_entry") or "—"
            median = book.get("median_entry")
            clock = when if not median or median == when else f"{when} on average (median {median})"
            per = book.get("trades_per_day")
            per_text = "—" if per is None else f"{per:.1f}"
            bits.append(
                f"**{book['label']}** enters at {clock} with an average stop {_dist(book.get('avg_stop_pct'))} "
                f"under the entry ({per_text} trades per tape day)"
            )
        lines.append("; ".join(bits) + ".")
        lines.append("")
        labels = [books[book_id]["label"] for book_id in ids]
        lines.append("| | " + " | ".join(labels) + " |")
        lines.append("| --- | " + " | ".join("---:" for _ in labels) + " |")
        for name, title in HORIZON_LABEL.items():
            for key, metric, fmt in _STRAT_METRICS:
                cells = [fmt((books[book_id].get("horizons") or {}).get(name, {}).get(key)) for book_id in ids]
                lines.append(f"| {title} {metric} | " + " | ".join(cells) + " |")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Write the morning-leader backtest report")
    parser.add_argument("--out", type=Path, default=config.DATA_DIR / "morning_report.md")
    args = parser.parse_args(argv)
    stats = cached_stats()
    meta = counts()
    text = render(stats, meta)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text)
    print(text)
    print(f"\nWrote {args.out}", flush=True)


if __name__ == "__main__":
    main()
