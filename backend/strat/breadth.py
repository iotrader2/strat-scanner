"""State-of-the-market breadth: $NASI, CNN Fear & Greed, and advancing vs declining issues.

$NASI is the Nasdaq McClellan Summation Index, read from StockCharts' public quote history.
Fear & Greed is CNN's index. Advancers and decliners are the WSJ markets diary (Nasdaq and NYSE).
Each source is cached for a few minutes and a failed refresh keeps the last good reading.
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
from typing import Callable, Optional

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


def _count(value: object) -> Optional[int]:
    if not isinstance(value, str):
        return None
    text = value.replace(",", "").strip()
    return int(text) if re.fullmatch(r"\d+", text) else None


def parse_issues(payload: dict) -> Optional[dict]:
    """WSJ markets diary -> advancing, declining and unchanged issue counts per exchange.

    The diary also lists share volume under the same row names, so only the Issues table is used.
    """
    sets = (payload.get("data") or {}).get("instrumentSets") if isinstance(payload, dict) else None
    if not isinstance(sets, list):
        return None
    issues = next(
        (
            item
            for item in sets
            if isinstance(item, dict)
            and (item.get("headerFields") or [{}])[0].get("label") == "Issues"
        ),
        None,
    )
    if not isinstance(issues, dict):
        return None
    rows = {
        row.get("name"): row
        for row in issues.get("instruments") or []
        if isinstance(row, dict) and row.get("name")
    }
    out = {}
    for exchange, key in (("NASDAQ", "nasdaq"), ("NYSE", "nyse")):
        counts = {
            field: _count((rows.get(name) or {}).get(exchange))
            for name, field in (("Advancing", "advancing"), ("Declining", "declining"), ("Unchanged", "unchanged"))
        }
        if any(v is None for v in counts.values()):
            continue
        out[key] = counts
    return out or None


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


def _diary_text() -> str:
    diary_id = json.dumps({"application": "WSJ", "marketsDiaryType": "overview"}, separators=(",", ":"))
    query = urllib.parse.urlencode({"id": diary_id, "type": "mdc_marketsdiary"})
    return _get(
        f"https://www.wsj.com/market-data/stocks?{query}",
        "application/json",
        "https://www.wsj.com/market-data/stocks",
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
    """Latest $NASI series, Fear & Greed score and advancer/decliner counts. Missing sources are null."""
    return {
        "nasi": _cached("nasi", lambda: parse_nasi(_nasi_text())),
        "fear_greed": _cached("fear_greed", lambda: parse_fear_greed(json.loads(_fear_text()))),
        "issues": _cached("issues", lambda: parse_issues(json.loads(_diary_text()))),
    }


def clear_cache() -> None:
    with _lock:
        _cache.clear()
