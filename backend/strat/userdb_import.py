"""One-time load of the watchlist and positions into the user database (Postgres when DATABASE_URL is set).

Sources:

* ``--positions FILE --watchlist FILE``: the JSON bodies of ``GET /api/positions`` and ``GET /api/watchlist``
  (the stage backups). List order, share counts, buy prices, entry dates and trims (with their times)
  are kept. Off-universe watchlist names get their name / sector / industry row too.
* ``--from-sqlite PATH``: copy every user table (watchlist, positions, trims, off-universe symbols, alerts,
  alert settings) from a SQLite cache file.

The target must be empty unless ``--replace`` is given. ``--dry-run`` prints what would be written.
The database URL is read from the environment and never printed.

    cd backend && DATABASE_URL="$(cat ~/secrets/...)" .venv/bin/python -m strat.userdb_import \\
        --positions ../stage-positions.json --watchlist ../stage-watchlist.json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import userdb
from .universe import load_universe


def rows_from_backups(positions: dict, watchlist: dict) -> dict[str, list[tuple]]:
    universe = {m.symbol for m in load_universe()}
    out: dict[str, list[tuple]] = {t: [] for t in ("watchlist", "positions", "position_trims", "extra_symbols")}
    now = datetime.now(timezone.utc)
    # added_at keeps the original order; stamped "now" plus a microsecond per row.
    for i, sym in enumerate(watchlist.get("symbols") or []):
        out["watchlist"].append((sym, (now + timedelta(microseconds=i)).isoformat(timespec="microseconds")))
    for i, p in enumerate(positions.get("positions") or []):
        out["positions"].append(
            (p["symbol"], p["entry_price"], p.get("shares"), p["entry_date"], (now + timedelta(microseconds=i)).isoformat(timespec="microseconds"))
        )
        for t in p.get("trims") or []:
            out["position_trims"].append((p["symbol"], t["shares"], t["price"], t["trimmed_at"]))
    rows = {r["symbol"]: r for r in (watchlist.get("rows") or [])}
    for p in positions.get("positions") or []:
        if p.get("row"):
            rows.setdefault(p["symbol"], p["row"])
    for sym, r in rows.items():
        if sym not in universe:
            out["extra_symbols"].append((sym, r.get("name") or sym, r.get("sector") or "", r.get("kind") or "stock", r.get("industry") or ""))
    return out


def rows_from_sqlite(path: Path) -> dict[str, list[tuple]]:
    conn = sqlite3.connect(path)
    try:
        have = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        out = {}
        for table, cols in COPY_COLUMNS.items():
            out[table] = conn.execute(f"SELECT {', '.join(cols)} FROM {table}").fetchall() if table in have else []
        return out
    finally:
        conn.close()


COPY_COLUMNS = {
    "watchlist": ("symbol", "added_at"),
    "positions": ("symbol", "entry_price", "shares", "entry_date", "added_at"),
    "position_trims": ("symbol", "shares", "price", "trimmed_at"),
    "extra_symbols": ("symbol", "name", "sector", "kind", "industry"),
    "alerts": None,  # filled below
    "alert_settings": ("key", "value"),
}
from .alerts_store import COLUMNS as _ALERT_COLUMNS  # noqa: E402

COPY_COLUMNS["alerts"] = tuple(c for c in _ALERT_COLUMNS if c != "id")


def write(rows: dict[str, list[tuple]], replace: bool) -> dict[str, int]:
    with userdb.connect() as conn:
        existing = {t: int(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]) for t in rows}
        busy = {t: n for t, n in existing.items() if n}
        if busy and not replace:
            raise SystemExit(f"Target already has rows {busy}; rerun with --replace to overwrite those tables.")
        written = {}
        for table, values in rows.items():
            cols = COPY_COLUMNS[table]
            if replace:
                conn.execute(f"DELETE FROM {table}")
            for v in values:
                conn.execute(f"INSERT INTO {table}({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", tuple(v))
            written[table] = len(values)
    userdb.bump()
    return written


def summary() -> dict:
    with userdb.connect() as conn:
        return {
            "watchlist": [r[0] for r in conn.execute("SELECT symbol FROM watchlist ORDER BY added_at, symbol").fetchall()],
            "positions": [
                {"symbol": r[0], "entry_price": r[1], "shares": r[2], "entry_date": r[3]}
                for r in conn.execute("SELECT symbol, entry_price, shares, entry_date FROM positions ORDER BY added_at, symbol").fetchall()
            ],
            "trims": int(conn.execute("SELECT COUNT(*) FROM position_trims").fetchone()[0]),
            "alerts": int(conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]),
        }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--positions", type=Path)
    ap.add_argument("--watchlist", type=Path)
    ap.add_argument("--from-sqlite", type=Path)
    ap.add_argument("--replace", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    if args.from_sqlite:
        rows = rows_from_sqlite(args.from_sqlite)
    elif args.positions and args.watchlist:
        rows = rows_from_backups(json.loads(args.positions.read_text()), json.loads(args.watchlist.read_text()))
    else:
        ap.error("give --positions and --watchlist, or --from-sqlite")
    target = userdb.describe()
    counts = {t: len(v) for t, v in rows.items()}
    print(f"target: {target}  rows: {counts}")
    if args.dry_run:
        return 0
    print("written:", write(rows, args.replace))
    print("now in target:", json.dumps(summary()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
