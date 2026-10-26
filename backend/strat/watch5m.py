"""Premarket prints and 5-minute EMA position for the watchlist and positions (Alpaca).

The alerts table reads the same in-memory EMA comparison (above / below the 6 and 20). It does not fetch.

These lists are a handful of names, so they get finer data than the universe without costing memory:

* **Premarket** (04:00-09:30 ET): last price, % change against the prior regular close, and volume.
  The price is the newest premarket print from either Alpaca free feed: IEX latest trade (real time,
  but IEX trades few names before ~08:00 ET) or the 15-minute delayed SIP latest trade (all exchanges,
  ``feed=delayed_sip``). Volume is the sum of SIP 5-minute bars, which are only served once they are
  15 minutes old, so it trails the price. After the open the reading freezes; once the 09:25 SIP bar is
  served (about 09:46 ET) it is replaced by the exact premarket close and full premarket volume. It is
  shown through the regular session and dropped at 16:00 ET.
* **Day range**: low / high of today's regular-session 5-minute bars with the latest price placed in it
  (0% at the low, 100% at the high). In premarket it is the premarket range so far (SIP bars plus the
  latest print); outside both, the last completed session's range.
* **Crossover highlight**: :func:`highlight_rule` on the last two completed 5-minute bars (a close back
  above the 6 or 20 EMA), shown for one bar, until the next bar completes. The Positions table paints
  the row; the watchlist does not.
* **6 and 20 EMA on the 5-minute chart**: regular-session bars only (09:30-16:00 ET), the usual chart
  definition, seeded with the last ``HISTORY_SESSIONS`` sessions so both averages are warmed up. The
  price compared against them is the live 5-minute close in the session, the premarket print in
  premarket, and the last regular close otherwise.

Prior sessions are SIP bars fetched once per session (and when a symbol is new). Today's bars are SIP
for anything 15 minutes old and IEX (real time) after that. Everything is held in this module's memory:
a few hundred closes per symbol. Nothing here runs on a page request; ``refresh`` is called from the
background job slot. A symbol without data shows a dash: nothing is estimated.
"""

from __future__ import annotations

import logging
import threading
from datetime import date, datetime, time, timedelta, timezone
from typing import Callable, Iterable, Mapping, Optional

from .alpaca import AlpacaClient, HTTPStatus, from_alpaca, to_alpaca
from .intraday import sip_cutoff
from .scheduler import CLOSE, ET, OPEN, PREMARKET_AT, last_completed_session, now_et, session_phase

log = logging.getLogger(__name__)

EMA_PERIODS = (6, 20)
HISTORY_SESSIONS = 5
HISTORY_CALENDAR_DAYS = 10  # enough calendar days to cover 5 sessions across a weekend and a holiday
MAX_SYMBOLS = 200  # one Alpaca batch
BAR = timedelta(minutes=5)

_lock = threading.Lock()
_history: dict[str, dict] = {}  # symbol -> {"checked": iso date, "closes": [(ts, close)]}
_premarket: dict[str, dict] = {}  # symbol -> reading for one session
_ema: dict[str, dict] = {}  # symbol -> latest EMA comparison
_range: dict[str, dict] = {}  # symbol -> day range (low / high / last)


def _ts(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)


def _iso(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _at(day: date, t: time) -> datetime:
    return datetime.combine(day, t, tzinfo=ET).astimezone(timezone.utc)


def is_regular(ts: datetime) -> bool:
    local = ts.astimezone(ET)
    return local.weekday() < 5 and OPEN <= local.time() < CLOSE


def is_premarket(ts: datetime, day: date) -> bool:
    local = ts.astimezone(ET)
    return local.date() == day and PREMARKET_AT <= local.time() < OPEN


def ema(values: list[float], period: int) -> Optional[float]:
    """Exponential moving average of ``values`` (oldest first), seeded with the SMA of the first ``period``."""
    if period <= 0 or len(values) < period:
        return None
    k = 2.0 / (period + 1)
    value = sum(values[:period]) / period
    for v in values[period:]:
        value += k * (v - value)
    return value


def ema_series(values: list[float], period: int) -> list[Optional[float]]:
    """EMA after each value (None until ``period`` values are in); the last entry equals :func:`ema`."""
    out: list[Optional[float]] = [None] * len(values)
    if period <= 0 or len(values) < period:
        return out
    k = 2.0 / (period + 1)
    value = sum(values[:period]) / period
    out[period - 1] = value
    for i in range(period, len(values)):
        value += k * (values[i] - value)
        out[i] = value
    return out


def highlight_rule(prev_close: float, prev_ema: float, last_close: float, last_ema: float) -> bool:
    """Crossover on the last two *completed* 5-minute bars: the last one closed above the EMA and the one
    before it closed at or below it. A name that simply stays above the EMA is not flagged."""
    return last_close > last_ema and prev_close <= prev_ema


def reclaims(bars: list[tuple[str, float]], now: datetime) -> tuple[list[int], Optional[str], Optional[str]]:
    """(EMA periods that :func:`highlight_rule` flags, last completed bar start, when the next bar completes).

    ``bars`` are (start, close) oldest first. A bar is completed once its 5 minutes are over. The highlight
    is only meant to last until the next bar completes; :func:`snapshot` drops it after ``until``.
    """
    done = [(ts, c) for ts, c in bars if _ts(ts) + BAR <= now]
    if len(done) < 2:
        return [], None, None
    closes = [c for _, c in done]
    hits = []
    for n in EMA_PERIODS:
        series = ema_series(closes, n)
        if series[-1] is None or series[-2] is None:
            continue
        if highlight_rule(closes[-2], series[-2], closes[-1], series[-1]):
            hits.append(n)
    last = _ts(done[-1][0])
    return hits, _iso(last), _iso(last + 2 * BAR)


def _bars(client: AlpacaClient, symbols: list[str], start: datetime, end: datetime, feed: str) -> dict[str, list[dict]]:
    if end <= start:
        return {}
    out, invalid = client.bars(symbols, "5Min", start, end=end, feed=feed, adjustment="raw")
    if invalid:
        log.info("watch5m: Alpaca has no %s bars for %s", feed, ",".join(invalid))
    return out


def _latest_trades(client: AlpacaClient, symbols: list[str], feed: str) -> dict[str, dict]:
    try:
        payload = client.get(
            "/v2/stocks/trades/latest", {"symbols": ",".join(to_alpaca(s) for s in symbols), "feed": feed}
        )
    except HTTPStatus as exc:
        log.warning("watch5m: latest trades (%s) failed: %s", feed, exc.status)
        return {}
    return {from_alpaca(sym): t for sym, t in (payload.get("trades") or {}).items() if isinstance(t, dict)}


def refresh_history(symbols: list[str], now: datetime, client: AlpacaClient) -> int:
    """SIP 5-minute closes for the last ``HISTORY_SESSIONS`` completed sessions, for symbols not yet current.

    Current means checked against the latest completed session (today after 16:20 ET). One request
    per batch, only when a session has completed since the last check or the symbol is new.
    """
    through = last_completed_session(now)
    with _lock:
        stale = [s for s in symbols if (_history.get(s) or {}).get("checked") != through.isoformat()]
    if not stale:
        return 0
    start = _at(through - timedelta(days=HISTORY_CALENDAR_DAYS), OPEN)
    end = min(_at(through, CLOSE), sip_cutoff(now))
    bars = _bars(client, stale, start, end, "sip")
    for sym in stale:
        regular = [b for b in bars.get(sym, []) if is_regular(_ts(b["t"]))]
        closes = [(_iso(_ts(b["t"])), float(b["c"])) for b in regular]
        sessions = sorted({_ts(ts).astimezone(ET).date() for ts, _ in closes})[-HISTORY_SESSIONS:]
        keep = [(ts, c) for ts, c in closes if sessions and _ts(ts).astimezone(ET).date() >= sessions[0]]
        last_range = None
        if sessions:
            last_day = [b for b in regular if _ts(b["t"]).astimezone(ET).date() == sessions[-1]]
            last_range = make_range(last_day, float(last_day[-1]["c"]), "last session", sessions[-1].isoformat())
        with _lock:
            _history[sym] = {"checked": through.isoformat(), "closes": keep, "range": last_range}
    return len(stale)


def make_range(bars: list[dict], last: float, basis: str, session: str) -> Optional[dict]:
    """Low / high of ``bars`` (5-minute h/l) with ``last`` placed in it; None when empty or high == low.

    ``pct`` is where ``last`` sits: 0 at the low of the range, 100 at the high.
    """
    if not bars:
        return None
    low = min(min(float(b["l"]) for b in bars), last)
    high = max(max(float(b["h"]) for b in bars), last)
    if not high > low:
        return None
    return {
        "low": round(low, 4),
        "high": round(high, 4),
        "last": round(last, 4),
        "pct": round((last - low) / (high - low) * 100, 1),
        "basis": basis,
        "session": session,
    }


def _today_regular_bars(
    sip: Mapping[str, list[dict]], iex: Mapping[str, list[dict]], symbol: str, cutoff: datetime
) -> list[dict]:
    """Today's regular-session bars, oldest first: SIP for bars that started before ``cutoff``, IEX after."""
    merged: dict[str, dict] = {}
    for b in iex.get(symbol, []):
        t = _ts(b["t"])
        if is_regular(t) and t >= cutoff:
            merged[_iso(t)] = b
    for b in sip.get(symbol, []):
        t = _ts(b["t"])
        if is_regular(t) and t < cutoff:
            merged[_iso(t)] = b
    return [merged[k] for k in sorted(merged)]


def _today_regular(
    sip: Mapping[str, list[dict]], iex: Mapping[str, list[dict]], symbol: str, cutoff: datetime
) -> list[tuple[str, float]]:
    """Today's regular-session closes: SIP for bars that started before ``cutoff``, IEX after."""
    return [(_iso(_ts(b["t"])), float(b["c"])) for b in _today_regular_bars(sip, iex, symbol, cutoff)]


def _premarket_print(
    symbol: str, day: date, sip: Mapping[str, list[dict]], trades: Iterable[Mapping[str, dict]]
) -> Optional[tuple[float, str, str]]:
    """Newest premarket (price, time, source) across the delayed SIP / IEX latest trades and the SIP bars."""
    best: Optional[tuple[datetime, float, str]] = None
    for feed_trades, source in trades:
        t = feed_trades.get(symbol)
        if not t or not isinstance(t.get("p"), (int, float)) or not t.get("t"):
            continue
        ts = _ts(t["t"])
        if is_premarket(ts, day) and t["p"] > 0 and (best is None or ts > best[0]):
            best = (ts, float(t["p"]), source)
    for b in sip.get(symbol, []):
        ts = _ts(b["t"])
        # A bar's last trade happened before the bar ended; date it at its start to stay conservative.
        if is_premarket(ts, day) and (best is None or ts > best[0]):
            best = (ts, float(b["c"]), "sip bar")
    if best is None:
        return None
    return best[1], _iso(best[0]), best[2]


def _premarket_volume(symbol: str, day: date, sip: Mapping[str, list[dict]]) -> tuple[Optional[float], Optional[str]]:
    rows = [b for b in sip.get(symbol, []) if is_premarket(_ts(b["t"]), day)]
    if not rows:
        return None, None
    last = max(_ts(b["t"]) for b in rows) + timedelta(minutes=5)
    return float(sum(float(b.get("v") or 0) for b in rows)), _iso(last)


def refresh(
    symbols: Iterable[str],
    prev_close: Callable[[str, date], Optional[float]],
    now: Optional[datetime] = None,
    client: Optional[AlpacaClient] = None,
) -> dict:
    """One poll for the watchlist and positions symbols. Returns counts for the log line.

    ``prev_close(symbol, day)`` is the last regular close before ``day`` from the daily cache.
    """
    clock = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    syms = list(dict.fromkeys(s for s in symbols if s))[:MAX_SYMBOLS]
    client = client or AlpacaClient()
    before = client.requests
    local = now_et(clock)
    day = local.date()
    phase = session_phase(clock)
    with _lock:
        for gone in set(_history) - set(syms):
            _history.pop(gone, None)
            _premarket.pop(gone, None)
            _ema.pop(gone, None)
            _range.pop(gone, None)
    if not syms:
        return {"symbols": 0, "requests": 0}

    history = refresh_history(syms, clock, client)

    # Today's bars, from 04:00 ET until the history covers today (the 16:20 ET session check).
    weekday = local.weekday() < 5
    premarket_start, open_, close_ = _at(day, PREMARKET_AT), _at(day, OPEN), _at(day, CLOSE)
    cutoff = sip_cutoff(clock)
    sip: dict[str, list[dict]] = {}
    iex: dict[str, list[dict]] = {}
    trades: list[tuple[dict, str]] = []
    if weekday and clock >= premarket_start and last_completed_session(clock) < day:
        sip = _bars(client, syms, premarket_start, min(cutoff, close_) - timedelta(seconds=1), "sip")
        if phase == "premarket":
            trades = [(_latest_trades(client, syms, "iex"), "iex"), (_latest_trades(client, syms, "delayed_sip"), "delayed sip")]
        elif clock >= open_ and cutoff < close_:
            iex = _bars(client, syms, max(open_, cutoff), min(clock, close_), "iex")

    today_iso = day.isoformat()
    for sym in syms:
        base = prev_close(sym, day)
        # Premarket reading.
        if weekday and premarket_start <= clock < close_:
            reading = None
            final = cutoff >= open_
            if phase == "premarket" or final:
                found = _premarket_print(sym, day, sip, trades if phase == "premarket" else ())
                volume, through = _premarket_volume(sym, day, sip)
                if found and base:
                    price, at, source = found
                    reading = {
                        "session": today_iso,
                        "price": round(price, 4),
                        "time": at,
                        "source": source,
                        "prev_close": round(base, 4),
                        "change_pct": round((price / base - 1) * 100, 2),
                        "volume": volume,
                        "volume_through": through,
                        "final": final,
                    }
            with _lock:
                held = _premarket.get(sym)
                if reading is not None:
                    _premarket[sym] = reading
                elif held and held.get("session") != today_iso:
                    _premarket.pop(sym, None)

        # Day range: today's regular session so far; in premarket the premarket range (with the latest
        # print); otherwise the last completed session.
        today_bars = _today_regular_bars(sip, iex, sym, cutoff) if (sip or iex) else []
        with _lock:
            pm_now = _premarket.get(sym)
            last_session_range = (_history.get(sym) or {}).get("range")
        rng = None
        if today_bars:
            rng = make_range(today_bars, float(today_bars[-1]["c"]), "regular", today_iso)
        elif phase == "premarket":
            pm_bars = [b for b in sip.get(sym, []) if is_premarket(_ts(b["t"]), day)]
            if pm_now and pm_now.get("session") == today_iso:
                rng = make_range(pm_bars or [{"h": pm_now["price"], "l": pm_now["price"]}], pm_now["price"], "premarket", today_iso)
        else:
            rng = last_session_range
        with _lock:
            if rng:
                _range[sym] = dict(rng)
            else:
                _range.pop(sym, None)

        # EMA comparison.
        with _lock:
            hist = list((_history.get(sym) or {}).get("closes") or [])
        last_hist = hist[-1][0] if hist else ""
        today = [(ts, c) for ts, c in _today_regular(sip, iex, sym, cutoff) if ts > last_hist] if (sip or iex) else []
        closes = [c for _, c in hist + today]
        values = {n: ema(closes, n) for n in EMA_PERIODS}
        if not closes or any(v is None for v in values.values()):
            with _lock:
                _ema.pop(sym, None)
            continue
        with _lock:
            pm = _premarket.get(sym)
        if phase == "premarket" and pm and pm.get("session") == today_iso:
            price, basis, at = pm["price"], "premarket", pm["time"]
        elif today:
            price, basis, at = today[-1][1], "live" if phase == "regular" else "close", today[-1][0]
        else:
            price, basis, at = hist[-1][1], "close", hist[-1][0]
        hits, last_bar, until = reclaims(hist + today, clock)
        result = {
            "price": round(price, 4),
            "basis": basis,
            "time": at,
            "bar_time": (hist + today)[-1][0],
            "highlight": hits,
            "highlight_bar": last_bar,
            "highlight_until": until,
        }
        for n, v in values.items():
            result[f"ema{n}"] = round(v, 4)
            result[f"vs{n}"] = "above" if price > v else "below" if price < v else "at"
        with _lock:
            _ema[sym] = result

    return {"symbols": len(syms), "history": history, "requests": client.requests - before}


def snapshot(symbols: Iterable[str], now: Optional[datetime] = None) -> dict[str, dict]:
    """``{symbol: {"premarket": ... | None, "ema5m": ... | None}}`` for the page payloads. Never fetches.

    The premarket reading is shown from 04:00 to 16:00 ET on its own session's date and hidden otherwise.
    """
    local = now_et(now)
    show_pm = local.weekday() < 5 and PREMARKET_AT <= local.time() < CLOSE
    out: dict[str, dict] = {}
    with _lock:
        for sym in symbols:
            pm = _premarket.get(sym)
            if not (show_pm and pm and pm.get("session") == local.date().isoformat()):
                pm = None
            em = dict(_ema[sym]) if sym in _ema else None
            if em and (not em.get("highlight_until") or now_et(now) >= _ts(em["highlight_until"])):
                em["highlight"] = []
            hits = em["highlight"] if em else []
            out[sym] = {
                "premarket": dict(pm) if pm else None,
                "ema5m": em,
                # Alert-ready crossover state: "6", "20" or "6+20", and the completed bar it happened on.
                "ema5m_cross": "+".join(str(n) for n in hits) if hits else None,
                "ema5m_cross_bar": em["highlight_bar"] if hits else None,
                "day_range": dict(_range[sym]) if sym in _range else None,
            }
    return out


def clear() -> None:
    with _lock:
        _history.clear()
        _premarket.clear()
        _ema.clear()
        _range.clear()
