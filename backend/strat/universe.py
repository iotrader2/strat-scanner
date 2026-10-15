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
from dataclasses import dataclass, replace
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

# Industry -> industry ETF for the Sector strength score, used only where the industry ETF is a clearly better
# benchmark than the broad SPDR sector ETF. Keys cover GICS sub-industries (S&P 500), ICB subsectors
# (Nasdaq-100-only names) and Yahoo Finance industries (symbols added from the Watchlist/Positions).
# Anything not listed (e.g. Pharmaceuticals, Broadline Retail, Building Products) uses its SPDR sector ETF.
INDUSTRY_ETF = {
    # Semiconductors -> SMH
    "Semiconductors": "SMH",
    "Semiconductor Materials & Equipment": "SMH",
    "Semiconductor Equipment & Materials": "SMH",
    # Software -> IGV
    "Application Software": "IGV",
    "Systems Software": "IGV",
    "Software": "IGV",
    "Software - Application": "IGV",
    "Software - Infrastructure": "IGV",
    # Biotech -> XBI
    "Biotechnology": "XBI",
    # Banks -> KRE (regional) / KBE (diversified)
    "Regional Banks": "KRE",
    "Banks - Regional": "KRE",
    "Diversified Banks": "KBE",
    "Banks - Diversified": "KBE",
    # Oil & gas E&P -> XOP
    "Oil & Gas Exploration & Production": "XOP",
    "Oil & Gas E&P": "XOP",
    # Homebuilders -> ITB
    "Homebuilding": "ITB",
    "Residential Construction": "ITB",
    # Aerospace & defense -> ITA
    "Aerospace & Defense": "ITA",
    "Aerospace": "ITA",
    "Defense": "ITA",
    # Gold miners -> GDX
    "Gold": "GDX",
    # Metals & mining -> XME
    "Steel": "XME",
    "Copper": "XME",
    "Aluminum": "XME",
    "Diversified Metals & Mining": "XME",
    "Other Industrial Metals & Mining": "XME",
    # Transports -> IYT
    "Rail Transportation": "IYT",
    "Cargo Ground Transportation": "IYT",
    "Air Freight & Logistics": "IYT",
    "Passenger Airlines": "IYT",
    "Railroads": "IYT",
    "Integrated Freight & Logistics": "IYT",
    "Trucking": "IYT",
    "Airlines": "IYT",
    # Specialty retail -> XRT (broadline retailers such as AMZN stay on XLY)
    "Apparel Retail": "XRT",
    "Automotive Retail": "XRT",
    "Home Improvement Retail": "XRT",
    "Other Specialty Retail": "XRT",
    "Computer & Electronics Retail": "XRT",
    "Homefurnishing Retail": "XRT",
    "Specialty Retail": "XRT",
    "Auto & Truck Dealerships": "XRT",
}


def normalize_industry(industry: str) -> str:
    """Yahoo writes "Software—Application" (em dash) in some responses and "Software - Application" in others."""
    return " - ".join(part.strip() for part in industry.replace("—", " - ").split(" - ")).strip()


def strength_etf(sector: str, industry: str = "") -> str:
    """ETF whose Sectors-page score drives a stock's Sector strength points ("" when there is none)."""
    return INDUSTRY_ETF.get(normalize_industry(industry)) or SECTOR_ETF.get(sector, "")

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
    industry: str = ""  # GICS sub-industry, ICB subsector or Yahoo industry

    @property
    def sector_etf(self) -> str:
        return SECTOR_ETF.get(self.sector, "")

    @property
    def strength_etf(self) -> str:
        return "" if self.kind == "etf" else strength_etf(self.sector, self.industry)


def to_yahoo(symbol: str) -> str:
    return symbol.strip().upper().replace(".", "-")


def load_universe(path: Path = UNIVERSE_CSV) -> list[Member]:
    with path.open(newline="") as fh:
        return [
            Member(r["symbol"], r["name"], r["sector"], r["kind"], r["indexes"], industry=r.get("industry") or "")
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


def _fetch_members() -> dict[str, Member]:
    import pandas as pd

    members: dict[str, Member] = {}

    sp = pd.read_html(io.StringIO(_wiki_html("List of S&P 500 companies")))[0]
    for _, row in sp.iterrows():
        sym = to_yahoo(str(row["Symbol"]))
        members[sym] = Member(
            sym, str(row["Security"]), str(row["GICS Sector"]), "stock", "SP500", industry=str(row["GICS Sub-Industry"])
        )

    ndx_tables = pd.read_html(io.StringIO(_wiki_html("List of NASDAQ-100 companies")))
    ndx = next(t for t in ndx_tables if "Ticker" in t.columns)
    industry_col = next(c for c in ndx.columns if str(c).startswith("ICB Industry"))
    subsector_col = next((c for c in ndx.columns if str(c).startswith("ICB Subsector")), None)
    for _, row in ndx.iterrows():
        sym = to_yahoo(str(row["Ticker"]))
        if sym in members:
            members[sym] = replace(members[sym], indexes="SP500;NDX")
        else:
            sector = ICB_TO_GICS.get(str(row[industry_col]), str(row[industry_col]))
            subsector = str(row[subsector_col]) if subsector_col is not None else ""
            members[sym] = Member(sym, str(row["Company"]), sector, "stock", "NDX", industry=subsector)

    for sym, name, sector, group in ETFS:
        members[sym] = Member(sym, name, sector, "etf", group)
    return members


def write_universe(members: list[Member], path: Path = UNIVERSE_CSV) -> list[Member]:
    ordered = sorted(members, key=lambda m: (m.kind != "etf", m.symbol))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["symbol", "name", "sector", "kind", "indexes", "industry"])
        for m in ordered:
            writer.writerow([m.symbol, m.name, m.sector, m.kind, m.indexes, m.industry])
    return ordered


def build_universe(path: Path = UNIVERSE_CSV) -> list[Member]:
    return write_universe(list(_fetch_members().values()), path)


def add_industries(path: Path = UNIVERSE_CSV) -> list[Member]:
    """Fill in the industry column of the existing snapshot without changing its membership."""
    fetched = _fetch_members()
    current = load_universe(path)
    return write_universe(
        [replace(m, industry=fetched[m.symbol].industry) if m.symbol in fetched else m for m in current], path
    )


if __name__ == "__main__":
    import sys

    if "--industries" in sys.argv:
        built = add_industries()
        print(f"Updated industries for {sum(1 for m in built if m.industry)} of {len(built)} symbols in {UNIVERSE_CSV}")
    else:
        built = build_universe()
        print(f"Wrote {len(built)} symbols to {UNIVERSE_CSV}")
