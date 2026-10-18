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


def _pct(value, digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:+.{digits}f}%"


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
        "The win rate and expectancy below are the equal-weight basket of the names that qualified, one number per morning.",
        "Mornings when nobody had crossed are left out of the return columns and included in the qualified average.",
        "A split inside the hold is adjusted out; it is not a loss.",
        "",
        "## By check-in",
        "",
        "Qualified is the average number of the top 10 that had closed above the 20 RMA by that check-in, including mornings when the count was zero.",
        "EOD through +5d are close-to-close holds of the names that were bought. Expectancy replaces the close with the low-of-day stop once a later bar has traded below it.",
        "The stop is the session low from 9:30 through the entry bar. 9:45 is the earliest buy. QQQ is the same clock-time hold, without a stop. vs QQQ is the basket minus that hold.",
        "",
    ]
    header = "| Window | Days | Qualified | EOD | +1d | +3d | +5d | Win +3d | Stop hit | Expectancy +3d | vs QQQ +3d |"
    sep = "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
    lines.extend([header, sep])
    for window in WINDOW_IDS:
        block = (stats.get("windows") or {}).get(window)
        if not block:
            continue
        h = block["horizons"]
        lines.append(
            "| "
            + " | ".join(
                [
                    window,
                    str(h["d3"]["n_days"] or h["eod"]["n_days"]),
                    _count(block.get("avg_qualified")),
                    _pct(h["eod"]["avg"]),
                    _pct(h["d1"]["avg"]),
                    _pct(h["d3"]["avg"]),
                    _pct(h["d5"]["avg"]),
                    _rate(h["d3"]["win_rate"]),
                    _rate(h["d3"]["stop_hit_rate"]),
                    _pct(h["d3"]["expectancy"]),
                    _pct(block["vs_qqq"].get("d3")),
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
            f"**{best['window']}** has the highest average {horizon} close return: "
            f"{_pct(best['avg'])} per morning "
            f"({_rate(best['win_rate'])} of mornings positive, "
            f"n = {best['n_days']} mornings / {best['n_trades']} fills)."
        )
        lines.append("")
        lines.append(
            f"On average {_count(best.get('avg_qualified'))} of the ten leaders had closed above the 20 RMA by {best['window']}."
        )
        lines.append("")
        lines.append(
            f"A stop at the low of day through that bar was hit {_rate(best['stop_hit_rate'])} of the time by {horizon}. "
            f"The stop-aware expectancy is {_pct(best['expectancy'])}."
        )
        lines.append("")
        lines.append(f"Against holding QQQ from the same minute: {_pct(best.get('vs_qqq'))}.")
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
