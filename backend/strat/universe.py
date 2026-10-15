"""Scan universe: S&P 500 + Nasdaq-100 stocks plus sector / benchmark ETFs.

The constituent list is snapshotted to ``data/universe.csv`` so scans work
without re-scraping; ``python -m strat.universe`` rebuilds it from Wikipedia.
"""

from __future__ import annotations

import csv
import io
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .config import DATA_DIR

UNIVERSE_CSV = DATA_DIR / "universe.csv"

SECTOR_ETF = {
    "Information Technology": "XLK",
    "Financials": "XLF",
    "Energy": "XLE",
    "Health Care": "XLV",
    "Industrials": "XLI",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Utilities": "XLU",
    "Materials": "XLB",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
}

# ICB industry (used by the Nasdaq-100 list) -> closest GICS sector.
ICB_TO_GICS = {
    "Technology": "Information Technology",
    "Telecommunications": "Communication Services",
    "Health Care": "Health Care",
    "Financials": "Financials",
    "Real Estate": "Real Estate",
    "Consumer Discretionary": "Consumer Discretionary",
    "Consumer Staples": "Consumer Staples",
    "Industrials": "Industrials",
    "Basic Materials": "Materials",
    "Energy": "Energy",
    "Utilities": "Utilities",
}

# Yahoo Finance sector names (used for symbols added from the watchlist) -> GICS sector.
YAHOO_TO_GICS = {
    "Technology": "Information Technology",
    "Healthcare": "Health Care",
    "Financial Services": "Financials",
    "Consumer Cyclical": "Consumer Discretionary",
    "Consumer Defensive": "Consumer Staples",
    "Basic Materials": "Materials",
    "Communication Services": "Communication Services",
    "Energy": "Energy",
    "Industrials": "Industrials",
    "Utilities": "Utilities",
    "Real Estate": "Real Estate",
}
OTHER_SECTOR = "Other"

# (symbol, name, sector, group). group: "spdr" | "industry" | "benchmark"
ETFS: list[tuple[str, str, str, str]] = [
    ("XLK", "Technology Select Sector SPDR", "Information Technology", "spdr"),
    ("XLF", "Financial Select Sector SPDR", "Financials", "spdr"),
    ("XLE", "Energy Select Sector SPDR", "Energy", "spdr"),
    ("XLV", "Health Care Select Sector SPDR", "Health Care", "spdr"),
    ("XLI", "Industrial Select Sector SPDR", "Industrials", "spdr"),
    ("XLY", "Consumer Discretionary Select Sector SPDR", "Consumer Discretionary", "spdr"),
    ("XLP", "Consumer Staples Select Sector SPDR", "Consumer Staples", "spdr"),
    ("XLU", "Utilities Select Sector SPDR", "Utilities", "spdr"),
    ("XLB", "Materials Select Sector SPDR", "Materials", "spdr"),
    ("XLRE", "Real Estate Select Sector SPDR", "Real Estate", "spdr"),
    ("XLC", "Communication Services Select Sector SPDR", "Communication Services", "spdr"),
    ("SMH", "VanEck Semiconductor", "Information Technology", "industry"),
    ("IGV", "iShares Expanded Tech-Software", "Information Technology", "industry"),
    ("XBI", "SPDR S&P Biotech", "Health Care", "industry"),
    ("KRE", "SPDR S&P Regional Banking", "Financials", "industry"),
    ("KBE", "SPDR S&P Bank", "Financials", "industry"),
    ("XOP", "SPDR S&P Oil & Gas Exploration & Production", "Energy", "industry"),
    ("XHB", "SPDR S&P Homebuilders", "Consumer Discretionary", "industry"),
    ("ITB", "iShares U.S. Home Construction", "Consumer Discretionary", "industry"),
    ("XRT", "SPDR S&P Retail", "Consumer Discretionary", "industry"),
    ("ITA", "iShares U.S. Aerospace & Defense", "Industrials", "industry"),
    ("IYT", "iShares Transportation Average", "Industrials", "industry"),
    ("GDX", "VanEck Gold Miners", "Materials", "industry"),
    ("XME", "SPDR S&P Metals & Mining", "Materials", "industry"),
    ("SPY", "SPDR S&P 500", "Benchmark", "benchmark"),
    ("QQQ", "Invesco QQQ (Nasdaq-100)", "Benchmark", "benchmark"),
    ("IWM", "iShares Russell 2000", "Benchmark", "benchmark"),
    ("DIA", "SPDR Dow Jones Industrial Average", "Benchmark", "benchmark"),
]


@dataclass(frozen=True)
class Member:
    symbol: str
    name: str
    sector: str
    kind: str  # "stock" | "etf"
    indexes: str  # e.g. "SP500;NDX" for stocks, ETF group for ETFs
    in_universe: bool = True  # False for symbols added from the watchlist

    @property
    def sector_etf(self) -> str:
        return SECTOR_ETF.get(self.sector, "")


def to_yahoo(symbol: str) -> str:
    return symbol.strip().upper().replace(".", "-")


def load_universe(path: Path = UNIVERSE_CSV) -> list[Member]:
    with path.open(newline="") as fh:
        return [
            Member(r["symbol"], r["name"], r["sector"], r["kind"], r["indexes"])
            for r in csv.DictReader(fh)
        ]


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "strat-scanner-local/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def _wiki_html(title: str) -> str:
    url = (
        "https://en.wikipedia.org/w/api.php?action=parse&format=json&prop=text&page="
        + urllib.parse.quote(title)
    )
    return json.loads(_get(url))["parse"]["text"]["*"]


def build_universe(path: Path = UNIVERSE_CSV) -> list[Member]:
    import pandas as pd

    members: dict[str, Member] = {}

    sp = pd.read_html(io.StringIO(_wiki_html("List of S&P 500 companies")))[0]
    for _, row in sp.iterrows():
        sym = to_yahoo(str(row["Symbol"]))
        members[sym] = Member(sym, str(row["Security"]), str(row["GICS Sector"]), "stock", "SP500")

    ndx_tables = pd.read_html(io.StringIO(_wiki_html("List of NASDAQ-100 companies")))
    ndx = next(t for t in ndx_tables if "Ticker" in t.columns)
    industry_col = next(c for c in ndx.columns if str(c).startswith("ICB Industry"))
    for _, row in ndx.iterrows():
        sym = to_yahoo(str(row["Ticker"]))
        if sym in members:
            m = members[sym]
            members[sym] = Member(m.symbol, m.name, m.sector, m.kind, "SP500;NDX")
        else:
            sector = ICB_TO_GICS.get(str(row[industry_col]), str(row[industry_col]))
            members[sym] = Member(sym, str(row["Company"]), sector, "stock", "NDX")

    for sym, name, sector, group in ETFS:
        members[sym] = Member(sym, name, sector, "etf", group)

    ordered = sorted(members.values(), key=lambda m: (m.kind != "etf", m.symbol))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["symbol", "name", "sector", "kind", "indexes"])
        for m in ordered:
            writer.writerow([m.symbol, m.name, m.sector, m.kind, m.indexes])
    return ordered


if __name__ == "__main__":
    built = build_universe()
    print(f"Wrote {len(built)} symbols to {UNIVERSE_CSV}")
