"""15-minute EMA entries for names with a daily setup, run from the 5-minute lists poll (inside the job slot).

Which names: the caller passes the names ``alert_symbols`` / ``alert_short_symbols`` chose (theme band,
allowed short setups, pending gate, then the score / RS caps). Each turned-on EMA is checked. Names with an
alert still live today are always kept.

Per poll, two Alpaca requests for those names: today's SIP bars (from the open up to the 15-minute SIP
cutoff) and today's IEX bars from the open. Each completed regular-session bar takes its prices from SIP
when SIP has it and from IEX otherwise. The bar still forming (IEX, real time) is only used to catch a
trigger early.

The 120 / 240 / 480 EMAs need weeks of 15-minute closes. Once per session per symbol (premarket from
08:00 ET, or the first poll that sees a new name) ``HISTORY_CALENDAR_DAYS`` of SIP bars are fetched, a few
symbols per request, and only the last ``TAIL_KEEP`` EMA values per period and the prior close are kept:
under 1 KB a symbol.

Only 09:30-16:00 ET is used, and nothing runs until the opening 15-minute candle has formed (09:45 ET);
outside it the poll does nothing, apart from one run just after the close so the last bar is scored and
open trades are closed.
"""

from __future__ import annotations

import logging
import threading
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, Mapping, Optional

from . import alerts_store
from .alerts import ACTIVE, BAR, SETUPS, BAR_MINUTES, SESSION_BARS, Alert, Context, Settings, advance_stored, context_from_closes, simulate
from .alpaca import AlpacaClient
from .intraday import sip_cutoff as _sip_cutoff
from .scheduler import CLOSE, ET, OPEN, PREMARKET_AT, now_et

log = logging.getLogger(__name__)

BARS = f"{BAR_MINUTES}Min"  # Alpaca timeframe
# ~63 sessions (~1,600 regular 15-minute closes) so the EMA 480 has settled; same window as the chart.
HISTORY_CALENDAR_DAYS = 92
HISTORY_BATCH = 2  # symbols per history request (~4k SIP bars each incl. extended hours; one page)
FIRST_RUN = time(9, 45)  # the opening 15-minute candle has formed; no alert can exist before it
RUN_UNTIL = time(16, 15)  # one last pass after the close
PREPARE_FROM = time(8, 0)  # premarket polls from here fetch the per-day inputs ahead of the open

_lock = threading.Lock()
_profiles: dict[str, dict] = {}  # symbol -> {"day": iso, "tail": {period: [ema...]}, "prev_close": float}
_last_run: dict = {}


def _ts(raw) -> datetime:
    if isinstance(raw, datetime):
        return raw.astimezone(timezone.utc)
    return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(timezone.utc)


def _at(day: date, t: time) -> datetime:
    return datetime.combine(day, t, tzinfo=ET).astimezone(timezone.utc)


def slot(ts: datetime) -> Optional[int]:
    """15-minute bar index after the open (0 = the opening bar), None outside the regular session."""
    local = ts.astimezone(ET)
    minutes = (local.hour * 60 + local.minute) - (OPEN.hour * 60 + OPEN.minute)
    if minutes < 0 or local.time() >= CLOSE:
        return None
    return minutes // BAR_MINUTES


def _bar(b: Mapping) -> dict:
    return {"t": _ts(b["t"]), "o": float(b["o"]), "h": float(b["h"]), "l": float(b["l"]), "c": float(b["c"]), "v": float(b.get("v") or 0)}


def regular_closes(bars: Iterable[Mapping], before: date) -> list[float]:
    """Regular-session (09:30-16:00 ET) closes before ``before``, oldest first. Premarket and after hours are dropped."""
    rows = sorted((_ts(b["t"]), float(b["c"])) for b in bars)
    return [c for t, c in rows if slot(t) is not None and t.astimezone(ET).date() < before]


def ensure_profiles(client: AlpacaClient, symbols: list[str], day: date) -> int:
    """Fetch the EMA history for symbols not yet prepared for ``day``. Returns how many.

    Profiles from earlier days are dropped; a name that leaves the list keeps today's profile, so a
    score hovering around the cut does not fetch it again.
    """
    with _lock:
        for sym in [s for s, p in _profiles.items() if p.get("day") != day.isoformat()]:
            _profiles.pop(sym, None)
        stale = [s for s in symbols if s not in _profiles]
    open_ = _at(day, OPEN)
    for i in range(0, len(stale), HISTORY_BATCH):
        batch = stale[i : i + HISTORY_BATCH]
        sip, _ = client.bars(batch, BARS, open_ - timedelta(days=HISTORY_CALENDAR_DAYS), end=open_ - timedelta(seconds=1), feed="sip", adjustment="raw")
        for sym in batch:
            ctx = context_from_closes(regular_closes(sip.get(sym, []), day))
            with _lock:
                _profiles[sym] = {"day": day.isoformat(), "tail": dict(ctx.ma_tail), "prev_close": ctx.prev_close}
        del sip
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


def forming_bar(iex: list[Mapping], day: date, done: int, now: datetime) -> Optional[dict]:
    """Today's IEX bar still forming at ``now``, when it is the next bar after the ``done`` completed ones."""
    for b in iex:
        t = _ts(b["t"])
        if t.astimezone(ET).date() == day and slot(t) == done and t <= now < t + BAR:
            return _bar(b)
    return None


def context_for(sym: str, session_bars: int) -> Context:
    with _lock:
        p = dict(_profiles.get(sym) or {})
    return Context(ma_tail=p.get("tail") or {}, prev_close=p.get("prev_close"), session_bars=session_bars)


def sip_cutoff(now: datetime) -> datetime:
    """Bars starting before this instant closed (whole 15-minute candles) at least 15 minutes ago."""
    return _sip_cutoff(now, BAR_MINUTES)


def prepare_due(now: datetime) -> bool:
    local = now_et(now)
    return local.weekday() < 5 and PREPARE_FROM <= local.time() < FIRST_RUN


def due(now: datetime) -> bool:
    local = now_et(now)
    return local.weekday() < 5 and FIRST_RUN <= local.time() <= RUN_UNTIL


def _parse_ts(raw) -> datetime:
    if isinstance(raw, datetime):
        return raw.astimezone(timezone.utc)
    return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(timezone.utc)


def _advance_orphans(
    session: str,
    found: list,
    bars_by: Mapping[str, list],
    ctx_by: Mapping[str, Context],
    settings: Settings,
    forming_by: Optional[Mapping[str, Optional[dict]]] = None,
) -> list:
    """ACTIVE DB alerts for this session that simulate no longer emits — re-walk outcomes only."""
    known = {a.key for a in found}
    out = []
    for row in alerts_store.list_alerts(session=session):
        if row["status"] not in ACTIVE or row["key"] in known:
            continue
        sym = row["symbol"]
        bars = bars_by.get(sym)
        ctx = ctx_by.get(sym)
        if not bars or ctx is None:
            continue
        parts = str(row["key"]).split("|")
        origin = _parse_ts(parts[3]) if len(parts) >= 4 else _parse_ts(row["setup_bar"])
        a = advance_stored(
            symbol=sym,
            session=session,
            setup=row["setup"],
            origin_bar=origin,
            setup_bar=_parse_ts(row["setup_bar"]),
            trigger=float(row["trigger_price"]),
            stop=float(row["stop_price"]),
            setup_low=float(row["setup_low"]),
            setup_high=float(row["setup_high"]),
            ref_price=float(row["ref_price"]),
            details=row.get("details") if isinstance(row.get("details"), dict) else {},
            bars=bars,
            ctx=ctx,
            settings=settings,
            forming=(forming_by or {}).get(sym),
        )
        if a is not None:
            out.append(a)
            log.info("alerts orphan advanced %s -> %s", a.key, a.status)
    return out


def refresh(
    symbols: Iterable[str],
    now: Optional[datetime] = None,
    client: Optional[AlpacaClient] = None,
    settings: Optional[Settings] = None,
    short_symbols: Iterable[str] = (),
    daily_setups: Optional[Mapping[str, Mapping[str, list]]] = None,
) -> dict:
    """One alerts pass for ``symbols`` (plus names with a live alert today). Returns counts for the log line.

    ``short_symbols`` are checked for the short mirror (rallies into a falling EMA) instead of pullbacks.
    ``daily_setups`` (symbol -> {"long": [labels], "short": [labels]}) names the daily setups behind each name;
    they are kept on the alert's details as ``daily_setups``.
    """
    clock = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    day = now_et(clock).date()
    short_picked = {s for s in short_symbols if s}
    syms = list(dict.fromkeys([s for s in symbols if s] + sorted(short_picked)))
    if syms and prepare_due(clock):
        # Premarket: fetch the EMA history now, so the 6:45 pass only needs today's bars.
        client = client or AlpacaClient()
        return {"symbols": len(syms), "skipped": True, "inserted": [], "prepared": ensure_profiles(client, syms, day)}
    if not due(clock):
        return {"symbols": len(syms), "skipped": True, "inserted": []}
    # A name whose daily setup went away keeps being tracked while its alert is live, but only its
    # existing alert is advanced: it cannot start a new one. Rows from the old A-F rules are not tracked.
    picked = set(syms) - short_picked
    live = [
        r["symbol"] for r in alerts_store.list_alerts(session=day.isoformat())
        if r["status"] in ACTIVE and r["setup"] in SETUPS
    ]
    syms = list(dict.fromkeys(syms + live))
    if not syms:
        return {"symbols": 0, "skipped": True, "inserted": []}
    client = client or AlpacaClient()
    before = client.requests
    settings = settings or alerts_store.load_settings()
    prepared = ensure_profiles(client, syms, day)
    cutoff = sip_cutoff(clock)
    open_, close_ = _at(day, OPEN), _at(day, CLOSE)
    # Until 10:15 ET no completed 15-minute SIP bar of today exists yet (the cutoff is at or before the open):
    # asking anyway sends an end before the start, which Alpaca rejects, and the 09:45 / 10:00 passes failed.
    if cutoff > open_:
        sip, _ = client.bars(syms, BARS, open_, end=min(cutoff, close_) - timedelta(seconds=1), feed="sip", adjustment="raw")
    else:
        sip = {}
    iex, _ = client.bars(syms, BARS, open_, end=min(clock, close_), feed="iex", adjustment="raw")
    session_over = clock >= close_ + BAR
    found: list[Alert] = []
    bars_by: dict[str, list] = {}
    ctx_by: dict[str, Context] = {}
    forming_by: dict[str, Optional[dict]] = {}
    for sym in syms:
        bars, _ = merge_day(sip.get(sym, []), iex.get(sym, []), day, cutoff, clock)
        if not bars:
            continue
        ctx = context_for(sym, len(bars) if session_over else SESSION_BARS)
        forming = None if session_over else forming_bar(iex.get(sym, []), day, len(bars), clock)
        bars_by[sym], ctx_by[sym], forming_by[sym] = bars, ctx, forming
        labels = (daily_setups or {}).get(sym) or {}
        for side, wanted in (("long", sym in picked), ("short", sym in short_picked)):
            # A new alert needs a daily setup on that side (when the caller says which names have one).
            if not wanted or (daily_setups is not None and not labels.get(side)):
                continue
            for a in simulate(sym, day.isoformat(), bars, ctx, settings, forming=forming, side=side):
                if labels.get(side):
                    a.details["daily_setups"] = list(labels[side])
                found.append(a)
    del sip, iex
    # SIP backfill can make a touch stop reproducing an alert that already fired; still advance outcomes.
    found.extend(_advance_orphans(day.isoformat(), found, bars_by, ctx_by, settings, forming_by))
    # save_session treats a key already in alerts_history as fired. This pass stays inside
    # RUN_UNTIL (16:15), which is after the 16:05 archive, including on a restart warm-up.
    saved = alerts_store.save_session(day.isoformat(), found, now=clock, top_names=settings.top_names)
    stats = {
        "symbols": len(syms),
        "prepared": prepared,
        "alerts": len(found),
        "inserted": saved["inserted"],
        "triggered": saved["triggered"],
        "updated": saved["updated"],
        "removed": saved["removed"],
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
