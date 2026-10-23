"""State-of-the-market breadth: $NASI, CNN Fear & Greed, and the scanner's own universe.

$NASI is the Nasdaq McClellan Summation Index, read from StockCharts' public quote history.
Fear & Greed is CNN's index. Each of those is cached for a few minutes and a failed refresh
keeps the last good reading.

Advancers versus decliners, and 52-week new highs versus new lows, count the symbols this
scanner already tracks (the scan rows), using the daily bars the background fetcher has cached.

Nasdaq advancers versus decliners (all Nasdaq-listed issues) come from the WSJ markets diary.
They are fetched by the background job (``refresh_nasdaq_issues``, on the price-refresh cadence),
never by a page request, and shown only for the same session as the universe counts. A failed
fetch keeps the last real reading; with none, the line is hidden. Nothing is estimated.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta
from typing import Callable, Mapping, Optional

import pandas as pd

from .leadership import HIGH_52W_BARS

log = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
NASI_POINTS = 252
_TTL_SEC = 10 * 60
_NASI_ROW = re.compile(
    r"^[A-Za-z]{3}\s+(\d{2})-(\d{2})-(\d{4})\s+"
    r"-?[\d.]+\s+-?[\d.]+\s+-?[\d.]+\s+(-?[\d.]+)"
)

_lock = threading.Lock()
_cache: dict[str, tuple[float, dict]] = {}


def _get(url: str, accept: str, referer: str) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": _UA, "Accept": accept, "Referer": referer},
    )
    with urllib.request.urlopen(req, timeout=12) as res:
        return res.read().decode("utf-8", "replace")


def parse_nasi(text: str, limit: int = NASI_POINTS) -> Optional[dict]:
    """Newest-first StockCharts quote table -> chronological points, last value and day change."""
    points = []
    for line in text.splitlines():
        match = _NASI_ROW.match(line.strip())
        if not match:
            continue
        month, day, year, close = match.groups()
        points.append({"time": f"{year}-{month}-{day}", "value": round(float(close), 2)})
    if not points:
        return None
    points.reverse()
    points = points[-limit:]
    last = points[-1]
    change = round(last["value"] - points[-2]["value"], 2) if len(points) > 1 else None
    return {"value": last["value"], "change": change, "as_of": last["time"], "points": points}


def parse_fear_greed(payload: dict) -> Optional[dict]:
    raw = payload.get("fear_and_greed") if isinstance(payload, dict) else None
    if not isinstance(raw, dict) or not isinstance(raw.get("score"), (int, float)):
        return None

    def num(key: str) -> Optional[float]:
        value = raw.get(key)
        return round(float(value), 1) if isinstance(value, (int, float)) else None

    rating = raw.get("rating")
    return {
        "score": round(float(raw["score"]), 1),
        "rating": rating.strip() if isinstance(rating, str) and rating.strip() else "neutral",
        "previous_close": num("previous_close"),
        "previous_week": num("previous_1_week"),
        "previous_month": num("previous_1_month"),
    }


def new_52w_extreme(daily: Optional[pd.DataFrame]) -> tuple[bool, bool]:
    """Whether the latest session set a 52-week high, a 52-week low, neither, or both.

    Compared with the prior ``HIGH_52W_BARS`` sessions only (today is not part of that
    window). Today's high must clear the prior high; today's low must undercut the prior
    low. A name with a shorter history is neither — a 60-day high is not a 52-week high.
    One wide session can be both.
    """
    need = HIGH_52W_BARS + 1
    if daily is None or len(daily) < need or "high" not in daily.columns or "low" not in daily.columns:
        return False, False
    window = daily.iloc[-need:]
    prior_high = window["high"].iloc[:-1].max(skipna=True)
    prior_low = window["low"].iloc[:-1].min(skipna=True)
    today_high = window["high"].iloc[-1]
    today_low = window["low"].iloc[-1]
    if pd.isna(prior_high) or pd.isna(prior_low) or pd.isna(today_high) or pd.isna(today_low):
        return False, False
    return bool(float(today_high) > float(prior_high)), bool(float(today_low) < float(prior_low))


def _change_pct(row: object) -> Optional[float]:
    if not isinstance(row, dict):
        return None
    change = row.get("change_pct")
    # ``bool`` is an ``int`` subclass and is not a percent.
    if isinstance(change, bool) or not isinstance(change, (int, float)):
        return None
    return float(change)


def universe_breadth(
    rows: Optional[list], daily_by_symbol: Optional[Mapping[str, pd.DataFrame]] = None
) -> Optional[dict]:
    """Up/down and 52-week high/low counts for the symbols the scanner tracks.

    Up, down and unchanged come from each row's ``change_pct``, which the scan already
    computed from the cached daily closes (latest close versus the prior close). Highs
    and lows walk the daily frames already held in memory; they are omitted until those
    frames are loaded, rather than reported as zero. ``names`` is the number of rows
    that had a change, which is the universe the cards label.
    """
    advancing = declining = unchanged = 0
    counted: list[str] = []
    for row in rows or []:
        change = _change_pct(row)
        if change is None or not isinstance(row, dict) or not row.get("symbol"):
            continue
        if change > 0:
            advancing += 1
        elif change < 0:
            declining += 1
        else:
            unchanged += 1
        counted.append(str(row["symbol"]))
    names = advancing + declining + unchanged
    if names == 0:
        return None
    issues = {"advancing": advancing, "declining": declining, "unchanged": unchanged, "names": names}
    if not daily_by_symbol:
        return {"issues": issues, "highs_lows": None}
    highs = lows = 0
    for symbol in counted:
        is_high, is_low = new_52w_extreme(daily_by_symbol.get(symbol))
        highs += int(is_high)
        lows += int(is_low)
    return {
        "issues": issues,
        "highs_lows": {"highs": highs, "lows": lows, "names": names},
    }


def _nasi_text() -> str:
    start = (date.today() - timedelta(days=400)).isoformat()
    query = urllib.parse.urlencode({"ticker": "$NASI", "start": start, "barwidth": "D", "out": "text"})
    return _get(
        f"https://stockcharts.com/quotebrain/pastdata?{query}",
        "text/plain",
        "https://stockcharts.com/",
    )


def _fear_text() -> str:
    return _get(
        "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
        "application/json",
        "https://edition.cnn.com/markets/fear-and-greed",
    )


def _cached(key: str, load: Callable[[], Optional[dict]]) -> Optional[dict]:
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < _TTL_SEC:
            return hit[1]
    try:
        fresh = load()
    except Exception as exc:
        log.warning("breadth %s failed: %s", key, exc)
        fresh = None
    with _lock:
        if fresh is not None:
            _cache[key] = (now, fresh)
            return fresh
        return _cache[key][1] if key in _cache else None


def fetch_breadth() -> dict:
    """Latest $NASI series and Fear & Greed score. Missing sources are null.

    Universe advancers and 52-week extremes are not fetched here; they are counted from
    the scan the background fetcher already produced.
    """
    return {
        "nasi": _cached("nasi", lambda: parse_nasi(_nasi_text())),
        "fear_greed": _cached("fear_greed", lambda: parse_fear_greed(json.loads(_fear_text()))),
    }


def _diary_text() -> str:
    diary_id = json.dumps({"application": "WSJ", "marketsDiaryType": "overview"}, separators=(",", ":"))
    query = urllib.parse.urlencode({"id": diary_id, "type": "mdc_marketsdiary"})
    return _get(
        f"https://www.wsj.com/market-data/stocks?{query}",
        "application/json",
        "https://www.wsj.com/market-data/stocks",
    )


def _count(value: object) -> Optional[int]:
    if not isinstance(value, str):
        return None
    text = value.replace(",", "").strip()
    return int(text) if re.fullmatch(r"\d+", text) else None


_DIARY_TS = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{2,4})\s*$")


def diary_session(timestamp: object) -> Optional[str]:
    """``"4:15 PM EDT 10/22/26"`` -> ``"2026-10-22"``; None when the stamp has no date."""
    if not isinstance(timestamp, str):
        return None
    m = _DIARY_TS.search(timestamp.strip())
    if not m:
        return None
    month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    year = year + 2000 if year < 100 else year
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def parse_nasdaq_issues(payload: object) -> Optional[dict]:
    """WSJ markets diary -> Nasdaq advancing / declining / unchanged issue counts and the diary's session.

    Only the "Issues" table is read: the diary repeats the same row names for share volume. Any missing or
    non-numeric count, or a stamp without a date, rejects the whole reading.
    """
    data = payload.get("data") if isinstance(payload, dict) else None
    sets = data.get("instrumentSets") if isinstance(data, dict) else None
    if not isinstance(sets, list):
        return None
    table = next(
        (
            item
            for item in sets
            if isinstance(item, dict)
            and isinstance(item.get("headerFields"), list)
            and item["headerFields"]
            and isinstance(item["headerFields"][0], dict)
            and item["headerFields"][0].get("label") == "Issues"
        ),
        None,
    )
    if table is None:
        return None
    rows = {r.get("name"): r for r in table.get("instruments") or [] if isinstance(r, dict) and r.get("name")}
    counts = {
        field: _count((rows.get(name) or {}).get("NASDAQ"))
        for name, field in (("Advancing", "advancing"), ("Declining", "declining"), ("Unchanged", "unchanged"))
    }
    if any(v is None for v in counts.values()) or counts["advancing"] + counts["declining"] == 0:
        return None
    stamp = data.get("timestamp")
    session = diary_session(stamp)
    if session is None:
        return None
    return {**counts, "as_of": stamp, "session": session}


_nasdaq: dict = {}


def refresh_nasdaq_issues(load: Callable[[], str] | None = None) -> Optional[dict]:
    """Fetch the Nasdaq diary into memory. Called from the background job slot, not from requests.

    A failure is logged and leaves the last real reading in place. Returns the reading now held.
    """
    try:
        fresh = parse_nasdaq_issues(json.loads((load or _diary_text)()))
        if fresh is None:
            log.warning("breadth nasdaq_issues: diary had no usable Nasdaq issue counts")
    except Exception as exc:
        log.warning("breadth nasdaq_issues failed: %s", exc)
        fresh = None
    with _lock:
        if fresh is not None:
            _nasdaq["reading"] = fresh
        return _nasdaq.get("reading")


def nasdaq_issues(session: Optional[str]) -> Optional[dict]:
    """The held Nasdaq reading when it is for ``session`` (the universe counts' session) or later; else None."""
    with _lock:
        reading = _nasdaq.get("reading")
    if reading is None or not session or reading["session"] < session:
        return None
    return dict(reading)


def clear_cache() -> None:
    with _lock:
        _cache.clear()
        _nasdaq.clear()
