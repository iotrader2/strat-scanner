"""Read API for the Morning Leaders tab. Everything comes from SQLite; stats are cached in process."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Query

from . import config
from .intraday import today_et
from .morning import WINDOW_IDS, build_single_stats, build_stats, definition_text, single_entry_text
from .morning_store import (
    earliest_leader_date,
    latest_leader_date,
    leaders_between,
    ranks_between,
    results_between,
    revision,
    single_entries_between,
)

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
    single = build_single_stats(
        [row for row in single_rows if row["rule"] != "qqq"],
        [row for row in single_rows if row["rule"] == "qqq"],
    )
    single["definition"] = single_entry_text()
    public = _round({k: v for k, v in stats.items() if k != "qqq_at_best"})
    public["definition"] = definition_text()
    public["single_entry"] = _round(single)
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
