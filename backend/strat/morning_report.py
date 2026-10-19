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
    _append_pullback(lines, stats)
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
    _append_rma_caps(lines, single)
    lines.extend(_rma_example_lines())


_CAP_HEAD = {
    "rma_first": "First",
    "rma_first_rank": "First, rank tie",
    "rma_two": "First 2",
    "rma_three": "First 3",
    "rma_all": "All",
}


def _append_rma_caps(lines: list[str], single: dict) -> None:
    books = single.get("books") or {}
    caps = [book_id for book_id in (single.get("caps") or []) if book_id in books]
    if len(caps) < 2:
        return
    lines.extend(["", "### 10:30 RMA, first two and first three", ""])
    if single.get("caps_note"):
        lines.append(single["caps_note"])
        lines.append("")
    lines.append(
        "Every one of these buys at the 10:30 close. The stop is the low from 9:30 through that bar. "
        "One R is that distance. R per trade is the expectancy, the mean R per fill. Average R gives "
        "each morning one vote. First is the existing book. All is every name that had closed above "
        "the 20 RMA by 10:30."
    )
    lines.append("")
    stops = []
    for book_id in caps:
        book = books[book_id]
        stops.append(f"**{_CAP_HEAD.get(book_id, book['label'])}** stop {_dist(book.get('avg_stop_pct'))}")
    lines.append("Average stop under the entry: " + "; ".join(stops) + ".")
    lines.append("")
    labels = [_CAP_HEAD.get(book_id, books[book_id]["label"]) for book_id in caps]
    lines.append("| | " + " | ".join(labels) + " |")
    lines.append("| --- | " + " | ".join("---:" for _ in labels) + " |")
    for name, title in HORIZON_LABEL.items():
        for key, metric, fmt in _SINGLE_METRICS:
            cells = [fmt((books[book_id].get("horizons") or {}).get(name, {}).get(key)) for book_id in caps]
            lines.append(f"| {title} {metric} | " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("Average R from the close through day 5, one number per book in the column order above:")
    lines.append("")
    for book_id in caps:
        path = []
        for name in HORIZON_LABEL:
            path.append(_r((books[book_id].get("horizons") or {}).get(name, {}).get("avg_r")))
        lines.append(f"- **{_CAP_HEAD.get(book_id, book_id)}**: " + ", ".join(path) + ".")


def _rma_example_lines() -> list[str]:
    """One stored 10:30 first-name morning, the recent typical one, written out bar by bar."""
    from datetime import date, timedelta

    import pandas as pd

    from .data import load_all_daily
    from .morning import (
        first_stop_bar,
        format_clock,
        pick_typical_rma_first,
        realized_lod_r,
        realized_pct,
        rma_at,
        to_pct,
        window_end,
    )
    from .morning_store import all_leaders, load_bars, single_entries_between

    rows = [row for row in single_entries_between("0000-01-01", "9999-12-31") if row.get("rule") == "rma1030"]
    picked = pick_typical_rma_first(rows)
    if not picked:
        return []
    row = picked["row"]
    day = str(row["date"])
    symbol = str(row["symbol"])
    leaders = [item for item in all_leaders() if item["date"] == day]
    by_symbol = {item["symbol"]: item for item in leaders}
    symbols = [item["symbol"] for item in leaders] or [symbol]
    if symbol not in symbols:
        symbols.append(symbol)
    start = (date.fromisoformat(day) - timedelta(days=40)).isoformat()
    end = (date.fromisoformat(day) + timedelta(days=21)).isoformat()
    bars = load_bars(symbols, start, end, interval="5m")
    daily = load_all_daily()
    qqq = daily.get("QQQ")
    calendar = [] if qqq is None or qqq.empty else [pd.Timestamp(ts).strftime("%Y-%m-%d") for ts in qqq.index]
    forward = [pd.Timestamp(stamp) for stamp in calendar if stamp > day][:5]
    entry_end = window_end(day, "10:30")
    reading = rma_at(bars.get(symbol), entry_end)
    leader = by_symbol.get(symbol) or {}
    rank = leader.get("rank")
    name = leader.get("name") or symbol
    entry = float(row["entry_price"])
    stop = float(row["stop_price"])
    risk = entry - stop
    cross_clock = "—"
    cross_close = None
    rma_value = None
    if reading is not None:
        cross_ts, cross_close, rma_value = reading
        cross_clock = format_clock(cross_ts.hour * 60 + cross_ts.minute) or "—"
    touch = first_stop_bar(bars.get(symbol), entry_end, stop, forward) if row.get("stopped") else None
    day_rows = [item for item in rows if item["date"] == day]
    score = {item["symbol"]: int(item["rank"]) for item in leaders}

    def _rank_key(item):
        return (str(item.get("cross_time") or ""), score.get(item["symbol"], 10**9), item["symbol"])

    rank_order = sorted(day_rows, key=_rank_key)
    symbol_order = sorted(day_rows, key=lambda item: (int(item.get("rank") or 99), item["symbol"]))
    qualified = {item["symbol"] for item in day_rows}
    lines = ["", "### One 10:30 first morning", ""]
    lines.append(
        f"**{day}**, **{symbol}** ({name}), prior-close leader rank {rank}. "
        f"Day 3 on this fill is {_r(picked['day3_r'])}, the median of the {picked['pool_n']} completed "
        f"first fills other than the best, {_r(picked['best_r'])} on {picked['best_date']}. "
        f"It is the most recent fill in that typical group with a day-5 close. "
        f"It is the existing First book: earliest cross, then the symbol. "
        + (
            "The rank tie-break picks the same name that morning."
            if not rank_order or rank_order[0]["symbol"] == symbol
            else f"The rank tie-break that morning would have bought {rank_order[0]['symbol']} first."
        )
    )
    lines.append("")
    if reading is None:
        lines.append(f"The stored cross is {row.get('cross_time')}. The 5-minute bars for that RMA were not on hand.")
    else:
        lines.append(
            f"The first 5-minute bar of the session to close above the 20 RMA ended at {cross_clock}. "
            f"That close was {_px(cross_close)} and the RMA was {_px(rma_value)}."
        )
    lines.append(
        f"The entry is the 10:30 close, {_px(entry)}. "
        f"The stop is the low from 9:30 through that bar, {_px(stop)}. "
        f"The stop sits {_dist(row.get('stop_pct'))} under the entry, so 1R is {_px(risk)}."
    )
    lines.append("")
    if int(row.get("stopped") or 0) and touch is not None:
        when = _stop_when(touch, day, forward)
        how = "opened through the stop" if touch["gapped"] else "traded down to the stop"
        exit_at = touch["open"] if touch["gapped"] else stop
        lines.append(
            f"The stop was hit {when}. The bar {how} "
            f"(open {_px(touch['open'])}, low {_px(touch['low'])}) and the exit is {_px(exit_at)}."
        )
    elif int(row.get("stopped") or 0):
        lines.append(
            f"The stop was hit on session offset {row.get('stop_day')}. "
            f"The 5-minute bar that touched it was not in the stored tape, so the clock is the stored stop day."
        )
    else:
        lines.append("The stop was not hit through the day-5 close.")
    lines.append("")
    lines.append(
        "The close columns are the session close against the entry, with no stop. "
        "The booked columns are what the study keeps: from the stop session on, the exit."
    )
    lines.append("")
    lines.append("| | Date | Close | Close % | Close R | Booked % | Booked R |")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: |")
    horizon_days = [("eod", day)] + [(name, pd.Timestamp(stamp).strftime("%Y-%m-%d")) for name, stamp in zip(("d1", "d2", "d3", "d4", "d5"), forward)]
    frame = daily.get(symbol)
    risk_pct = row.get("stop_pct")
    for horizon, stamp in horizon_days:
        close = _daily_close(frame, stamp)
        close_pct = to_pct(entry, close)
        close_r = None if close_pct is None or not risk_pct else close_pct / float(risk_pct)
        lines.append(
            f"| {HORIZON_LABEL[horizon]} | {stamp} | {_px(close) if close is not None else '—'} | "
            f"{_pct(close_pct)} | {_r(close_r)} | {_pct(realized_pct(row, horizon))} | {_r(realized_lod_r(row, horizon))} |"
        )
    lines.append("")
    lines.append(
        "Qualified that morning, in the existing symbol order, then the rank order. "
        "A name qualifies when a 5-minute bar has closed above the 20 RMA by 10:30 and the low from "
        "9:30 through 10:30 is under that close."
    )
    lines.append("")
    lines.append(_name_list("Symbol order", symbol_order, by_symbol))
    lines.append(_name_list("Rank order", rank_order, by_symbol))
    skipped = [item for item in leaders if item["symbol"] not in qualified]
    if not skipped:
        lines.append("")
        lines.append("Every top-10 name qualified.")
        return lines
    lines.append("")
    lines.append("Skipped:")
    lines.append("")
    for item in skipped:
        reason = _skip_reason(bars.get(item["symbol"]), entry_end)
        lines.append(f"- **{item['symbol']}** ({item.get('name') or item['symbol']}), leader rank {item['rank']}: {reason}.")
    return lines


def _name_list(title: str, rows: list, leaders: dict) -> str:
    bits = []
    for item in rows:
        leader = leaders.get(item["symbol"]) or {}
        bits.append(
            f"{item['symbol']} rank {leader.get('rank', '—')} at {item.get('cross_time')}"
        )
    return f"**{title}:** " + "; ".join(bits) + "."


def _daily_close(frame, day: str):
    import pandas as pd

    if frame is None or frame.empty:
        return None
    stamp = pd.Timestamp(day).normalize()
    if stamp not in frame.index:
        return None
    close = frame.loc[stamp].close
    try:
        value = float(close)
    except (TypeError, ValueError):
        return None
    return None if value != value else value


def _px(value) -> str:
    if value is None:
        return "—"
    return f"${float(value):,.2f}"


def _stop_when(touch: dict, day: str, forward: list) -> str:
    import pandas as pd

    from .morning import format_clock

    offset = int(touch["day_index"])
    if offset == 0:
        session = day
        label = "on the entry session"
    elif offset <= len(forward):
        session = pd.Timestamp(forward[offset - 1]).strftime("%Y-%m-%d")
        label = f"on the +{offset} session"
    else:
        session = "a later session"
        label = "later"
    clock = format_clock(touch["ts"].hour * 60 + touch["ts"].minute)
    return f"{label} ({session}), the 5-minute bar ending {clock}"


_PB_DAY3 = (
    ("n_days", "days", _num),
    ("n_trades", "fills", _num),
    ("avg_pct", "avg %", _pct),
    ("avg_r", "avg R", _r),
    ("win_rate", "win", _rate),
    ("stop_hit_rate", "stop", _rate),
    ("total_r", "total R", lambda value: _r(value, 1)),
    ("expectancy", "R per trade", _r),
    ("avg_mfe", "avg MFE", _r),
    ("best_r", "best R", _r),
    ("worst_r", "worst R", _r),
    ("vs_rank_first", "vs 10:30 first", _r),
    ("vs_rank_two", "vs 10:30 first 2", _r),
)

_PB_COL = {
    "pb1100_first": "First",
    "pb1100_two": "First 2",
    "pb1100_three": "First 3",
    "pb1100_all": "All",
    "pb1030_first": "First",
    "pb1030_two": "First 2",
    "pb1030_three": "First 3",
    "pb1030_all": "All",
}
_PB_REF = {
    "rma_first_rank": "10:30 first",
    "rma_two": "10:30 first 2",
    "rma_three": "10:30 first 3",
    "rma_all": "10:30 all",
}


def _dollars(value) -> str:
    if value is None:
        return "—"
    return f"${float(value):,.2f}"


def _append_pullback(lines: list[str], stats: dict) -> None:
    study = stats.get("strat_pullback") or {}
    books = study.get("books") or {}
    single = (stats.get("single_entry") or {}).get("books") or {}
    panels = study.get("panels") or []
    lines.extend(["", "## 5-minute Strat pullback", ""])
    if study.get("definition"):
        lines.append(study["definition"])
        lines.append("")
    lines.append(
        "The name has to close above the 20 RMA first. The pullback is a later 5-minute bar that is a "
        "2D or an inside, and the buy is the first trade above that bar's high. A 2U straight after a "
        "3 is not a pullback. A bar that opens above the prior high fills at the open, and that fill is "
        "known at the bar's start, so the bar that ends five minutes after the cutoff can still fill "
        "at its open. A through-trade is known at the bar's end. The earliest fill is 9:45. One trade "
        "per name per day. The stop is the low from 9:30 through the entry bar, including that bar's "
        "low. The entry bar is not a stop. A later bar at or below the stop exits at the stop. A bar "
        "that opens below the stop exits at the open."
    )
    lines.append("")
    lines.append(
        "First, first 2, and first 3 are the best leader-list ranks among the names that actually "
        "filled. Rank 1 is the best prior-close score. A name that never triggers does not take a slot. "
        "The columns beside them are the 10:30 rank-tie books, bought at the 10:30 close with the same "
        "low-of-day stop. Risk per share is the entry minus that stop. The entry comparison is the "
        "10:30 price minus this fill, as a percent of the 10:30 price, averaged over the names that "
        "have both fills. Positive means the pullback fill was lower."
    )
    lines.append("")
    best = study.get("best")
    benchmark = study.get("benchmark") or {}
    if not best:
        lines.append("Not enough completed holds for the 5-minute Strat pullback study yet.")
    else:
        first = (benchmark.get("first") or {}).get("avg_r")
        two = (benchmark.get("two") or {}).get("avg_r")
        paired = best.get("vs_rank_first")
        lines.append(
            f"**{best['label']}** is the best of these pullback books by day 3 at {_r(best['avg_r'])} "
            f"per morning (n = {best['n_days']} mornings / {best['n_trades']} fills). "
            f"The 10:30 rank-tie first book is {_r(first)} by day 3, and its first 2 is {_r(two)}. "
            f"On the mornings both have a day-3 result, this book is {_r(paired)} versus the rank-tie first book."
        )
        lines.append("")
    if not panels:
        lines.extend(_pullback_example_lines())
        return
    for panel in panels:
        ids = [book_id for book_id in panel.get("books") or [] if book_id in books]
        refs = list(panel.get("refs") or [])
        columns = []
        for index, book_id in enumerate(ids):
            columns.append(("pullback", book_id))
            if index < len(refs) and refs[index] in single:
                columns.append(("rma", refs[index]))
        if not columns:
            continue
        lines.extend(["", f"### {panel['title']}", ""])
        bits = []
        for book_id in ids:
            book = books[book_id]
            when = book.get("avg_entry") or "—"
            median = book.get("median_entry")
            clock = when if not median or median == when else f"{when} on average (median {median})"
            saved = _pct(book.get("avg_entry_saved_pct"))
            bits.append(
                f"**{_PB_COL.get(book_id, book['label'])}** enters at {clock} with an average stop "
                f"{_dist(book.get('avg_stop_pct'))} under the entry, {_dollars(book.get('avg_risk_dollars'))} "
                f"of risk per share against {_dollars(book.get('avg_rma_risk_dollars'))} at the 10:30 entry "
                f"({saved} versus that price, positive means a lower fill, n = {book.get('n_paired') or 0})"
            )
        lines.append("; ".join(bits) + ".")
        lines.append("")
        labels = []
        for kind, book_id in columns:
            if kind == "pullback":
                labels.append(_PB_COL.get(book_id, books[book_id]["label"]))
            else:
                labels.append(_PB_REF.get(book_id, single[book_id].get("label") or book_id))
        lines.append("Day 3, side by side. Average % and average R give each morning one vote. R per trade, win, stop, total R, MFE, and best and worst are per fill.")
        lines.append("")
        lines.append("| | " + " | ".join(labels) + " |")
        lines.append("| --- | " + " | ".join("---:" for _ in labels) + " |")
        for key, metric, fmt in _PB_DAY3:
            cells = []
            for kind, book_id in columns:
                source = books if kind == "pullback" else single
                cells.append(fmt((source[book_id].get("horizons") or {}).get("d3", {}).get(key)))
            lines.append(f"| Day 3 {metric} | " + " | ".join(cells) + " |")
        lines.append("")
        lines.append("Average R from the close through day 5:")
        lines.append("")
        for kind, book_id in columns:
            source = books if kind == "pullback" else single
            title = labels[columns.index((kind, book_id))]
            path = [_r((source[book_id].get("horizons") or {}).get(name, {}).get("avg_r")) for name in HORIZON_LABEL]
            lines.append(f"- **{title}** R: " + ", ".join(path) + ".")
        lines.append("")
        lines.append("Average percent from the close through day 5:")
        lines.append("")
        for kind, book_id in columns:
            source = books if kind == "pullback" else single
            title = labels[columns.index((kind, book_id))]
            path = [_pct((source[book_id].get("horizons") or {}).get(name, {}).get("avg_pct")) for name in HORIZON_LABEL]
            lines.append(f"- **{title}** %: " + ", ".join(path) + ".")
    lines.extend(_pullback_example_lines())


def _pullback_example_lines() -> list[str]:
    """The 2026-10-09 CRWD pullback, the same morning as the 10:30 first example."""
    from datetime import date, timedelta

    import pandas as pd

    from .data import load_all_daily
    from .morning import first_stop_bar, format_clock, realized_lod_r, realized_pct, rma_at, to_pct
    from .morning_store import all_leaders, load_bars, single_entries_between, strat_pullbacks_between
    from .strat_pullback import first_pullback, prepare_pullbacks

    day = "2026-10-09"
    symbol = "CRWD"
    stored = [
        row for row in strat_pullbacks_between(day, day)
        if row.get("symbol") == symbol and row.get("cutoff") in ("11:00", "10:30")
    ]
    row = next((item for item in stored if item.get("cutoff") == "11:00"), None)
    if row is None:
        return []
    other = next((item for item in stored if item.get("cutoff") == "10:30"), None)
    rma = next(
        (
            item for item in single_entries_between(day, day)
            if item.get("symbol") == symbol and item.get("rule") == "rma1030"
        ),
        None,
    )
    leaders = [item for item in all_leaders() if item["date"] == day and item["symbol"] == symbol]
    leader = leaders[0] if leaders else {}
    start = (date.fromisoformat(day) - timedelta(days=40)).isoformat()
    end = (date.fromisoformat(day) + timedelta(days=21)).isoformat()
    bars = load_bars([symbol], start, end, interval="5m")
    daily = load_all_daily()
    qqq = daily.get("QQQ")
    calendar = [] if qqq is None or qqq.empty else [pd.Timestamp(ts).strftime("%Y-%m-%d") for ts in qqq.index]
    forward = [pd.Timestamp(stamp) for stamp in calendar if stamp > day][:5]
    prepared = prepare_pullbacks(bars, [symbol])
    found = first_pullback(prepared.get(symbol), day, "11:00", bars.get(symbol))
    entry = float(row["entry_price"])
    stop = float(row["stop_price"])
    risk = entry - stop
    clock = format_clock(int(str(row["entry_time"])[:2]) * 60 + int(str(row["entry_time"])[3:5])) or row["entry_time"]
    entry_end = found["entry_end"] if found else pd.Timestamp(f"{day} {row['entry_time']}")
    reading = rma_at(bars.get(symbol), entry_end)
    touch = first_stop_bar(bars.get(symbol), entry_end, stop, forward) if row.get("stopped") else None
    frame = bars.get(symbol)
    prior_high = None
    trigger_open = None
    trigger_high = None
    if found is not None and frame is not None and entry_end in frame.index:
        loc = frame.index.get_loc(entry_end)
        if isinstance(loc, int) and loc > 0:
            prior_high = float(frame.iloc[loc - 1].high)
            trigger_open = float(frame.iloc[loc].open)
            trigger_high = float(frame.iloc[loc].high)
    lines = ["", "### CRWD on 2026-10-09, the 5-minute pullback", ""]
    rank = leader.get("rank")
    name = leader.get("name") or symbol
    lines.append(
        f"**{day}**, **{symbol}** ({name}), prior-close leader rank {rank}. "
        "This is the same morning as the 10:30 first example. The pullback buys the break of the "
        "pullback bar instead of waiting for the 10:30 close. Rank 7 is not the first name that day; "
        "the example is this trade."
    )
    lines.append("")
    if reading is None:
        lines.append("The 5-minute bars for the RMA cross were not on hand.")
    else:
        cross_ts, cross_close, rma_value = reading
        cross_clock = format_clock(cross_ts.hour * 60 + cross_ts.minute) or "—"
        lines.append(
            f"The first 5-minute bar of the session to close above the 20 RMA ended at {cross_clock}. "
            f"That close was {_px(cross_close)} and the RMA was {_px(rma_value)}."
        )
    lines.append("")
    if prior_high is not None:
        lines.append(
            f"The bar before the trigger made a high of {_px(prior_high)}. "
            f"The trigger bar opened at {_px(trigger_open)} and traded up to {_px(trigger_high)}. "
            f"The open is under that prior high, so the fill is the prior high, {_px(entry)}, at {clock}. "
            f"The pattern is {row.get('pattern')}."
        )
    else:
        lines.append(
            f"The fill is {_px(entry)} at {clock}, pattern {row.get('pattern')}."
        )
    if abs(entry - 263.79) < 0.05:
        lines.append("")
        lines.append("That prior high is the price described as about $263.79.")
    lines.append("")
    lines.append(
        f"The stop is the low from 9:30 through the entry bar, {_px(stop)}. "
        f"It sits {_dist(row.get('stop_pct'))} under the entry, so 1R is {_dollars(risk)}. "
        "A stop this tight turns a small dollar move into a large R until the stop books −1R."
    )
    lines.append("")
    if rma is not None and rma.get("entry_price") is not None and rma.get("stop_price") is not None:
        rma_entry = float(rma["entry_price"])
        rma_risk = rma_entry - float(rma["stop_price"])
        saved = (rma_entry - entry) / rma_entry * 100.0 if rma_entry else None
        lines.append(
            f"The 10:30 entry on this name is {_px(rma_entry)}, with the same stop at {_px(rma['stop_price'])} "
            f"and 1R of {_dollars(rma_risk)}. This fill is {_dollars(rma_entry - entry)} lower, "
            f"{_pct(saved)} of the 10:30 price, and risks {_dollars(risk)} a share instead of {_dollars(rma_risk)}."
        )
        lines.append("")
    if other is not None and other.get("entry_time") == row.get("entry_time") and abs(float(other["entry_price"]) - entry) < 1e-6:
        lines.append("The 10:30 cutoff keeps this same trade, because the fill is before 10:30.")
    elif other is None:
        lines.append("The 10:30 cutoff does not include this trade.")
    lines.append("")
    if int(row.get("stopped") or 0) and touch is not None:
        when = _stop_when(touch, day, forward)
        how = "opened through the stop" if touch["gapped"] else "traded down to the stop"
        exit_at = touch["open"] if touch["gapped"] else stop
        lines.append(
            f"The stop was hit {when}. The bar {how} "
            f"(open {_px(touch['open'])}, low {_px(touch['low'])}) and the exit is {_px(exit_at)}."
        )
    elif int(row.get("stopped") or 0):
        lines.append(
            f"The stop was hit on session offset {row.get('stop_day')}. "
            "The 5-minute bar that touched it was not in the stored tape."
        )
    else:
        lines.append("The stop was not hit through the day-5 close.")
    lines.append("")
    lines.append(
        "The close columns are the session close against this entry, with no stop. "
        "The booked columns are what the study keeps: from the stop session on, the exit."
    )
    lines.append("")
    lines.append("| | Date | Close | Close % | Close R | Booked % | Booked R |")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: |")
    horizon_days = [("eod", day)] + [
        (name, pd.Timestamp(stamp).strftime("%Y-%m-%d")) for name, stamp in zip(("d1", "d2", "d3", "d4", "d5"), forward)
    ]
    daily_frame = daily.get(symbol)
    risk_pct = row.get("stop_pct")
    for horizon, stamp in horizon_days:
        close = _daily_close(daily_frame, stamp)
        close_pct = to_pct(entry, close)
        close_r = None if close_pct is None or not risk_pct else close_pct / float(risk_pct)
        lines.append(
            f"| {HORIZON_LABEL[horizon]} | {stamp} | {_px(close) if close is not None else '—'} | "
            f"{_pct(close_pct)} | {_r(close_r)} | {_pct(realized_pct(row, horizon))} | {_r(realized_lod_r(row, horizon))} |"
        )
    return lines


def _skip_reason(bars, entry_end) -> str:
    from .morning import cross_through, entry_at, session_low_through

    if bars is None or bars.empty:
        return "no stored 5-minute bars"
    cross = cross_through(bars, entry_end)
    if cross is None:
        return "no 5-minute close above the 20 RMA by 10:30"
    price = entry_at(bars, entry_end)
    if price is None:
        return "no 10:30 bar"
    stop = session_low_through(bars, entry_end)
    if stop is None or stop >= price:
        return "the low from 9:30 through 10:30 was not under the 10:30 close"
    return "it met the rule and was still left out of the stored book"


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
        "for that variant only, and a later name does not move up to fill the cap. Trades per day "
        "includes tape sessions where nobody reclaimed."
    )
    lines.append("")
    lines.append(
        "First, first 2, and first 3 are the earliest reclaims that day. A tie on the reclaim bar goes "
        "to the better leader-list rank, rank 1 ahead of rank 2, because that rank is the prior-close "
        "leadership score. The symbol breaks a remaining tie. The same order picks the single first name."
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
