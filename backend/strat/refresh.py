"""CLI: ``python -m strat.refresh [--full] [--universe]`` downloads data into the local cache."""

from __future__ import annotations

import argparse
import sys

from . import data
from .universe import build_universe, load_universe


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh the local price cache from Yahoo Finance")
    parser.add_argument("--full", action="store_true", help="re-download full history for every symbol")
    parser.add_argument("--universe", action="store_true", help="rebuild the S&P 500 / Nasdaq-100 list first")
    args = parser.parse_args()

    members = build_universe() if args.universe else load_universe()

    def progress(done: int, total: int, message: str) -> None:
        print(f"\r[{done}/{total}] {message:<60}", end="", file=sys.stderr, flush=True)

    saved = data.refresh([m.symbol for m in members], full=args.full, progress=progress)
    print(f"\nCached bars for {len(saved)} / {len(members)} symbols in {data.config.CACHE_DB}")


if __name__ == "__main__":
    main()
