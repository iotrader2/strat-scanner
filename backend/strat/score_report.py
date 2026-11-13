"""Validate the setup score against the R of the trades it was attached to.

Every alert stores the score it fired with (``details["score"]``: every component's points plus the raw inputs, see
:mod:`strat.setup_score`). Once enough trades have closed (about 200: two weeks at a dozen-plus trades a day), this
report shows which parts actually predict R, and above all the right tail, since the edge comes from the occasional
+3R trade rather than from the win rate:

* **Spearman** rank correlation of each component (points, and the raw input behind it) with R, and with the
  R >= 1.5 flag.
* **Tail lift**: the R >= 1.5 hit rate of the component's top quintile divided by the overall hit rate.
* **Score quintiles**: count, average and median R, hit rate of R >= 1.5, number of R >= 3 trades and total R per
  quintile of the full score.

Set the weights from this, not from a couple of trades. Under ``MIN_TRADES`` closed trades the report still runs but
says the sample is too small to act on.

    python -m strat.score_report [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--json]
"""

from __future__ import annotations

import argparse
import json
import math
from typing import Any, Iterable, Mapping, Optional

import pandas as pd

MIN_TRADES = 200
TAIL_R = 1.5
BIG_R = 3.0
QUINTILES = 5

# Raw inputs worth correlating, as (label, path into details["score"]["inputs"]).
RAW_INPUTS = (
    ("stop % / ATR %", ("entry", "stop_x_atr")),
    ("intraday excess (ATR)", ("entry", "intraday_excess_x_atr")),
    ("intraday excess (pts)", ("entry", "intraday_excess")),
    ("trigger-day rel. volume", ("entry", "relative_volume")),
    ("ATR5 / ATR20", ("base", "atr_ratio")),
    ("close stdev %", ("base", "close_std_pct")),
    ("5d / 50d volume", ("base", "volume_dryup")),
    ("ATRs from 10/21 EMA", ("base", "ema_dist_atr")),
    ("ATR(14) %", ("base", "atr14_pct")),
    ("10d RS percentile", ("short_rs", "pct_10d")),
    ("20d RS percentile", ("short_rs", "pct_20d")),
    ("10d excess vs QQQ", ("short_rs", "excess_10d")),
    ("20d excess vs QQQ", ("short_rs", "excess_20d")),
    ("RS line 20d high", ("short_rs", "rs_line_high")),
    ("1M/3M/6M RS percentile", ("rs_blended",)),
)


def _dig(d: Any, path: Iterable[str]) -> Optional[float]:
    for k in path:
        if not isinstance(d, Mapping):
            return None
        d = d.get(k)
    if isinstance(d, bool):
        return float(d)
    if isinstance(d, (int, float)) and math.isfinite(d):
        return float(d)
    return None


def trade_frame(rows: Iterable[Mapping]) -> pd.DataFrame:
    """One row per closed, filled alert that carries a setup score: R, the score, each group and component."""
    out = []
    for r in rows:
        details = r.get("details") if isinstance(r.get("details"), Mapping) else {}
        sc = details.get("score")
        R = r.get("r_multiple")
        if not r.get("filled") or not isinstance(R, (int, float)) or not isinstance(sc, Mapping):
            continue
        rec: dict[str, Any] = {
            "id": r.get("id"), "symbol": r.get("symbol"), "session": r.get("session"), "R": float(R),
            "version": sc.get("version"), "score": sc.get("score"), "scan_score": sc.get("scan_score"),
        }
        for g, v in (sc.get("groups") or {}).items():
            rec[f"group:{g}"] = v.get("points") if isinstance(v, Mapping) else None
        for k, v in (sc.get("components") or {}).items():
            rec[f"pts:{k}"] = v
        for label, path in RAW_INPUTS:
            rec[f"raw:{label}"] = _dig(sc.get("inputs"), path)
        out.append(rec)
    return pd.DataFrame(out)


def _spearman(x: pd.Series, y: pd.Series) -> Optional[float]:
    ok = x.notna() & y.notna()
    if ok.sum() < 5 or x[ok].nunique() < 2 or y[ok].nunique() < 2:
        return None
    v = x[ok].rank().corr(y[ok].rank())
    return None if v is None or not math.isfinite(v) else round(float(v), 3)


def _top_quintile_hit(x: pd.Series, hit: pd.Series) -> Optional[float]:
    ok = x.notna()
    if ok.sum() < QUINTILES * 2 or x[ok].nunique() < 2:
        return None
    cut = x[ok].quantile(1 - 1 / QUINTILES)
    top = hit[ok][x[ok] >= cut]
    return round(float(top.mean()), 3) if len(top) else None


def features(df: pd.DataFrame) -> list[dict]:
    """Per feature: Spearman with R and with the R >= 1.5 flag, top-quintile hit rate and its lift over the base."""
    if df.empty:
        return []
    hit = (df["R"] >= TAIL_R).astype(float)
    base = float(hit.mean()) if len(hit) else 0.0
    cols = ["score", "scan_score"] + sorted(c for c in df.columns if c.startswith(("group:", "pts:", "raw:")))
    out = []
    for c in cols:
        if c not in df:
            continue
        x = pd.to_numeric(df[c], errors="coerce")
        top = _top_quintile_hit(x, hit)
        out.append({
            "feature": c,
            "n": int(x.notna().sum()),
            "spearman_r": _spearman(x, df["R"]),
            "spearman_tail": _spearman(x, hit),
            "top_quintile_hit": top,
            "tail_lift": round(top / base, 2) if top is not None and base > 0 else None,
        })
    return out


def quintiles(df: pd.DataFrame, column: str = "score") -> list[dict]:
    """Score quintiles (1 = lowest): count, average / median R, hit rate of R >= 1.5, R >= 3 count, total R."""
    x = pd.to_numeric(df.get(column), errors="coerce") if not df.empty else pd.Series(dtype=float)
    ok = df[x.notna()] if not df.empty else df
    if len(ok) < QUINTILES:
        return []
    q = pd.qcut(x[x.notna()].rank(method="first"), QUINTILES, labels=False) + 1
    out = []
    for i in range(1, QUINTILES + 1):
        part = ok[q == i]
        R = part["R"]
        out.append({
            "quintile": i,
            "n": int(len(part)),
            "score_min": round(float(x[q.index][q == i].min()), 1),
            "score_max": round(float(x[q.index][q == i].max()), 1),
            "avg_r": round(float(R.mean()), 3),
            "median_r": round(float(R.median()), 3),
            "hit_tail": round(float((R >= TAIL_R).mean()), 3),
            "big_wins": int((R >= BIG_R).sum()),
            "total_r": round(float(R.sum()), 2),
        })
    return out


def report(rows: Iterable[Mapping]) -> dict:
    df = trade_frame(rows)
    n = int(len(df))
    return {
        "trades": n,
        "min_trades": MIN_TRADES,
        "enough": n >= MIN_TRADES,
        "versions": sorted({int(v) for v in df["version"].dropna()}) if n else [],
        "tail_r": TAIL_R,
        "overall": None if not n else {
            "avg_r": round(float(df["R"].mean()), 3),
            "hit_tail": round(float((df["R"] >= TAIL_R).mean()), 3),
            "big_wins": int((df["R"] >= BIG_R).sum()),
            "total_r": round(float(df["R"].sum()), 2),
        },
        "quintiles": quintiles(df),
        "features": features(df),
    }


def _fmt(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.3f}".rstrip("0").rstrip(".") if abs(v) < 1000 else f"{v:,.0f}"
    return str(v)


def markdown(rep: Mapping) -> str:
    lines = [f"# Setup score vs R — {rep['trades']} closed trades with a score", ""]
    if not rep["enough"]:
        lines += [
            f"> **Too few trades to act on** ({rep['trades']} of {rep['min_trades']}). "
            "Read this as a progress check, not as a reason to change the weights.", "",
        ]
    o = rep["overall"]
    if not o:
        return "\n".join(lines + ["No closed trade carries a setup score yet."])
    lines += [
        f"Overall: avg R {o['avg_r']}, R ≥ {rep['tail_r']} on {o['hit_tail'] * 100:.0f}% of trades, "
        f"{o['big_wins']} trades ≥ {BIG_R:g}R, total {o['total_r']}R.", "",
        "## Score quintiles", "",
        f"| Quintile | Trades | Score | Avg R | Median R | R ≥ {rep['tail_r']} | ≥ {BIG_R:g}R | Total R |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for q in rep["quintiles"]:
        lines.append(
            f"| {q['quintile']} | {q['n']} | {q['score_min']}–{q['score_max']} | {q['avg_r']} | {q['median_r']} | "
            f"{q['hit_tail'] * 100:.0f}% | {q['big_wins']} | {q['total_r']} |"
        )
    lines += [
        "", "## Components", "",
        f"Sorted by Spearman with the R ≥ {rep['tail_r']} flag. *Tail lift* = R ≥ {rep['tail_r']} hit rate of the "
        "feature's top quintile ÷ the overall hit rate (for raw inputs where lower is better, such as stop / ATR, "
        "read a negative Spearman and a lift below 1 as the good direction).", "",
        "| Feature | n | Spearman (R) | Spearman (tail) | Top-quintile hit | Tail lift |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    feats = sorted(rep["features"], key=lambda f: -(f["spearman_tail"] if f["spearman_tail"] is not None else -9))
    for f in feats:
        lines.append(
            f"| {f['feature']} | {f['n']} | {_fmt(f['spearman_r'])} | {_fmt(f['spearman_tail'])} | "
            f"{_fmt(f['top_quintile_hit'])} | {_fmt(f['tail_lift'])} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: Optional[list[str]] = None) -> None:
    from . import alerts_store

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    rep = report(alerts_store.list_for_metrics(start=args.start, end=args.end))
    print(json.dumps(rep, indent=2) if args.json else markdown(rep))


if __name__ == "__main__":
    main()
