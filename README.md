# strat-scanner

A **local-only** stock scanner for Rob Smith's **The Strat**, long bias only. It scans liquid US names
(S&P 500 + Nasdaq-100 + sector/industry ETFs), classifies the Monthly, Weekly and Daily candles,
flags inside bars, hammers and bullish Strat combos, and ranks everything by an *actionability* score.

It runs on your machine only (API and UI bind to `127.0.0.1`). There is no deploy or hosting config.
Data comes from Yahoo Finance via [yfinance](https://github.com/ranaroussi/yfinance) (no API key needed)
and is cached in a local SQLite file.

## Quick start

Requirements: **Python 3.10+** and **Node.js 18+** (npm).

```bash
npm run dev        # or: make dev
```

Then open **http://127.0.0.1:5173**.

`npm run dev` does everything on first run: it creates `backend/.venv`, installs the Python requirements and the
web dependencies, starts the FastAPI backend on `127.0.0.1:8000` and the Vite UI on `127.0.0.1:5173`.
If the cache is empty, the first download (~550 symbols, 3 years of daily bars) starts automatically and
takes about a minute; the top bar shows progress. Press `Ctrl+C` to stop both servers.

### Other commands

| Command | What it does |
| --- | --- |
| `npm run setup` | Install/update Python + web dependencies only |
| `npm run refresh` | Download the latest bars into the cache from the CLI (same as the **↻ Refresh data** button) |
| `npm run refresh:universe` | Rebuild the S&P 500 / Nasdaq-100 list from Wikipedia, then refresh |
| `npm test` | Run the backend unit tests (candle classification, hammer, setups, scoring) |
| `npm run typecheck` | Type-check the frontend |

Each has a `make` equivalent (`make refresh`, `make test`, ...). The `refresh`/`test` npm scripts assume a
POSIX shell; on Windows run `backend\.venv\Scripts\python -m strat.refresh` / `-m pytest` from `backend/`.

### Configuration

Defaults can be changed with environment variables (the UI filters can also be changed live):

| Variable | Default | Meaning |
| --- | --- | --- |
| `STRAT_MIN_PRICE` | `10` | Minimum last price |
| `STRAT_MIN_DOLLAR_VOLUME` | `50000000` | Minimum average daily dollar volume |
| `STRAT_ADV_LOOKBACK_DAYS` | `20` | Days used for average dollar volume / range |
| `STRAT_HISTORY_PERIOD` | `3y` | History fetched for new symbols / full refresh |
| `STRAT_API_PORT` / `STRAT_WEB_PORT` | `8000` / `5173` | Local ports |
| `STRAT_CACHE_DB` | `backend/data/cache.sqlite3` | Cache location |

Example: `STRAT_MIN_PRICE=20 STRAT_MIN_DOLLAR_VOLUME=100000000 npm run dev`.

## What it computes

Weekly (Mon-Fri) and monthly candles are built from the cached daily bars. The **last candle is the
current, still-forming period**, which is how The Strat is read in real time.

**Strat number** of each candle vs. the previous one:

- `1` inside: does not take out the prior high or low
- `2U`: takes out the prior high only; `2D`: takes out the prior low only
- `3` outside: takes out both

**Continuity**: a timeframe is green when price is above that period's open (red if below).
The best names have Monthly **and** Weekly green; the scanner defaults to that filter.

**Hammer**: lower wick ≥ 2× body, small upper wick (≤ the body or ≤ 10% of the range), and a close in
the top third of the range.

**Long setups** found on M, W and D:

| Setup | Pattern | Trigger / stop |
| --- | --- | --- |
| Inside bar (incl. inside month/week/day) | current candle is `1` | above the inside-bar high / inside-bar low |
| 2-1 → 2-1-2, 3-1 → 3-1-2 (pending) | `2`/`3` then current `1` | inside-bar high / inside-bar low |
| Hammer | current candle is a hammer | hammer high / hammer low |
| 2-1-2 bullish (2D-1-2U, 2U-1-2U) | triggered | inside-bar high / inside-bar low |
| 3-1-2 bullish | triggered | inside-bar high / inside-bar low |
| 1-2-2 RevStrat | `1`, `2D`, `2U` | 2D-candle high / 2D-candle low |
| 2D-2U reversal | `2D` then `2U` | 2D-candle high / 2D-candle low |
| Hammer triggered | prior candle hammer, current breaks its high | hammer high / hammer low |

**Actionability score (0–100)**:

- Continuity: Monthly green +15, Weekly green +15, Daily green +8, plus a +10 bonus for full M+W+D.
- Setups: pending inside bars / hammers score highest, and higher timeframes weigh more
  (e.g. a monthly 2-1 setup scores more than a daily one). Triggered combos score less (capped at 28 points).
- Proximity: up to +15 when price is within 5% below the trigger of the chosen setup (half credit once triggered).
- Liquidity: up to +10, log-scaled from $50M to $5B average daily dollar volume.
- Names with an average daily range under 0.5% (typically pinned by a pending acquisition) have their score halved.

The chosen ("best") setup supplies the **trigger**, **stop** and **reason** text shown in the table.

## UI

- **Scanner**: ranked, sortable and filterable table (search, sector, continuity, setup type, stocks/ETFs,
  min price, min dollar volume, max distance to trigger). M/W/D badges show the Strat number (text colour,
  yellow outline for `1`, purple for `3`) on a green/red fill for continuity; `H` marks a hammer.
- **Detail** (`/stock/SYMBOL`): interactive candlestick chart ([TradingView lightweight-charts](https://github.com/tradingview/lightweight-charts))
  with a Monthly/Weekly/Daily toggle, Strat numbers above recent bars, hammer arrows, and dashed trigger/stop lines.
- **Sectors**: SPDR sector ETFs (XLK, XLF, XLE, XLV, XLI, XLY, XLP, XLU, XLB, XLRE, XLC), industry ETFs
  (SMH, IGV, XBI, KRE, KBE, XOP, XHB, ITB, XRT, ITA, IYT, GDX, XME) and benchmarks, each with a labelled chart,
  M/W/D badges and a strongest→weakest leaderboard. “Scan sector →” filters the scanner to that sector.

## Layout

```
backend/
  strat/candles.py    Strat classification, continuity, hammer, long setups (pure, unit tested)
  strat/scoring.py    actionability score
  strat/data.py       SQLite cache, yfinance download, weekly/monthly resampling
  strat/scanner.py    per-symbol scan + chart payloads
  strat/universe.py   S&P 500 / Nasdaq-100 / ETF universe (snapshot in data/universe.csv)
  strat/api.py        FastAPI app (localhost only)
  tests/              pytest suite
web/                  React + Vite + lightweight-charts UI
scripts/              setup + dev launcher used by `npm run dev`
```

Not investment advice. Yahoo Finance data is unofficial and can be delayed or incomplete.
