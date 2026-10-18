"""Write the morning-leader backtest report from the local database.

``python -m strat.morning_report`` prints the summary and writes ``backend/data/morning_report.md``.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from . import config
from .intraday import YAHOO_15M_LOOKBACK_DAYS
from .morning import PRIMARY_HORIZON, WINDOW_IDS, definition_text, weights_from_env
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


def render(stats: dict, meta: dict) -> str:
    weights = stats.get("weights") or {}
    lines = [
        "# Morning leaders",
        "",
        "Which of the five morning check-ins is the best time to buy that day's leaders.",
        "Leaders are the scanner's top 10 stocks as of the **prior close**. The check-in rank uses only",
        "the 15-minute bars that have closed by that time. Nothing here looks ahead.",
        "",
        definition_text(weights_from_env()),
        "",
        "## What was collected",
        "",
        f"- Leader sessions stored: {meta['leader_days']} ({meta['leader_rows']} rows).",
        f"- 15-minute bars stored: {meta['bar_rows']} "
        f"({meta['bar_start'] or '—'} → {meta['bar_end'] or '—'}).",
        f"- Bar sources: {meta['bar_sources'] or 'none yet'}.",
        f"- Sessions with entry results: {meta['result_days']}.",
        f"- Yahoo 15-minute history is about the last {YAHOO_15M_LOOKBACK_DAYS} calendar days. "
        "Older sessions keep their leader snapshot and, once a backfill provider has filled them, their bars.",
        "",
        "Sample-size caveat: each morning's ten names move together, so 40 mornings are not 400 independent bets.",
        "The win rate and expectancy below are computed on the equal-weight basket of the day's top 10, one number per morning.",
        "A split inside the hold is adjusted out; it is not a loss.",
        "",
        "## By check-in",
        "",
        "EOD through +5d are close-to-close holds (no stop). Expectancy replaces the close with the candle-low stop once that low has been hit.",
        "The open row buys every leader at the session open. QQQ is the same clock-time hold. vs QQQ is the basket minus that hold.",
        "",
    ]
    header = "| Window | Days | EOD | +1d | +3d | +5d | Win +3d | Stop hit | Expectancy +3d | vs open +3d | vs QQQ +3d |"
    sep = "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
    lines.extend([header, sep])
    order = ["open", *WINDOW_IDS]
    for window in order:
        block = (stats.get("windows") or {}).get(window)
        if not block:
            continue
        h = block["horizons"]
        label = "Open" if window == "open" else window
        lines.append(
            "| "
            + " | ".join(
                [
                    label,
                    str(h["d3"]["n_days"] or h["eod"]["n_days"]),
                    _pct(h["eod"]["avg"]),
                    _pct(h["d1"]["avg"]),
                    _pct(h["d3"]["avg"]),
                    _pct(h["d5"]["avg"]),
                    _rate(h["d3"]["win_rate"]),
                    _rate(h["d3"]["stop_hit_rate"]) if window != "open" else "—",
                    _pct(h["d3"]["expectancy"]) if window != "open" else _pct(h["d3"]["avg"]),
                    _pct(block["vs_open"].get("d3")) if window != "open" else "—",
                    _pct(block["vs_qqq"].get("d3")),
                ]
            )
            + " |"
        )
    best = stats.get("best")
    open_days = ((stats.get("windows") or {}).get("open") or {}).get("horizons", {}).get("d3", {}).get("n_days") or 0
    checkin_days = [
        ((stats.get("windows") or {}).get(w) or {}).get("horizons", {}).get("d3", {}).get("n_days") or 0 for w in WINDOW_IDS
    ]
    widest = max(checkin_days) if checkin_days else 0
    if open_days and widest and open_days > widest + 5:
        lines.extend(
            [
                "",
                f"The open row is {open_days} mornings of daily data. The five check-ins are {widest} mornings, "
                "which is as far as the 15-minute bars go. \"vs open\" and \"vs QQQ\" use only the mornings both sides have.",
                "",
            ]
        )
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
            f"A stop at that candle's low was hit {_rate(best['stop_hit_rate'])} of the time by {horizon}. "
            f"The stop-aware expectancy is {_pct(best['expectancy'])}. "
            "The stop is one 15-minute wick, so it sits close to the fill."
        )
        lines.append("")
        lines.append(
            f"Against buying the same names at the open: {_pct(best.get('vs_open'))}. "
            f"Against holding QQQ from the same minute: {_pct(best.get('vs_qqq'))}."
        )
        lines.append("")
        lines.append(
            "That is a description of this sample, not a promise. Overlapping holds, a short window, and "
            "today's index membership (survivorship) all apply."
        )
    lines.extend(
        [
            "",
            "## Weights",
            "",
            f"- Move from the open: {weights.get('move', 1)}",
            f"- Excess versus QQQ: {weights.get('vs_qqq', 1)}",
            f"- Opening-range position: {weights.get('opening_range', 1)}",
            "",
            "Change them with `STRAT_MORNING_W_MOVE`, `STRAT_MORNING_W_QQQ` and `STRAT_MORNING_W_OR`, "
            "then `npm run morning:backfill` to rebuild ranks and outcomes from the stored bars.",
            "",
        ]
    )
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
