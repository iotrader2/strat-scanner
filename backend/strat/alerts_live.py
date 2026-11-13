"""15-minute EMA entries for names with a daily setup, run from the 5-minute lists poll (inside the job slot).

Which names: the caller passes the names to check (the capped qualifying lists, plus manual watchlist
names when that setting is on). Each turned-on EMA is checked. Names with an alert still live today
are always kept. The same symbol list is what ``ensure_profiles`` prepares, including off-universe tickers.

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

Daily trim ladder: crossback positions are held overnight. One pass at 15:59 ET (``close_check_due``)
takes each held symbol's latest price (the forming bar's close) as the "close" for the daily trim check
and stores it (``alerts_store.save_close_marks``), so later passes that day reproduce the same trims. A
symbol with an open position and no mark by the after-close pass is marked from the last bar, ``late``.
Positions from earlier sessions are walked from a snapshot of their start-of-day state
(``carry_alert``): stop on today's bars, then the 15:59 check. A name with a carried position does not
open a new alert.

Completed bars SIP has already published keep SIP prices. Bars newer than the SIP delay are priced from
Yahoo's consolidated 15-minute chart, and from IEX only when that symbol's Yahoo request fails. The bar
still forming is judged the same way, so a trigger is not set off an IEX-only high.

"""

from __future__ import annotations

import logging
import threading
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, Mapping, Optional, Sequence

from . import alerts_store
from .alerts import (
    ACTIVE, BAR, BAR_MINUTES, CLOSE_CHECK_AT, ENTRY_EMA_CROSS, SESSION_BARS, Alert, Context, Settings,
    advance_carried, advance_stored, apply_order, carry_alert, stop_too_tight, context_from_closes, ema_periods_for,
    known_setup, simulate,
)
from .inverse_etfs import map_underlyings_to_etfs
from .leadership import BENCHMARK
from .setup_score import EntryInputs, entry_score
from .yahoo_15m import fetch_yahoo_15m
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
_daily: dict[str, dict] = {}  # symbol -> {"day": iso, "closes": [finished daily closes before day]}
DAILY_CALENDAR_DAYS = 200  # ~135 sessions: the daily 20 EMA has settled
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
            ctx = context_from_closes(regular_closes(sip.get(sym, []), day), periods=ema_periods_for())
            with _lock:
                _profiles[sym] = {"day": day.isoformat(), "tail": dict(ctx.ma_tail), "prev_close": ctx.prev_close}
        del sip
    return len(stale)


def ensure_daily_closes(client: AlpacaClient, symbols: list[str], day: date) -> dict[str, list[float]]:
    """Finished daily closes before ``day`` (split-adjusted, regular session) for the daily trim EMAs. Cached per day."""
    with _lock:
        for sym in [s for s, p in _daily.items() if p.get("day") != day.isoformat()]:
            _daily.pop(sym, None)
        stale = [s for s in symbols if s not in _daily]
    if stale:
        open_ = _at(day, OPEN)
        rows, _ = client.bars(stale, "1Day", open_ - timedelta(days=DAILY_CALENDAR_DAYS), end=open_ - timedelta(seconds=1), feed="sip", adjustment="split")
        for sym in stale:
            got = sorted((_ts(b["t"]), float(b["c"])) for b in rows.get(sym, []))
            closes = [c for t, c in got if t.astimezone(ET).date() < day]
            with _lock:
                _daily[sym] = {"day": day.isoformat(), "closes": closes}
    with _lock:
        return {s: list((_daily.get(s) or {}).get("closes") or []) for s in symbols}


def close_check_due(now: datetime) -> bool:
    """15:59-16:00 ET on a weekday: take the prices for the daily trim check."""
    local = now_et(now)
    return local.weekday() < 5 and CLOSE_CHECK_AT <= local.time() < CLOSE


def _minute(ts: datetime) -> datetime:
    return ts.astimezone(timezone.utc).replace(second=0, microsecond=0)


def _indexed(rows: list[Mapping] | None, day: date) -> dict[datetime, dict]:
    out = {}
    for b in rows or []:
        t = _ts(b["t"])
        if t.astimezone(ET).date() == day and slot(t) is not None:
            out[_minute(t)] = _bar(b)
    return out


def merge_day(
    sip: list[Mapping],
    iex: list[Mapping],
    day: date,
    cutoff: datetime,
    now: datetime,
    yahoo: list[Mapping] | None = None,
) -> tuple[list[dict], Optional[float]]:
    """(completed regular-session bars for ``day`` oldest first, premarket low).

    Prices: SIP once the candle started before ``cutoff`` and SIP has it. Otherwise Yahoo's consolidated
    OHLC, and IEX only when Yahoo has no bar. Volume stays IEX when IEX traded (else the consolidated
    volume, else 0). Each bar's ``src`` is ``sip``, ``yahoo``, or ``iex``.
    """
    iex_by = _indexed(iex, day)
    yahoo_by = _indexed(yahoo, day)
    sip_by: dict[datetime, dict] = {}
    pm_low = None
    for b in sip:
        t = _ts(b["t"])
        local = t.astimezone(ET)
        if local.date() != day:
            continue
        if PREMARKET_AT <= local.time() < OPEN:
            pm_low = float(b["l"]) if pm_low is None else min(pm_low, float(b["l"]))
        elif slot(t) is not None:
            sip_by[_minute(t)] = _bar(b)
    # IEX fills any hole. Yahoo replaces it. SIP replaces both once that candle is old enough to be published.
    merged: dict[datetime, dict] = {}
    for t, row in iex_by.items():
        priced = dict(row)
        priced["src"] = "iex"
        merged[t] = priced
    for t, row in yahoo_by.items():
        if t < cutoff and t in sip_by:
            continue
        priced = dict(row)
        priced["v"] = iex_by[t]["v"] if t in iex_by else float(row.get("v") or 0)
        priced["src"] = "yahoo"
        merged[t] = priced
    for t, row in sip_by.items():
        if t >= cutoff:
            continue
        priced = dict(row)
        priced["v"] = iex_by[t]["v"] if t in iex_by else 0.0
        priced["src"] = "sip"
        merged[t] = priced
    done = [merged[t] for t in sorted(merged) if t + BAR <= now]
    # Bars must run from the open with no hole; stop at the first missing slot.
    out = []
    for k, b in enumerate(done):
        if slot(b["t"]) != k:
            break
        out.append(b)
    return out, pm_low


def forming_bar(
    iex: list[Mapping], day: date, done: int, now: datetime, yahoo: list[Mapping] | None = None
) -> Optional[dict]:
    """The bar still forming at ``now``, when it is the next bar after the ``done`` completed ones.

    Yahoo's forming bar is the consolidated high/low. IEX is used only when Yahoo does not have it.
    """
    for rows, src in ((yahoo, "yahoo"), (iex, "iex")):
        for b in rows or []:
            t = _ts(b["t"])
            if t.astimezone(ET).date() == day and slot(t) == done and t <= now < t + BAR:
                row = _bar(b)
                row["src"] = src
                return row
    return None


def context_for(
    sym: str,
    session_bars: int,
    prior_daily_bars: Optional[Sequence] = None,
    daily_closes: Optional[Sequence[float]] = None,
    close_mark: Optional[Mapping] = None,
) -> Context:
    with _lock:
        p = dict(_profiles.get(sym) or {})
    return Context(
        ma_tail=p.get("tail") or {},
        prev_close=p.get("prev_close"),
        session_bars=session_bars,
        prior_daily_bars=tuple(prior_daily_bars or ()),
        daily_closes=tuple(daily_closes or ()),
        close_mark=close_mark,
    )


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


def _near(a: float, b: float) -> bool:
    return round(float(a), 4) == round(float(b), 4)


def correct_pending(
    session: str,
    bars_by: Mapping[str, list],
    ctx_by: Mapping[str, Context],
    settings: Settings,
    skip_keys: set[str],
    forming_by: Optional[Mapping[str, Optional[dict]]] = None,
) -> list:
    """Re-price pending alerts whose working candle was IEX once a consolidated bar exists.

    Trigger becomes that candle's high + $0.01 (short: low − $0.01) and the stop follows ``stop_mode``.
    Filled trades are left alone. Alerts this poll already rebuilt (``skip_keys``) are left to that rebuild.
    Rows saved before ``bar_feed`` existed are treated as IEX.
    """
    out = []
    for row in alerts_store.list_alerts(session=session):
        if row["status"] != "pending" or row["key"] in skip_keys:
            continue
        feed = (row.get("details") or {}).get("bar_feed")
        bars = bars_by.get(row["symbol"]) or []
        setup_ts = _parse_ts(row["setup_bar"])
        bar = next((b for b in bars if _minute(_parse_ts(b["t"])) == _minute(setup_ts)), None)
        # Nothing better than IEX yet, or this watch was already priced from SIP.
        if bar is None or bar.get("src") not in ("yahoo", "sip") or feed == "sip":
            continue
        # A Yahoo price is replaced only when SIP has the candle.
        if feed == "yahoo" and bar.get("src") != "sip":
            continue
        short = str(row["setup"]).startswith("s")
        stored = float(row["setup_low"] if short else row["setup_high"])
        live = float(bar["l"] if short else bar["h"])
        if feed == bar.get("src") and _near(stored, live):
            continue
        origin = _parse_ts(str(row["key"]).split("|")[3]) if str(row.get("key", "")).count("|") >= 3 else setup_ts
        details = dict(row.get("details") or {})
        scratch = Alert(
            symbol=row["symbol"], session=row["session"], setup=row["setup"],
            origin_bar=origin, setup_bar=setup_ts, setup_index=0,
            trigger=float(row["trigger_price"]), stop=float(row["stop_price"]),
            setup_low=float(row["setup_low"]), setup_high=float(row["setup_high"]),
            ref_price=float(row["ref_price"]), details=details, current_stop=float(row["stop_price"]),
        )
        old = scratch.trigger
        if not apply_order(scratch, float(bar["h"]), float(bar["l"]), settings):
            scratch.status = "cancelled"
            scratch.exit_reason = "stop_too_tight" if stop_too_tight(scratch, settings) else "stop_too_wide"
            scratch.exit_at = bar["t"] + BAR
            scratch.details["bar_feed"] = bar["src"]
            out.append(scratch)
            log.info("pending %s cancelled after reprice; stop outside the min/max", row["symbol"])
            continue
        scratch.details["bar_feed"] = bar["src"]
        ctx = ctx_by.get(row["symbol"])
        walked = None
        if ctx is not None:
            walked = advance_stored(
                symbol=scratch.symbol, session=scratch.session, setup=scratch.setup,
                origin_bar=origin, setup_bar=setup_ts,
                trigger=scratch.trigger, stop=scratch.stop,
                setup_low=scratch.setup_low, setup_high=scratch.setup_high,
                ref_price=scratch.ref_price, details=scratch.details,
                bars=bars, ctx=ctx, settings=settings,
                forming=(forming_by or {}).get(row["symbol"]),
            )
        final = walked or scratch
        out.append(final)
        log.info(
            "repriced pending %s trigger %.4f -> %.4f stop %.4f (%s)",
            row["symbol"], old, final.trigger, final.stop, bar["src"],
        )
    return out


def refresh(
    symbols: Iterable[str],
    now: Optional[datetime] = None,
    client: Optional[AlpacaClient] = None,
    settings: Optional[Settings] = None,
    short_symbols: Iterable[str] = (),
    daily_setups: Optional[Mapping[str, Mapping[str, list]]] = None,
    yahoo_bars: Optional[Mapping[str, list]] = None,
    prior_daily_bars: Optional[Mapping[str, Sequence]] = None,
    scan_rows: Optional[Mapping[str, Mapping]] = None,
) -> dict:
    """One alerts pass for ``symbols`` (plus names with a live alert today). Returns counts for the log line.

    ``short_symbols`` are checked for the short mirror (rallies into a falling EMA) instead of pullbacks.
    ``daily_setups`` (symbol -> {"long": [refs], "short": [refs]}) names the daily setups behind each name.
    Each ref is ``{kind, label, side}`` (and ``period`` for a 10/20/50-day average). They are kept on the
    alert's details as ``daily_setups``. A name on several setups keeps every one of them.
    ``prior_daily_bars`` (symbol -> prior-session daily bars/closes) feeds ``long_extension_skip`` in ``simulate``.
    ``scan_rows`` (symbol -> scan row) turns on the setup score: each new alert gets ``details["score"]``, the scan
    components plus the entry parts (intraday RS vs QQQ to the trigger bar, stop / ATR, trigger-day volume), frozen
    at the poll that first saved it (see ``alerts_store.save_session``). QQQ's 15-minute bars are fetched for it.
    """
    clock = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    day = now_et(clock).date()
    settings = settings or alerts_store.load_settings()
    short_underlyings = [s for s in short_symbols if s]
    # Shorts: map underlyings with EMA Crossback Short to inverse ETFs; never simulate direct shorts.
    inverse_pairs = map_underlyings_to_etfs(short_underlyings) if settings.inverse_etf_shorts and settings.shorts else []
    inverse_etfs = {etf for etf, _ in inverse_pairs}
    underlying_for = {etf: und for etf, und in inverse_pairs}
    picked = {s for s in symbols if s} - set(short_underlyings)
    # Fetch bars for long names + inverse ETFs (not the underlyings, unless also a long).
    syms = list(dict.fromkeys(list(picked) + sorted(inverse_etfs)))
    if syms and prepare_due(clock):
        # Premarket: fetch the EMA history now, so the 6:45 pass only needs today's bars.
        client = client or AlpacaClient()
        return {"symbols": len(syms), "skipped": True, "inserted": [], "prepared": ensure_profiles(client, syms, day)}
    if not due(clock):
        return {"symbols": len(syms), "skipped": True, "inserted": []}
    # A name whose daily setup went away keeps being tracked while its alert is live, but only its
    # existing alert is advanced: it cannot start a new one.
    today_rows = alerts_store.list_alerts(session=day.isoformat(), limit=None)
    live = [r["symbol"] for r in today_rows if r["status"] in ACTIVE and known_setup(r["setup"])]
    # Crossback positions from earlier sessions, held overnight for the daily trim ladder.
    carried = alerts_store.open_carried(day.isoformat())
    held_over = {r["symbol"] for r in carried}
    syms = list(dict.fromkeys(syms + live + sorted(held_over)))
    if not syms:
        return {"symbols": 0, "skipped": True, "inserted": []}
    if scan_rows is not None and BENCHMARK not in syms:
        syms.append(BENCHMARK)  # bars only: QQQ is not simulated unless it is a name itself
    client = client or AlpacaClient()
    before = client.requests
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
    if yahoo_bars is None:
        yahoo_bars, yahoo_failed = fetch_yahoo_15m(syms, day, clock)
    else:
        yahoo_failed = set()
    session_over = clock >= close_ + BAR
    # Daily trim check: open crossback positions (today's fills and carried ones) need today's 15:59 price.
    holding = held_over | {
        r["symbol"] for r in today_rows
        if r["status"] == "triggered" and (r.get("details") or {}).get("entry_trigger") == ENTRY_EMA_CROSS
    }
    marks = alerts_store.close_marks(day.isoformat()) if holding else {}
    taking = holding and (close_check_due(clock) or clock >= close_)
    daily_closes = ensure_daily_closes(client, sorted(holding), day) if taking or marks else {}
    new_marks: dict[str, dict] = {}
    found: list[Alert] = []
    bars_by: dict[str, list] = {}
    ctx_by: dict[str, Context] = {}
    forming_by: dict[str, Optional[dict]] = {}
    prior_bars = prior_daily_bars or {}
    for sym in syms:
        bars, _ = merge_day(sip.get(sym, []), iex.get(sym, []), day, cutoff, clock, yahoo_bars.get(sym))
        if not bars:
            continue
        if sym in yahoo_failed and any(b.get("src") == "iex" for b in bars):
            log.warning("alerts %s: recent 15m bars priced from IEX after Yahoo failed", sym)
        # Inverse ETFs skip the long extension cap; underlyings are screened before mapping.
        prior = () if sym in inverse_etfs else prior_bars.get(sym)
        forming = None if session_over else forming_bar(iex.get(sym, []), day, len(bars), clock, yahoo_bars.get(sym))
        mark = marks.get(sym)
        if mark is None and taking and sym in holding:
            if clock < close_:
                # 15:59: the latest price (forming bar's close) stands in for the daily close.
                last = forming if forming is not None else bars[-1]
                mark = {"price": round(float(last["c"]), 4), "at": clock.strftime("%Y-%m-%dT%H:%M:%SZ"), "late": False}
            else:
                # The 15:59 pass was missed: decide on the last bar, after the close.
                mark = {"price": round(float(bars[-1]["c"]), 4), "at": close_.strftime("%Y-%m-%dT%H:%M:%SZ"), "late": True}
            new_marks[sym] = mark
        ctx = context_for(
            sym, len(bars) if session_over else SESSION_BARS, prior_daily_bars=prior,
            daily_closes=daily_closes.get(sym), close_mark=mark,
        )
        bars_by[sym], ctx_by[sym], forming_by[sym] = bars, ctx, forming
        if sym in held_over:
            # One position per name: a carried position blocks a new entry until it is closed.
            continue
        if sym in picked:
            labels = (daily_setups or {}).get(sym) or {}
            if daily_setups is None or labels.get("long"):
                for a in simulate(sym, day.isoformat(), bars, ctx, settings, forming=forming, side="long"):
                    if labels.get("long"):
                        a.details["daily_setups"] = list(labels["long"])
                    found.append(a)
        if sym in inverse_etfs:
            und = underlying_for[sym]
            und_labels = (daily_setups or {}).get(und) or {}
            short_refs = list(und_labels.get("short") or [])
            if daily_setups is not None and not short_refs:
                continue
            for a in simulate(
                sym, day.isoformat(), bars, ctx, settings, forming=forming, side="long",
                skip_extension_cap=True,
            ):
                a.details["underlying"] = und
                a.details["inverse_etf"] = True
                a.details["side_role"] = "short"
                if short_refs:
                    a.details["daily_setups"] = short_refs
                found.append(a)
    del sip, iex
    if scan_rows is not None:
        for a in found:
            attach_entry_score(a, bars_by.get(a.symbol), bars_by.get(BENCHMARK), scan_rows.get(a.symbol))
    # A pending watch priced from IEX (including rows saved before bar_feed existed) takes the
    # consolidated candle on this poll: trigger = high + 1c, stop from the current stop rule.
    corrected = correct_pending(
        day.isoformat(), bars_by, ctx_by, settings, {a.key for a in found}, forming_by,
    )
    found.extend(corrected)
    corrected_keys = {a.key for a in corrected}
    # SIP backfill can make a touch stop reproducing an alert that already fired; still advance outcomes.
    found.extend(
        a for a in _advance_orphans(day.isoformat(), found, bars_by, ctx_by, settings, forming_by)
        if a.key not in corrected_keys
    )
    # save_session treats a key already in alerts_history as fired. This pass stays inside
    # RUN_UNTIL (16:15), which is after the 16:05 archive, including on a restart warm-up.
    if new_marks:
        alerts_store.save_close_marks(day.isoformat(), new_marks)
    saved = alerts_store.save_session(day.isoformat(), found, now=clock, top_names=settings.top_names)
    # Carried positions: stop on today's bars and today's 15:59 check, saved under their own session.
    by_session: dict[str, list[Alert]] = {}
    for row in carried:
        bars = bars_by.get(row["symbol"])
        if not bars:
            continue
        a = advance_carried(carry_alert(row, day.isoformat()), bars, ctx_by[row["symbol"]], settings)
        by_session.setdefault(row["session"], []).append(a)
    for old_session, items in sorted(by_session.items()):
        more = alerts_store.save_session(old_session, items, now=clock, top_names=0)
        for k in ("triggered", "trimmed", "stop_moved"):
            saved[k] = saved[k] + more[k]
        saved["updated"] += more["updated"]
        saved["removed"] += more["removed"]
    stats = {
        "symbols": len(syms),
        "prepared": prepared,
        "alerts": len(found),
        "inserted": saved["inserted"],
        "triggered": saved["triggered"],
        "trimmed": saved["trimmed"],
        "stop_moved": saved["stop_moved"],
        "carried": sum(len(v) for v in by_session.values()),
        "updated": saved["updated"],
        "removed": saved["removed"],
        "requests": client.requests - before,
    }
    with _lock:
        _last_run.clear()
        _last_run.update({"at": clock.strftime("%Y-%m-%dT%H:%M:%SZ"), "alerts": len(found), "symbols": len(syms)})
    return stats


def entry_inputs(alert, bars: Optional[Sequence[Mapping]], qqq_bars: Optional[Sequence[Mapping]], row: Optional[Mapping]) -> EntryInputs:
    """The entry parts of the setup score for one alert: today's move from the open to the trigger (signal) bar's
    close against QQQ over the same window, the stop as a share of the daily ATR, and today's volume so far."""
    row = row or {}
    atr = row.get("atr_pct")
    avg_vol = row.get("avg_volume")
    stock = qqq = day_vol = None
    elapsed = None
    if bars:
        idx = next((i for i, b in enumerate(bars) if b["t"] == alert.origin_bar), None)
        if idx is not None and bars[0].get("o"):
            stock = (float(bars[idx]["c"]) / float(bars[0]["o"]) - 1.0) * 100.0
            day_vol = float(sum(float(b.get("v") or 0.0) for b in bars[: idx + 1]))
            elapsed = idx + 1
    if qqq_bars:
        q = next((b for b in qqq_bars if b["t"] == alert.origin_bar), None)
        if q is not None and qqq_bars[0].get("o"):
            qqq = (float(q["c"]) / float(qqq_bars[0]["o"]) - 1.0) * 100.0
    return EntryInputs(
        stop_pct=alert.stop_pct if alert.trigger else None,
        atr14_pct=float(atr) if isinstance(atr, (int, float)) and atr > 0 else None,
        stock_change_pct=stock,
        qqq_change_pct=qqq,
        day_volume=day_vol,
        avg_volume=float(avg_vol) if isinstance(avg_vol, (int, float)) and avg_vol > 0 else None,
        bars_elapsed=elapsed,
    )


def attach_entry_score(alert, bars, qqq_bars, row) -> None:
    """Put the setup score of the trade on ``details["score"]`` unless it already has one (a stored alert keeps it)."""
    if isinstance(alert.details.get("score"), dict):
        return
    try:
        alert.details["score"] = entry_score(row, entry_inputs(alert, bars, qqq_bars, row))
    except Exception:  # noqa: BLE001 — a scoring problem must never stop an alert
        log.exception("entry score failed for %s", alert.symbol)


def last_run() -> dict:
    with _lock:
        return dict(_last_run)


def clear() -> None:
    with _lock:
        _profiles.clear()
        _daily.clear()
        _last_run.clear()
