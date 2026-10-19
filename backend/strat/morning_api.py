"""Read API for the Morning Leaders tab. Everything comes from SQLite; stats are cached in process."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Query

from . import config
from .intraday import today_et
from .cross_trigger import build_cross_stats, cross_text
from .ema_reclaim import build_reclaim_stats, reclaim_text
from .morning import WINDOW_IDS, build_single_stats, build_stats, definition_text, single_entry_text
from .morning_store import (
    cross_trigger_tape_days,
    cross_triggers_between,
    ema_reclaim_tape_days,
    ema_reclaims_between,
    stop_sweeps_between,
    strat_pullback_tape_days,
    strat_pullbacks_between,
    all_leaders,
    earliest_leader_date,
    latest_leader_date,
    leaders_between,
    ranks_between,
    results_between,
    revision,
    single_entries_between,
    strat_reversals_between,
)
from .stop_sweep import build_sweep_stats, load_rank_example
from .strat_pullback import build_pullback_stats, pullback_text
from .strat_reversal import build_reversal_stats, reversal_text

router = APIRouter()

_CACHE: dict = {"rev": None, "stats": None}
WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI")
MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _round(value):
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, dict):
        return {k: _round(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_round(v) for v in value]
    return value


def cached_stats(force: bool = False) -> dict:
    rev = f"{config.CACHE_DB}:{revision()}"
    if not force and _CACHE["rev"] == rev and _CACHE["stats"] is not None:
        return _CACHE["stats"]
    stats = build_stats(
        results_between("0000-01-01", "9999-12-31", role="leader"),
        results_between("0000-01-01", "9999-12-31", role="benchmark"),
        ranks_between("0000-01-01", "9999-12-31"),
    )
    single_rows = single_entries_between("0000-01-01", "9999-12-31")
    score_ranks: dict[str, dict[str, int]] = {}
    for leader in all_leaders():
        score_ranks.setdefault(leader["date"], {})[leader["symbol"]] = int(leader["rank"])
    single = build_single_stats(
        [row for row in single_rows if row["rule"] != "qqq"],
        [row for row in single_rows if row["rule"] == "qqq"],
        score_ranks,
    )
    single["definition"] = single_entry_text()
    reversal_rows = strat_reversals_between("0000-01-01", "9999-12-31")
    rma_first = [
        row for row in single_rows if row["rule"] == "rma1030" and int(row.get("rank") or 0) == 1
    ]
    reversal = build_reversal_stats(
        [row for row in reversal_rows if int(row.get("timeframe") or 0) != 0],
        [row for row in reversal_rows if int(row.get("timeframe") or 0) == 0],
        rma_first,
    )
    reversal["definition"] = reversal_text()
    cross_rows = cross_triggers_between("0000-01-01", "9999-12-31")
    cross = build_cross_stats(
        [row for row in cross_rows if row["rule"] != "qqq"],
        [row for row in cross_rows if row["rule"] == "qqq"],
        rma_first,
        cross_trigger_tape_days(),
    )
    cross["definition"] = cross_text()
    reclaim_rows = ema_reclaims_between("0000-01-01", "9999-12-31")
    reclaim = build_reclaim_stats(
        [row for row in reclaim_rows if row["rule"] != "qqq"],
        [row for row in reclaim_rows if row["rule"] == "qqq"],
        rma_first,
        ema_reclaim_tape_days(),
    )
    reclaim["definition"] = reclaim_text()
    pullback_rows = strat_pullbacks_between("0000-01-01", "9999-12-31")
    pullback = build_pullback_stats(
        pullback_rows,
        [row for row in single_rows if row["rule"] != "qqq"],
        score_ranks,
        strat_pullback_tape_days(),
    )
    pullback["definition"] = pullback_text()
    sweep_rows = stop_sweeps_between("0000-01-01", "9999-12-31")
    sweep = build_sweep_stats(sweep_rows)
    first_book = (sweep.get("books") or {}).get("first") or {}
    tight_id = first_book.get("tight")
    lod_r = (((first_book.get("stops") or {}).get("lod") or {}).get("horizons") or {}).get("d3", {}).get("r_per_trade")
    sweep["example"] = load_rank_example(
        [row for row in single_rows if row["rule"] == "rma1030"],
        score_ranks,
        sweep_rows,
        tight_id,
        book_avg=lod_r,
    )
    public = _round({k: v for k, v in stats.items() if k != "qqq_at_best"})
    public["definition"] = definition_text()
    public["single_entry"] = _round(single)
    public["strat_reversal"] = _round(reversal)
    public["cross_trigger"] = _round(cross)
    public["ema_reclaim"] = _round(reclaim)
    public["strat_pullback"] = _round(pullback)
    public["stop_sweep"] = _round(sweep)
    _CACHE["rev"] = rev
    _CACHE["stats"] = public
    return public


def week_payload(week: Optional[str] = None) -> dict:
    today = today_et()
    anchor = date.fromisoformat(week) if week else today
    monday = monday_of(anchor)
    days = [monday + timedelta(days=i) for i in range(5)]
    start, end = days[0].isoformat(), days[-1].isoformat()
    leaders = leaders_between(start, end)
    ranks = ranks_between(start, end)
    results = results_between(start, end, role="leader")

    by_day: dict[str, dict[str, dict]] = {}
    for row in leaders:
        by_day.setdefault(row["date"], {})[row["symbol"]] = {
            "rank": row["rank"],
            "symbol": row["symbol"],
            "name": row["name"],
            "score": row["score"],
            "rs": row["rs"],
            "as_of": row["as_of"],
            "windows": {},
        }
    rank_index = {(r["date"], r["window"], r["symbol"]): r for r in ranks}
    result_index = {(r["date"], r["window"], r["symbol"]): r for r in results}
    for (day, window, symbol), rank in rank_index.items():
        slot = by_day.get(day, {}).get(symbol)
        if slot is None:
            continue
        outcome = result_index.get((day, window, symbol), {})
        qualified = int(rank.get("qualified") or 0) == 1 and int(rank["rank"]) < 100
        slot["windows"][window] = {
            "rank": rank["rank"] if qualified else None,
            "qualified": 1 if qualified else 0,
            "cross_time": rank.get("cross_time"),
            "score": rank["score"],
            "day_move": rank["day_move"],
            "vs_qqq": rank["vs_qqq"],
            "or_position": rank["or_position"],
            "eod_ret": outcome.get("eod_ret"),
            "d1_ret": outcome.get("d1_ret"),
            "d2_ret": outcome.get("d2_ret"),
            "d3_ret": outcome.get("d3_ret"),
            "d4_ret": outcome.get("d4_ret"),
            "d5_ret": outcome.get("d5_ret"),
            "stopped": outcome.get("stopped"),
            "stop_day": outcome.get("stop_day"),
            "stop_ret": outcome.get("stop_ret"),
            "gapped": outcome.get("gapped"),
            "mfe": outcome.get("mfe"),
            "mae": outcome.get("mae"),
            "entry_price": outcome.get("entry_price"),
            "candle_low": outcome.get("candle_low"),
        }

    latest = latest_leader_date()
    earliest = earliest_leader_date()
    cap = monday_of(date.fromisoformat(latest)) if latest else monday
    prev = monday - timedelta(days=7)
    nxt = monday + timedelta(days=7)
    columns = []
    for day in days:
        key = day.isoformat()
        rows = sorted(by_day.get(key, {}).values(), key=lambda r: (r["rank"], r["symbol"]))
        columns.append(
            {
                "date": key,
                "weekday": WEEKDAYS[day.weekday()],
                "month_day": f"{MONTHS[day.month - 1]} {day.day}",
                "closed": not rows and key < today.isoformat() and (latest is None or key <= latest),
                "rows": _round(rows),
            }
        )
    return {
        "week_of": monday.isoformat(),
        "title": f"Week of {MONTHS[monday.month - 1].title()} {monday.day}, {monday.year}",
        "this_week": monday == monday_of(today),
        "prev": prev.isoformat() if earliest and monday_of(date.fromisoformat(earliest)) <= prev else None,
        "next": nxt.isoformat() if nxt <= cap else None,
        "windows": list(WINDOW_IDS),
        "days": columns,
        "stats": cached_stats(),
    }


@router.get("/api/morning")
def morning(week: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")):
    return week_payload(week)
