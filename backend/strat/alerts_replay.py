"""Replay the alert rules over past sessions' real Alpaca 15-minute bars and report what would have fired.

    cd backend && .venv/bin/python -m strat.alerts_replay --symbols AAPL,MU,SNDK,QQQ,SPY,CRWD --days 5

Same inputs as the live tab: SIP prices (the session is over, so SIP covers every bar), IEX volume
against the IEX time-of-day average of the 20 sessions before each day, EMAs seeded with the 5 sessions
before. Nothing is written to the database. Times are printed in Phoenix time.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from . import alerts_live
from .alerts import SETUP_NAMES, Settings, mark_top, metrics, simulate
from .alpaca import AlpacaClient
from .scheduler import CLOSE, ET, OPEN, PREMARKET_AT

PHX = ZoneInfo("America/Phoenix")


def _ts(raw) -> datetime:
    return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(timezone.utc)


def sessions(client: AlpacaClient, end: date, n: int) -> list[date]:
    """The last ``n`` sessions on or before ``end`` (from SPY daily bars)."""
    rows, _ = client.bars(["SPY"], "1Day", end - timedelta(days=n * 2 + 10), end=datetime.combine(end, time(23, 0), tzinfo=ET), feed="sip", adjustment="raw")
    days = sorted({_ts(b["t"]).astimezone(ET).date() for b in rows.get("SPY", [])})
    return [d for d in days if d <= end][-n:]


def prev_closes(client: AlpacaClient, symbols: list[str], day: date) -> dict[str, float]:
    rows, _ = client.bars(symbols, "1Day", day - timedelta(days=10), end=datetime.combine(day, time(0, 0), tzinfo=ET), feed="sip", adjustment="raw")
    out = {}
    for s, bars in rows.items():
        prior = [b for b in bars if _ts(b["t"]).astimezone(ET).date() < day]
        if prior:
            out[s] = float(prior[-1]["c"])
    return out


def replay_day(client: AlpacaClient, symbols: list[str], day: date, settings: Settings) -> dict:
    alerts_live.clear()
    alerts_live.ensure_profiles(client, symbols, day)
    start = datetime.combine(day, PREMARKET_AT, tzinfo=ET)
    close = datetime.combine(day, CLOSE, tzinfo=ET)
    sip, _ = client.bars(symbols, alerts_live.BARS, start, end=close - timedelta(seconds=1), feed="sip", adjustment="raw")
    iex, _ = client.bars(symbols, alerts_live.BARS, datetime.combine(day, OPEN, tzinfo=ET), end=close - timedelta(seconds=1), feed="iex", adjustment="raw")
    pcs = prev_closes(client, symbols, day)
    found, skipped, bars_seen = [], [], {}
    after = close.astimezone(timezone.utc) + timedelta(hours=1)
    for sym in symbols:
        bars, pm_low = alerts_live.merge_day(sip.get(sym, []), iex.get(sym, []), day, after, after)
        bars_seen[sym] = len(bars)
        if not bars:
            continue
        ctx = alerts_live.context_for(sym, pcs.get(sym), pm_low, len(bars))
        found.extend(simulate(sym, day.isoformat(), bars, ctx, settings, skipped))
    rows = [a.record() for a in found]
    top = mark_top(rows, settings.top_names)
    for r in rows:
        r["top"] = r["symbol"] in top
    rows.sort(key=lambda r: (r["fired_at"], r["symbol"]))
    profiles = {s: {"vol_sessions": (alerts_live._profiles.get(s) or {}).get("sessions", 0)} for s in symbols}
    return {"day": day.isoformat(), "alerts": rows, "skipped": skipped, "bars": bars_seen, "profiles": profiles}


def _phx(iso):
    return _ts(iso).astimezone(PHX).strftime("%H:%M") if iso else "-"


def print_day(res: dict) -> None:
    print(f"\n== {res['day']}  bars per symbol: {res['bars']}  volume-history sessions: "
          f"{ {s: p['vol_sessions'] for s, p in res['profiles'].items()} }")
    if not res["alerts"]:
        print("   no alerts")
    for r in res["alerts"]:
        risk = r["trigger_price"] - r["stop_price"]
        print(
            f"   {_phx(r['fired_at'])} PHX  {r['symbol']:<5} {r['setup']} {json.loads(r['details']).get('variant', ''):<8}"
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
        print("   tagged but filtered:", ", ".join(f"{k} x{v}" for k, v in sorted(reasons.items())))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbols", default="AAPL,MU,SNDK,QQQ,SPY,CRWD")
    ap.add_argument("--end", default=None, help="last session to replay (YYYY-MM-DD), default the latest")
    ap.add_argument("--days", type=int, default=1)
    ap.add_argument("--json", default=None, help="also write the full result here")
    args = ap.parse_args(argv)
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    client = AlpacaClient()
    end = date.fromisoformat(args.end) if args.end else datetime.now(ET).date()
    days = sessions(client, end, args.days)
    settings = Settings()
    results = []
    for d in days:
        res = replay_day(client, symbols, d, settings)
        print_day(res)
        results.append(res)
    allrows = [dict(r, filled=bool(r["filled"])) for res in results for r in res["alerts"]]
    print("\n== by setup (closed filled trades for win rate / R)")
    for m in metrics(allrows):
        if m["count"]:
            print(f"   {m['setup']:<3} {m['name']:<28} n={m['count']:<3} fill {m['fill_rate']}%  win {m['win_rate']}%  avgR {m['avg_r']}  totR {m['total_r']}")
    print(f"\n   Alpaca requests: {client.requests}")
    if args.json:
        with open(args.json, "w") as fh:
            json.dump({"symbols": symbols, "days": [d.isoformat() for d in days], "results": results, "metrics": metrics(allrows)}, fh, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
