"""Curated theme groups: stocks that actually move together (the "sector" unit of the app).

``data/themes.yaml`` is the source of truth. A stock has at most one *primary* theme (it drives the theme's equal-weight
index and the stock's Theme strength score) and may be listed as a *secondary* ("also") member of others (shown on those
theme cards and matched by the scanner's theme filter, but not part of their index). Correlation analysis only ever
*suggests* changes (``python -m strat.themes_report``); nothing is reassigned automatically.

``python -m strat.themes sync`` adds theme tickers that are not yet in the universe, when they pass the liquidity filters.
"""

from __future__ import annotations

import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Mapping, Optional, Sequence

import pandas as pd

from . import config
from .universe import UNIVERSE_CSV, Member, load_universe, to_yahoo, write_universe

THEMES_YAML = config.DATA_DIR / "themes.yaml"
THEME_INDEX_TAG = "THEME"  # `indexes` value of universe rows that exist only because a theme lists them

MIN_PRIMARY_MEMBERS = 3
ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")

# Liquidity gate for adding an off-universe theme ticker to the universe. Price and volume sliders in the Stock Scanner
# stay user-adjustable, so the gate only keeps out illiquid names: average dollar volume as in STRAT_MIN_DOLLAR_VOLUME,
# at least the lowest share-volume slider position, and not a sub-$1 stock.
SYNC_MIN_PRICE = 1.0
SYNC_MIN_AVG_VOLUME = 100_000.0
SYNC_MAX_STALE_DAYS = 10  # a last bar older than this means the ticker is delisted or halted


class ThemeError(ValueError):
    """The theme map is invalid; ``problems`` lists every issue found."""

    def __init__(self, problems: list[str]):
        super().__init__("invalid themes: " + "; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class Theme:
    id: str
    name: str
    description: str
    members: tuple[str, ...]  # primary members: they define the theme index
    also: tuple[str, ...] = ()  # secondary members: shown on the card and matched by the scanner filter
    keep: tuple[str, ...] = ()  # primary members reviewed against the correlation report and kept on purpose

    @property
    def everyone(self) -> tuple[str, ...]:
        return self.members + self.also


@dataclass
class ThemeMap:
    version: int
    themes: list[Theme]
    primary: dict[str, str] = field(default_factory=dict)  # symbol -> primary theme id
    secondary: dict[str, list[str]] = field(default_factory=dict)  # symbol -> secondary theme ids

    def __post_init__(self) -> None:
        self.primary = {s: t.id for t in self.themes for s in t.members}
        self.secondary = {}
        for t in self.themes:
            for s in t.also:
                self.secondary.setdefault(s, []).append(t.id)

    def by_id(self, theme_id: str) -> Optional[Theme]:
        return next((t for t in self.themes if t.id == theme_id), None)

    def theme_of(self, symbol: str) -> Optional[Theme]:
        tid = self.primary.get(symbol)
        return self.by_id(tid) if tid else None

    def symbols(self) -> list[str]:
        return list(dict.fromkeys(s for t in self.themes for s in t.everyone))


def _symbols(raw: object, where: str, problems: list[str]) -> list[str]:
    """Tickers from a whitespace/comma separated string (a YAML list is accepted if every entry is a string)."""
    if raw is None:
        return []
    if isinstance(raw, str):
        items: list = [t for t in re.split(r"[\s,]+", raw) if t]
    elif isinstance(raw, list):
        items = raw
    else:
        problems.append(f"{where}: expected a list of tickers")
        return []
    out = []
    for item in items:
        if not isinstance(item, str):
            problems.append(f"{where}: {item!r} is not a ticker string (quote tickers such as ON or NO in YAML)")
            continue
        out.append(to_yahoo(item))
    return out


def parse_themes(raw: object) -> ThemeMap:
    """Build and validate a ThemeMap from the parsed YAML document; raises ThemeError listing every problem."""
    problems: list[str] = []
    if not isinstance(raw, Mapping) or not isinstance(raw.get("themes"), Mapping):
        raise ThemeError(["the file needs a top-level `themes:` mapping"])
    version = raw.get("version")
    if not isinstance(version, int):
        problems.append("missing integer `version`")

    themes: list[Theme] = []
    names: set[str] = set()
    owner: dict[str, str] = {}
    for tid, body in raw["themes"].items():
        tid = str(tid)
        if not ID_RE.match(tid):
            problems.append(f"theme id {tid!r} must be lowercase letters, digits and dashes")
        if not isinstance(body, Mapping):
            problems.append(f"{tid}: expected a mapping with name and members")
            continue
        name = str(body.get("name") or "").strip()
        if not name:
            problems.append(f"{tid}: missing name")
        elif name.lower() in names:
            problems.append(f"{tid}: duplicate theme name {name!r}")
        names.add(name.lower())
        members = _symbols(body.get("members"), f"{tid}.members", problems)
        also = _symbols(body.get("also"), f"{tid}.also", problems)
        keep = _symbols(body.get("keep"), f"{tid}.keep", problems)
        stray = sorted(set(keep) - set(members))
        if stray:
            problems.append(f"{tid}.keep: {', '.join(stray)} not among the primary members")
        for label, group in (("members", members), ("also", also)):
            dupes = sorted({s for s in group if group.count(s) > 1})
            if dupes:
                problems.append(f"{tid}.{label}: duplicate {', '.join(dupes)}")
        if len(set(members)) < MIN_PRIMARY_MEMBERS:
            problems.append(f"{tid}: needs at least {MIN_PRIMARY_MEMBERS} primary members")
        overlap = sorted(set(members) & set(also))
        if overlap:
            problems.append(f"{tid}: {', '.join(overlap)} listed as both primary and also")
        for s in dict.fromkeys(members):
            if s in owner:
                problems.append(f"{s} is the primary member of both {owner[s]} and {tid} (one primary theme per stock)")
            owner[s] = tid
        themes.append(
            Theme(
                tid, name, str(body.get("description") or "").strip(),
                tuple(dict.fromkeys(members)), tuple(dict.fromkeys(also)), tuple(dict.fromkeys(keep)),
            )
        )
    if problems:
        raise ThemeError(problems)
    return ThemeMap(version=version, themes=themes)


def load_themes(path: Path = THEMES_YAML) -> ThemeMap:
    import yaml

    with path.open() as fh:
        try:
            raw = yaml.safe_load(fh)
        except yaml.YAMLError as exc:
            raise ThemeError([f"{path.name} is not valid YAML: {exc}"]) from exc
    return parse_themes(raw)


def unknown_symbols(themes: ThemeMap, universe: Iterable[Member]) -> list[str]:
    """Theme tickers that are not in the universe (they are ignored until ``themes sync`` adds them)."""
    known = {m.symbol for m in universe if m.kind == "stock"}
    return [s for s in themes.symbols() if s not in known]


def build_theme_index(daily_by_symbol: Mapping[str, pd.DataFrame], symbols: Sequence[str]) -> Optional[pd.DataFrame]:
    """Equal-weight, daily-rebalanced OHLC index of ``symbols`` (starts at 100), or None when nothing can be built.

    Each member contributes its day's open/high/low/close relative to its own previous close. A day's index candle is
    the previous index close times the average of those ratios, so every member weighs the same whatever its price,
    and a member joining (an IPO) or missing a day changes nothing retroactively. The index starts on the first day at
    least half of the members with data are trading. ``volume`` is chosen so that ``close * volume`` is the members'
    combined dollar volume.
    """
    frames = {k: {} for k in ("open", "high", "low", "close")}
    dollars = {}
    for sym in symbols:
        df = daily_by_symbol.get(sym)
        if df is None or len(df) < 2:
            continue
        prev = df["close"].shift(1).where(lambda s: s > 0)
        for k in frames:
            frames[k][sym] = df[k] / prev
        dollars[sym] = df["close"] * df["volume"]
    if not dollars:
        return None
    ratios = {k: pd.DataFrame(v).replace([math.inf, -math.inf], math.nan) for k, v in frames.items()}
    valid = ratios["open"].notna() & ratios["high"].notna() & ratios["low"].notna() & ratios["close"].notna()
    counts = valid.sum(axis=1)
    required = math.ceil(len(dollars) / 2)
    keep = counts >= required
    if not keep.any():
        return None
    first = keep.idxmax()
    keep = keep & (keep.index >= first)
    mean = {k: ratios[k].where(valid).loc[keep].mean(axis=1) for k in ratios}
    close = 100.0 * mean["close"].cumprod()
    prev_close = close.shift(1).fillna(100.0)
    dollar = pd.DataFrame(dollars).where(valid).loc[keep].sum(axis=1)
    out = pd.DataFrame(
        {
            "open": prev_close * mean["open"],
            "high": prev_close * mean["high"],
            "low": prev_close * mean["low"],
            "close": close,
            "volume": dollar / close,
        }
    )
    out.index.name = "date"
    return out


@dataclass
class SyncResult:
    added: list[Member] = field(default_factory=list)
    pruned: list[str] = field(default_factory=list)  # theme-only names no theme lists any more
    rejected: dict[str, str] = field(default_factory=dict)  # ticker -> reason (illiquid, ETF, ...)
    failed: dict[str, str] = field(default_factory=dict)  # ticker -> lookup error (try again later)


def sync_universe(
    themes: ThemeMap,
    lookup: Optional[Callable[[str], tuple[pd.DataFrame, dict]]] = None,
    save: bool = True,
    path: Path = UNIVERSE_CSV,
) -> SyncResult:
    """Add theme tickers missing from the universe (S&P 500, Nasdaq-100, ETFs) when they pass the liquidity gate.

    Added names are stored in the universe snapshot with the `THEME` tag and their price history is cached; tickers
    that fail the gate are reported and left out, so remove them from ``themes.yaml``.
    """
    from . import data

    lookup = lookup or data.lookup_symbol
    base = load_universe(path)
    result = SyncResult()
    wanted = set(themes.symbols())
    result.pruned = [m.symbol for m in base if m.indexes == THEME_INDEX_TAG and m.symbol not in wanted]
    base = [m for m in base if m.symbol not in result.pruned]
    known = {m.symbol for m in base}
    for sym in themes.symbols():
        if sym in known:
            continue
        try:
            bars, meta = lookup(sym)
        except data.SymbolNotFound:
            result.rejected[sym] = "not found on Yahoo Finance"
            continue
        except data.LookupFailed as exc:
            result.failed[sym] = str(exc)
            continue
        if meta["kind"] == "etf":
            result.rejected[sym] = "is an ETF"
            continue
        recent = bars.tail(config.ADV_LOOKBACK_DAYS)
        price = float(bars["Close"].iloc[-1])
        dollar_volume = float((recent["Close"] * recent["Volume"]).mean())
        avg_volume = float(recent["Volume"].mean())
        reasons = []
        stale = (pd.Timestamp.now().normalize() - bars.index[-1].tz_localize(None).normalize()).days
        if stale > SYNC_MAX_STALE_DAYS:
            reasons.append(f"last price is {stale} days old (delisted?)")
        if price < SYNC_MIN_PRICE:
            reasons.append(f"price ${price:.2f} < ${SYNC_MIN_PRICE:g}")
        if dollar_volume < config.MIN_DOLLAR_VOLUME:
            reasons.append(f"avg $ volume ${dollar_volume / 1e6:.0f}M < ${config.MIN_DOLLAR_VOLUME / 1e6:.0f}M")
        if avg_volume < SYNC_MIN_AVG_VOLUME:
            reasons.append(f"avg volume {avg_volume:,.0f} < {SYNC_MIN_AVG_VOLUME:,.0f}")
        if reasons:
            result.rejected[sym] = "illiquid: " + ", ".join(reasons)
            continue
        if save:
            data.save_bars(sym, bars)
        result.added.append(
            Member(sym, meta["name"], meta["sector"], "stock", THEME_INDEX_TAG, industry=meta.get("industry", ""))
        )
    if save and (result.added or result.pruned):
        write_universe(base + result.added, path)
    return result


def main(argv: Sequence[str]) -> int:
    cmd = argv[0] if argv else "check"
    themes = load_themes()
    if cmd == "check":
        missing = unknown_symbols(themes, load_universe())
        print(f"{len(themes.themes)} themes, {len(themes.symbols())} tickers; version {themes.version}")
        if missing:
            print("not in the universe yet (run `npm run themes:sync`): " + " ".join(missing))
        return 1 if missing else 0
    if cmd == "sync":
        result = sync_universe(themes, save="--dry-run" not in argv)
        for m in result.added:
            print(f"added    {m.symbol:<6} {m.name} ({m.industry or m.sector})")
        for sym in result.pruned:
            print(f"pruned   {sym:<6} no theme lists it any more")
        for sym, why in result.rejected.items():
            print(f"rejected {sym:<6} {why}")
        for sym, why in result.failed.items():
            print(f"failed   {sym:<6} {why}")
        print(f"{len(result.added)} added, {len(result.pruned)} pruned, {len(result.rejected)} rejected, {len(result.failed)} failed")
        return 1 if result.failed else 0
    print("usage: python -m strat.themes [check|sync [--dry-run]]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
