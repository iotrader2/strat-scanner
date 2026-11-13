"""Replay the alert rules over past sessions' real Alpaca 15-minute bars and report what would have fired.

    cd backend && .venv/bin/python -m strat.alerts_replay --symbols AAPL,MU,SNDK,CRWD --days 5

Same inputs as the live tab: SIP where it has the bar, Yahoo's consolidated 15-minute chart for any
bar SIP does not have yet, IEX only if that symbol's Yahoo request fails. The 120 / 240 / 480 EMAs are
carried over from the weeks before each day. Nothing is written to the database. Times are printed
in Phoenix time. The score filter is not applied: pass the names to check.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import logging

from . import alerts_live
from .alerts import MIN_ALERT_ATR_PCT, Settings, mark_top, metrics, simulate
from .yahoo_15m import fetch_yahoo_15m

log = logging.getLogger(__name__)
from .alpaca import AlpacaClient
from .scheduler import CLOSE, ET, OPEN

PHX = ZoneInfo("America/Phoenix")


def _ts(raw) -> datetime:
    return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(timezone.utc)


def sessions(client: AlpacaClient, end: date, n: int) -> list[date]:
    """The last ``n`` sessions on or before ``end`` (from SPY daily bars)."""
    rows, _ = client.bars(["SPY"], "1Day", end - timedelta(days=n * 2 + 10), end=datetime.combine(end, time(23, 0), tzinfo=ET), feed="sip", adjustment="raw")
    days = sorted({_ts(b["t"]).astimezone(ET).date() for b in rows.get("SPY", [])})
    return [d for d in days if d <= end][-n:]


def replay_day(client: AlpacaClient, symbols: list[str], day: date, settings: Settings) -> dict:
    alerts_live.clear()
    alerts_live.ensure_profiles(client, symbols, day)
    start = datetime.combine(day, OPEN, tzinfo=ET)
    close = datetime.combine(day, CLOSE, tzinfo=ET)
    sip, _ = client.bars(symbols, alerts_live.BARS, start, end=close - timedelta(seconds=1), feed="sip", adjustment="raw")
    iex, _ = client.bars(symbols, alerts_live.BARS, datetime.combine(day, OPEN, tzinfo=ET), end=close - timedelta(seconds=1), feed="iex", adjustment="raw")
    try:
        yahoo, _failed = fetch_yahoo_15m(symbols, day, close.astimezone(timezone.utc))
    except Exception:
        log.exception("replay Yahoo 15m failed; bars SIP does not have stay on IEX")
        yahoo = {}
    found, skipped, bars_seen = [], [], {}
    after = close.astimezone(timezone.utc) + timedelta(hours=1)
    # Daily trim check: the last bar's close stands in for the 15:59 ET price. A replay covers one
    # day only, so a crossback trade still open after that check is shown as triggered (held).
    daily_closes = alerts_live.ensure_daily_closes(client, symbols, day)
    mark_at = (close - timedelta(minutes=1)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for sym in symbols:
        bars, _ = alerts_live.merge_day(sip.get(sym, []), iex.get(sym, []), day, after, after, yahoo.get(sym))
        bars_seen[sym] = len(bars)
        if not bars:
            continue
        mark = {"price": float(bars[-1]["c"]), "at": mark_at, "late": False}
        ctx = alerts_live.context_for(sym, len(bars), daily_closes=daily_closes.get(sym), close_mark=mark)
        found.extend(simulate(sym, day.isoformat(), bars, ctx, settings, skipped))
    rows = [a.record() for a in found]
    top = mark_top(rows, settings.top_names)
    for r in rows:
        r["top"] = r["symbol"] in top
    rows.sort(key=lambda r: (r["fired_at"], r["symbol"]))
    profiles = {s: {"emas": sorted((alerts_live._profiles.get(s) or {}).get("tail", {}))} for s in symbols}
    return {"day": day.isoformat(), "alerts": rows, "skipped": skipped, "bars": bars_seen, "profiles": profiles}


def _phx(iso):
    return _ts(iso).astimezone(PHX).strftime("%H:%M") if iso else "-"


def print_day(res: dict) -> None:
    print(f"\n== {res['day']}  bars per symbol: {res['bars']}  EMAs known: "
          f"{ {s: p['emas'] for s, p in res['profiles'].items()} }")
    if not res["alerts"]:
        print("   no alerts")
    for r in res["alerts"]:
        risk = r["trigger_price"] - r["stop_price"]
        print(
            f"   {_phx(r['fired_at'])} PHX  {r['symbol']:<5} EMA {r['setup']:<4} @ {json.loads(r['details']).get('ma', 0):>9.2f}"
            f" trig {r['trigger_price']:>9.2f} stop {r['stop_price']:>9.2f} ({risk / r['trigger_price'] * 100:4.2f}%, ${risk:.2f}/sh)"
            f"  {r['status']:<9}"
            + (f" fill {r['fill_price']:.2f} @{_phx(r['fill_at'])}" if r["filled"] else "")
            + (f" BE@{_phx(r['breakeven_at'])}" if r["breakeven_at"] else "")
            + (f" exit {r['exit_price']:.2f} @{_phx(r['exit_at'])} ({r['exit_reason']})" if r["exit_price"] is not None else "")
            + (f"  R={r['r_multiple']:+.2f}" if r["r_multiple"] is not None else "")
            + ("  TOP" if r["top"] else "")
        )
    if res["skipped"]:
        reasons: dict[str, int] = {}
        for s in res["skipped"]:
            reasons[f"{s['setup']}: {s['reason']}"] = reasons.get(f"{s['setup']}: {s['reason']}", 0) + 1
        print("   touches not alerted:", ", ".join(f"{k} x{v}" for k, v in sorted(reasons.items())))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbols", default="AAPL,MU,SNDK,CRWD")
    ap.add_argument("--end", default=None, help="last session to replay (YYYY-MM-DD), default the latest")
    ap.add_argument("--days", type=int, default=1)
    ap.add_argument("--json", default=None, help="also write the full result here")
    args = ap.parse_args(argv)
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    client = AlpacaClient()
    end = date.fromisoformat(args.end) if args.end else datetime.now(ET).date()
    days = sessions(client, end, args.days)
    settings = Settings()
    atr = "Any" if settings.atr_filter_off() else f"{settings.atr_pct_min:g}–{settings.atr_pct_max:g}%"
    print(
        f"name screen: ATR % > {MIN_ALERT_ATR_PCT:g} (always), avg $ volume >= {settings.min_avg_dollar_volume:,.0f}, "
        f"ATR % {atr}. Names you added to the watchlist skip the sliders but not the ATR floor. "
        "This replay checks the symbols you passed."
    )
    results = []
    for d in days:
        res = replay_day(client, symbols, d, settings)
        print_day(res)
        results.append(res)
    allrows = [dict(r, filled=bool(r["filled"])) for res in results for r in res["alerts"]]
    print("\n== by daily setup (closed filled trades for win rate / R; an alert counts under each setup)")
    for m in metrics(allrows):
        if m["count"]:
            print(f"   {m['setup']:<24} {m['name']:<36} n={m['count']:<3} fill {m['fill_rate']}%  win {m['win_rate']}%  avgR {m['avg_r']}  totR {m['total_r']}")
    print(f"\n   Alpaca requests: {client.requests}")
    if args.json:
        with open(args.json, "w") as fh:
            json.dump({
                "symbols": symbols,
                "days": [d.isoformat() for d in days],
                "screen": {
                    "min_avg_dollar_volume": settings.min_avg_dollar_volume,
                    "atr_pct_min": settings.atr_pct_min,
                    "atr_pct_max": settings.atr_pct_max,
                },
                "results": results,
                "metrics": metrics(allrows),
            }, fh, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
