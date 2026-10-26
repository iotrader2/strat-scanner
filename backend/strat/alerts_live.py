"""Alerts for the watchlist, run from the existing 5-minute poll (inside the job slot).

Per poll, two small Alpaca requests for the watchlist: today's SIP bars (04:00 ET up to the 15-minute
SIP cutoff, which also gives the premarket low) and today's IEX bars from the open. Each completed
regular-session bar takes its prices from SIP when SIP has it and from IEX otherwise; volume is always
IEX, so it is compared like for like with the IEX time-of-day average. That average (20 sessions,
one number per 5-minute slot) and the prior sessions' closes that seed the EMAs are fetched once per
session per symbol and held here: under 1 KB a symbol.

Only 09:30-16:00 ET (6:30-1:00 Phoenix in daylight time) is used; outside it the poll does nothing,
apart from one run just after the close so the last bar is scored and open trades are closed.
"""

from __future__ import annotations

import logging
import threading
from datetime import date, datetime, time, timedelta, timezone
from typing import Callable, Iterable, Mapping, Optional

from . import alerts_store
from .alerts import Context, Settings, simulate
from .alpaca import AlpacaClient
from .intraday import sip_cutoff
from .scheduler import CLOSE, ET, OPEN, PREMARKET_AT, now_et

log = logging.getLogger(__name__)

BAR = timedelta(minutes=5)
PROFILE_SESSIONS = 20
PROFILE_CALENDAR_DAYS = 34  # 20 sessions plus weekends and a holiday or two
WARM_SESSIONS = 5
WARM_CALENDAR_DAYS = 10
PROFILE_BATCH = 5  # symbols per profile request, keeps the transient bar list small
RUN_UNTIL = time(16, 15)  # one last pass after the close
PREPARE_FROM = time(8, 0)  # premarket polls from here fetch the per-day inputs ahead of the open

_lock = threading.Lock()
_profiles: dict[str, dict] = {}  # symbol -> {"day": iso, "avg": {slot: vol}, "sessions": n, "warm": [closes]}
_last_run: dict = {}


def _ts(raw) -> datetime:
    if isinstance(raw, datetime):
        return raw.astimezone(timezone.utc)
    return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(timezone.utc)


def _at(day: date, t: time) -> datetime:
    return datetime.combine(day, t, tzinfo=ET).astimezone(timezone.utc)


def slot(ts: datetime) -> Optional[int]:
    """5-minute bar index after the open (0 = the opening bar), None outside the regular session."""
    local = ts.astimezone(ET)
    minutes = (local.hour * 60 + local.minute) - (OPEN.hour * 60 + OPEN.minute)
    if minutes < 0 or local.time() >= CLOSE:
        return None
    return minutes // 5


def _bar(b: Mapping) -> dict:
    return {"t": _ts(b["t"]), "o": float(b["o"]), "h": float(b["h"]), "l": float(b["l"]), "c": float(b["c"]), "v": float(b.get("v") or 0)}


def volume_profile(bars: Iterable[Mapping], before: date) -> tuple[dict[int, float], int]:
    """Average IEX volume per bar slot over the last ``PROFILE_SESSIONS`` sessions before ``before``.

    A slot with no IEX bar in a session counts as zero volume for that session.
    """
    by_day: dict[date, dict[int, float]] = {}
    for b in bars:
        t = _ts(b["t"])
        d = t.astimezone(ET).date()
        k = slot(t)
        if k is None or d >= before:
            continue
        by_day.setdefault(d, {})[k] = by_day.get(d, {}).get(k, 0.0) + float(b.get("v") or 0)
    days = sorted(by_day)[-PROFILE_SESSIONS:]
    if not days:
        return {}, 0
    slots = {k for d in days for k in by_day[d]}
    return {k: sum(by_day[d].get(k, 0.0) for d in days) / len(days) for k in sorted(slots)}, len(days)


def warm_closes(bars: Iterable[Mapping], before: date) -> list[float]:
    """Regular-session closes of the last ``WARM_SESSIONS`` sessions before ``before`` (EMA seed)."""
    rows = sorted((_ts(b["t"]), float(b["c"])) for b in bars)
    rows = [(t, c) for t, c in rows if slot(t) is not None and t.astimezone(ET).date() < before]
    days = sorted({t.astimezone(ET).date() for t, _ in rows})[-WARM_SESSIONS:]
    keep = set(days)
    return [c for t, c in rows if t.astimezone(ET).date() in keep]


def ensure_profiles(client: AlpacaClient, symbols: list[str], day: date) -> int:
    """Fetch the volume profile and EMA seed for symbols not yet prepared for ``day``. Returns how many."""
    with _lock:
        stale = [s for s in symbols if (_profiles.get(s) or {}).get("day") != day.isoformat()]
        for gone in set(_profiles) - set(symbols):
            _profiles.pop(gone, None)
    open_ = _at(day, OPEN)
    for i in range(0, len(stale), PROFILE_BATCH):
        batch = stale[i : i + PROFILE_BATCH]
        iex, _ = client.bars(batch, "5Min", open_ - timedelta(days=PROFILE_CALENDAR_DAYS), end=open_ - timedelta(seconds=1), feed="iex", adjustment="raw")
        sip, _ = client.bars(batch, "5Min", open_ - timedelta(days=WARM_CALENDAR_DAYS), end=open_ - timedelta(seconds=1), feed="sip", adjustment="raw")
        for sym in batch:
            avg, n = volume_profile(iex.get(sym, []), day)
            entry = {"day": day.isoformat(), "avg": avg, "sessions": n, "warm": warm_closes(sip.get(sym, []), day)}
            with _lock:
                _profiles[sym] = entry
        del iex, sip
    return len(stale)


def merge_day(sip: list[Mapping], iex: list[Mapping], day: date, cutoff: datetime, now: datetime) -> tuple[list[dict], Optional[float]]:
    """(completed regular-session bars for ``day`` oldest first, premarket low).

    Prices: SIP for bars that started before ``cutoff``, IEX after. Volume: IEX (0 when IEX had no trade).
    """
    iex_by = {}
    for b in iex:
        t = _ts(b["t"])
        if t.astimezone(ET).date() == day and slot(t) is not None:
            iex_by[t] = _bar(b)
    merged: dict[datetime, dict] = {t: dict(b) for t, b in iex_by.items() if t >= cutoff}
    pm_low = None
    for b in sip:
        t = _ts(b["t"])
        local = t.astimezone(ET)
        if local.date() != day:
            continue
        if PREMARKET_AT <= local.time() < OPEN:
            pm_low = float(b["l"]) if pm_low is None else min(pm_low, float(b["l"]))
        elif slot(t) is not None and t < cutoff:
            row = _bar(b)
            row["v"] = iex_by[t]["v"] if t in iex_by else 0.0
            merged[t] = row
    done = [merged[t] for t in sorted(merged) if t + BAR <= now]
    # Bars must run from the open with no hole; stop at the first missing slot.
    out = []
    for k, b in enumerate(done):
        if slot(b["t"]) != k:
            break
        out.append(b)
    return out, pm_low


def context_for(sym: str, prev_close: Optional[float], pm_low: Optional[float], session_bars: int) -> Context:
    with _lock:
        p = dict(_profiles.get(sym) or {})
    return Context(
        warm_closes=p.get("warm") or [],
        prev_close=prev_close,
        premarket_low=pm_low,
        vol_avg=p.get("avg") or {},
        vol_sessions=p.get("sessions") or 0,
        session_bars=session_bars,
    )


def prepare_due(now: datetime) -> bool:
    local = now_et(now)
    return local.weekday() < 5 and PREPARE_FROM <= local.time() < time(9, 35)


def due(now: datetime) -> bool:
    local = now_et(now)
    return local.weekday() < 5 and time(9, 35) <= local.time() <= RUN_UNTIL


def refresh(
    symbols: Iterable[str],
    prev_close: Callable[[str, date], Optional[float]],
    now: Optional[datetime] = None,
    client: Optional[AlpacaClient] = None,
    settings: Optional[Settings] = None,
) -> dict:
    """One alerts pass for the watchlist. Returns counts for the log line (new alert ids included)."""
    clock = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    syms = list(dict.fromkeys(s for s in symbols if s))
    if syms and prepare_due(clock):
        # Premarket: fetch the volume averages and EMA seeds now, so the 6:35 pass only needs today's bars.
        client = client or AlpacaClient()
        return {"symbols": len(syms), "skipped": True, "inserted": [], "prepared": ensure_profiles(client, syms, now_et(clock).date())}
    if not syms or not due(clock):
        return {"symbols": len(syms), "skipped": True, "inserted": []}
    client = client or AlpacaClient()
    before = client.requests
    day = now_et(clock).date()
    settings = settings or alerts_store.load_settings()
    prepared = ensure_profiles(client, syms, day)
    cutoff = sip_cutoff(clock)
    open_, close_ = _at(day, OPEN), _at(day, CLOSE)
    sip, _ = client.bars(syms, "5Min", _at(day, PREMARKET_AT), end=min(cutoff, close_) - timedelta(seconds=1), feed="sip", adjustment="raw")
    iex, _ = client.bars(syms, "5Min", open_, end=min(clock, close_), feed="iex", adjustment="raw")
    session_over = clock >= close_ + BAR
    found = []
    for sym in syms:
        bars, pm_low = merge_day(sip.get(sym, []), iex.get(sym, []), day, cutoff, clock)
        if not bars:
            continue
        ctx = context_for(sym, prev_close(sym, day), pm_low, len(bars) if session_over else 78)
        found.extend(simulate(sym, day.isoformat(), bars, ctx, settings))
    saved = alerts_store.save_session(day.isoformat(), found, now=clock, top_names=settings.top_names)
    stats = {
        "symbols": len(syms),
        "prepared": prepared,
        "alerts": len(found),
        "inserted": saved["inserted"],
        "updated": saved["updated"],
        "requests": client.requests - before,
    }
    with _lock:
        _last_run.clear()
        _last_run.update({"at": clock.strftime("%Y-%m-%dT%H:%M:%SZ"), "alerts": len(found), "symbols": len(syms)})
    return stats


def last_run() -> dict:
    with _lock:
        return dict(_last_run)


def clear() -> None:
    with _lock:
        _profiles.clear()
        _last_run.clear()
