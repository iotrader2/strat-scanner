"""Validate ``data/themes.yaml`` against price data (``npm run themes:report``).

For the last ~6 months of daily returns (126 sessions) it computes each member's average correlation to the other
primary members of its theme, both raw and *beta-adjusted* (the residual after removing each stock's beta to SPY, so a
theme is not "cohesive" merely because everything rises with the market). It then

* flags members whose in-theme correlation is low, or lower than their correlation to another theme,
* lists unassigned stocks that correlate strongly with a theme, and
* runs average-linkage hierarchical clustering on the residual correlations to suggest groupings.

The report only suggests. Nothing is reassigned: the curated map always wins.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional

import numpy as np
import pandas as pd

from . import config, data
from .themes import ThemeMap, load_themes
from .universe import load_universe

WINDOW = 126  # trading sessions, about six months
MIN_OBS = 60  # sessions a stock needs inside the window to be included
MARKET = "SPY"

LOW_CORR = 0.15  # in-theme residual correlation below this is "low"
BETTER_MARGIN = 0.10  # another theme fits better by at least this much (residual correlation)
UNASSIGNED_MIN = 0.30  # an unassigned stock correlates at least this much with a theme
CLUSTER_CORR = 0.45  # average-linkage clusters are cut where the average residual correlation falls to this
MIN_CLUSTER = 4

REPORT_PATH = config.DATA_DIR / "themes_report.md"


def returns_frame(daily_by_symbol: Mapping[str, pd.DataFrame], window: int = WINDOW, min_obs: int = MIN_OBS) -> pd.DataFrame:
    """Daily close-to-close returns, last ``window`` sessions, for symbols with at least ``min_obs`` observations."""
    closes = pd.DataFrame({s: d["close"] for s, d in daily_by_symbol.items() if len(d) > 2})
    rets = closes.sort_index().pct_change(fill_method=None).iloc[-window:]
    return rets.loc[:, rets.notna().sum() >= min_obs]


def residual_returns(rets: pd.DataFrame, market: Optional[pd.Series] = None) -> pd.DataFrame:
    """Returns with each stock's beta to ``market`` removed (OLS over the window; market defaults to the cross-section mean)."""
    if market is None:
        market = rets.mean(axis=1)
    market = market.reindex(rets.index)
    out = {}
    for s in rets.columns:
        pair = pd.concat([rets[s], market], axis=1).dropna()
        if len(pair) < 3 or pair.iloc[:, 1].var() == 0:
            out[s] = rets[s]
            continue
        beta = pair.iloc[:, 0].cov(pair.iloc[:, 1]) / pair.iloc[:, 1].var()
        out[s] = rets[s] - beta * market
    return pd.DataFrame(out)


def theme_affinity(corr: pd.DataFrame, themes: ThemeMap) -> pd.DataFrame:
    """Average correlation of every stock to each theme's other primary members (self excluded): rows stocks, columns theme ids."""
    symbols = list(corr.columns)
    c = corr.fillna(0.0).to_numpy().copy()
    np.fill_diagonal(c, 0.0)
    cols = {}
    for t in themes.themes:
        member = np.array([s in set(t.members) for s in symbols], dtype=float)
        total = c @ member
        count = member.sum() - member  # members other than the stock itself
        with np.errstate(invalid="ignore", divide="ignore"):
            cols[t.id] = np.where(count > 0, total / np.where(count > 0, count, 1), np.nan)
    return pd.DataFrame(cols, index=symbols)


@dataclass
class MemberCheck:
    symbol: str
    theme: str
    own: float  # beta-adjusted average correlation to the theme's other members
    own_raw: float
    best_theme: str
    best: float
    reasons: list[str] = field(default_factory=list)
    kept: bool = False  # listed under the theme's `keep:` (reviewed, kept on purpose)

    @property
    def flagged(self) -> bool:
        return bool(self.reasons)

    @property
    def to_review(self) -> bool:
        return self.flagged and not self.kept


def check_members(
    themes: ThemeMap,
    resid_affinity: pd.DataFrame,
    raw_affinity: pd.DataFrame,
    low: float = LOW_CORR,
    margin: float = BETTER_MARGIN,
) -> list[MemberCheck]:
    """Per-member in-theme correlation, flagged when low or when another theme fits clearly better. Curated map is unchanged."""
    out = []
    for t in themes.themes:
        for s in t.members:
            if s not in resid_affinity.index or np.isnan(resid_affinity.at[s, t.id]):
                continue
            row = resid_affinity.loc[s].drop(t.id).dropna()
            best_theme, best = (row.idxmax(), float(row.max())) if len(row) else ("", float("nan"))
            own = float(resid_affinity.at[s, t.id])
            check = MemberCheck(s, t.id, own, float(raw_affinity.at[s, t.id]), best_theme, best, kept=s in t.keep)
            if own < low:
                check.reasons.append(f"low in-theme correlation ({own:.2f} < {low:.2f})")
            if best_theme and best - own >= margin:
                check.reasons.append(f"fits {best_theme} better ({best:.2f} vs {own:.2f})")
            out.append(check)
    return out


def unassigned_candidates(
    themes: ThemeMap, resid_affinity: pd.DataFrame, stocks: set[str], minimum: float = UNASSIGNED_MIN
) -> list[tuple[str, str, float]]:
    """Stocks with no primary theme whose best theme correlation is at least ``minimum``: (symbol, theme id, corr)."""
    out = []
    for s in resid_affinity.index:
        if s not in stocks or s in themes.primary:
            continue
        row = resid_affinity.loc[s].dropna()
        if len(row) and float(row.max()) >= minimum:
            out.append((s, str(row.idxmax()), float(row.max())))
    return sorted(out, key=lambda x: -x[2])


def average_linkage(corr: pd.DataFrame, min_corr: float = CLUSTER_CORR) -> list[list[str]]:
    """Agglomerative clustering (average linkage on 1 - correlation) stopped when the best merge is below ``min_corr``."""
    symbols = list(corr.columns)
    dist = 1.0 - corr.fillna(0.0).to_numpy()
    n = len(symbols)
    np.fill_diagonal(dist, np.inf)
    sizes = np.ones(n)
    members: dict[int, list[str]] = {i: [s] for i, s in enumerate(symbols)}
    active = np.ones(n, dtype=bool)
    limit = 1.0 - min_corr
    while active.sum() > 1:
        masked = np.where(active[:, None] & active[None, :], dist, np.inf)
        flat = int(np.argmin(masked))
        a, b = divmod(flat, n)
        if masked[a, b] > limit:
            break
        merged = (sizes[a] * dist[a] + sizes[b] * dist[b]) / (sizes[a] + sizes[b])
        dist[a, :] = merged
        dist[:, a] = merged
        dist[a, a] = np.inf
        sizes[a] += sizes[b]
        members[a] += members.pop(b)
        active[b] = False
        dist[b, :] = np.inf
        dist[:, b] = np.inf
    return sorted(members.values(), key=len, reverse=True)


def cluster_summary(clusters: list[list[str]], themes: ThemeMap, min_size: int = MIN_CLUSTER) -> list[dict]:
    """For each cluster: its dominant theme, how pure it is, the unassigned names inside and members of other themes."""
    out = []
    for members in clusters:
        if len(members) < min_size:
            continue
        counts: dict[str, int] = {}
        for s in members:
            if s in themes.primary:
                counts[themes.primary[s]] = counts.get(themes.primary[s], 0) + 1
        dominant = max(counts, key=counts.get) if counts else None
        out.append(
            {
                "size": len(members),
                "dominant": dominant,
                "purity": counts[dominant] / sum(counts.values()) if dominant else 0.0,
                "themes": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
                "unassigned": sorted(s for s in members if s not in themes.primary),
                "outsiders": sorted(s for s in members if dominant and s in themes.primary and themes.primary[s] != dominant),
                "members": sorted(members),
            }
        )
    return out


@dataclass
class Report:
    start: str
    end: str
    sessions: int
    checks: list[MemberCheck]
    cohesion: pd.DataFrame  # per theme: members, avg raw corr, avg residual corr, flagged
    candidates: list[tuple[str, str, float]]
    clusters: list[dict]
    skipped: list[str]  # themed symbols without enough history in the window


def build_report(themes: ThemeMap, daily_by_symbol: Mapping[str, pd.DataFrame], stocks: set[str]) -> Report:
    rets = returns_frame(daily_by_symbol)
    market = rets[MARKET] if MARKET in rets else None
    resid = residual_returns(rets, market)
    stock_cols = [s for s in rets.columns if s in stocks]
    raw_corr = rets[stock_cols].corr(min_periods=MIN_OBS)
    res_corr = resid[stock_cols].corr(min_periods=MIN_OBS)
    raw_aff = theme_affinity(raw_corr, themes)
    res_aff = theme_affinity(res_corr, themes)
    checks = check_members(themes, res_aff, raw_aff)

    rows = []
    for t in themes.themes:
        mine = [c for c in checks if c.theme == t.id]
        rows.append(
            {
                "theme": t.id,
                "name": t.name,
                "members": len(t.members),
                "with_data": len(mine),
                "raw": float(np.mean([c.own_raw for c in mine])) if mine else float("nan"),
                "resid": float(np.mean([c.own for c in mine])) if mine else float("nan"),
                "flagged": sum(c.flagged for c in mine),
                "to_review": sum(c.to_review for c in mine),
            }
        )
    clusters = cluster_summary(average_linkage(res_corr), themes)
    return Report(
        start=rets.index[0].strftime("%Y-%m-%d"),
        end=rets.index[-1].strftime("%Y-%m-%d"),
        sessions=len(rets),
        checks=checks,
        cohesion=pd.DataFrame(rows).set_index("theme"),
        candidates=unassigned_candidates(themes, res_aff, stocks),
        clusters=clusters,
        skipped=[s for s in themes.symbols() if s in stocks and s not in stock_cols],
    )


def render(report: Report, themes: ThemeMap) -> str:
    names = {t.id: t.name for t in themes.themes}
    flagged = [c for c in report.checks if c.flagged]
    avg_res = report.cohesion["resid"].mean()
    avg_raw = report.cohesion["raw"].mean()
    lines = [
        "# Theme validation report",
        "",
        f"Daily returns {report.start} → {report.end} ({report.sessions} sessions). Correlation is each member's average to the "
        f"other primary members of its theme; *beta-adjusted* removes each stock's beta to {MARKET} first.",
        "",
        f"- {len(themes.themes)} themes, {len(report.checks)} members checked, **{len(flagged)} flagged** "
        f"({sum(c.kept for c in flagged)} reviewed and kept by curation, **{sum(c.to_review for c in flagged)} to review**)",
        f"- average in-theme correlation: raw {avg_raw:.2f}, beta-adjusted {avg_res:.2f}",
        f"- flags: beta-adjusted correlation below {LOW_CORR:.2f}, or another theme fits better by {BETTER_MARGIN:.2f}+",
    ]
    if report.skipped:
        lines.append(f"- not enough history in the window: {' '.join(report.skipped)}")
    lines += ["", "## Theme cohesion", "", "| Theme | Members | Raw corr | Beta-adj corr | Flagged (to review) |", "| --- | ---: | ---: | ---: | ---: |"]
    for tid, r in report.cohesion.sort_values("resid", ascending=False).iterrows():
        lines.append(f"| {r['name']} | {int(r['with_data'])} | {r['raw']:.2f} | {r['resid']:.2f} | {int(r['flagged'])} ({int(r['to_review'])}) |")
    lines += ["", "## Flagged members", ""]
    if flagged:
        lines += ["| Symbol | Theme | In-theme (adj / raw) | Best other theme | Why | Status |", "| --- | --- | --- | --- | --- | --- |"]
        for c in sorted(flagged, key=lambda c: c.own):
            alt = f"{names.get(c.best_theme, c.best_theme)} {c.best:.2f}" if c.best_theme else "—"
            lines.append(f"| {c.symbol} | {names[c.theme]} | {c.own:.2f} / {c.own_raw:.2f} | {alt} | {'; '.join(c.reasons)} | {'kept (curated)' if c.kept else 'review'} |")
    else:
        lines.append("None.")
    lines += ["", "## Unassigned stocks that correlate with a theme", ""]
    if report.candidates:
        lines += ["| Symbol | Best theme | Beta-adj corr |", "| --- | --- | ---: |"]
        lines += [f"| {s} | {names[t]} | {v:.2f} |" for s, t, v in report.candidates[:60]]
    else:
        lines.append("None.")
    lines += ["", f"## Clusters (average linkage, beta-adjusted correlation ≥ {CLUSTER_CORR:.2f}, {MIN_CLUSTER}+ names)", ""]
    for cl in report.clusters:
        dom = names.get(cl["dominant"], "—") if cl["dominant"] else "no theme"
        lines.append(f"- **{dom}** · {cl['size']} names · {cl['purity'] * 100:.0f}% from that theme")
        if cl["unassigned"]:
            lines.append(f"  - unassigned: {' '.join(cl['unassigned'])}")
        if cl["outsiders"]:
            lines.append(f"  - other themes: {' '.join(f'{s} ({names[themes.primary[s]]})' for s in cl['outsiders'])}")
    lines.append("")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate data/themes.yaml against price correlations")
    parser.add_argument("--out", type=Path, default=REPORT_PATH, help="where to write the markdown report")
    parser.add_argument("--no-write", action="store_true", help="print only")
    args = parser.parse_args(argv)

    themes = load_themes()
    stocks = {m.symbol for m in load_universe() if m.kind == "stock"}
    daily = data.load_all_daily()
    report = build_report(themes, daily, stocks)
    text = render(report, themes)
    print(text)
    if not args.no_write:
        args.out.write_text(text)
        print(f"Wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
