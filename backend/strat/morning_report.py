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
    lines.append("")
    return "\n".join(lines)


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
