# strat-scanner

A **local-only** stock scanner for Rob Smith's **The Strat**, long bias only. It scans liquid US names
(S&P 500 + Nasdaq-100 + sector/industry ETFs) for **weekly** setups (inside weeks, weekly hammers and
bullish weekly Strat combos) and ranks them by an *actionability* score. Monthly, Weekly and Daily candles are all
classified and shown as context (Strat number and continuity).

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

**Long setups** are detected on the **weekly** timeframe only. Names without a weekly setup do not appear in the
ranked list, even if their monthly or daily candle shows a pattern.

| Setup | Pattern | Trigger |
| --- | --- | --- |
| Inside week (ready to trigger) | current week is `1` | above the inside-week high |
| 2-1 → 2-1-2, 3-1 → 3-1-2 (pending) | `2`/`3` week then current week `1` | inside-week high |
| Weekly hammer | current week is a hammer | hammer high |
| 2-1-2 bullish (2D-1-2U, 2U-1-2U) | triggered | inside-week high |
| 3-1-2 bullish | triggered | inside-week high |
| 1-2-2 RevStrat | `1`, `2D`, `2U` weeks | 2D-week high |
| 2D-2U reversal | `2D` week then `2U` week | 2D-week high |
| Hammer triggered | prior week a hammer, current week breaks its high | hammer high |

Stops are intentionally not shown: they are managed intraday (e.g. on the 5-minute chart), which is out of
scope for this scanner.

**Actionability score (0–100)**:

- Monthly 2U: **+20** when the current monthly candle is a 2U (strongest single factor).
- Continuity: Monthly green +12, Weekly green +12, Daily green +6, plus a +8 bonus for full M+W+D.
- Weekly setup: pending 2-1 / 3-1 setups +23, inside week +20, hammer +18; triggered combos score less
  (2-1-2 / 3-1-2 +12, 1-2-2 +10, 2D-2U +9, hammer triggered +8). Extra weekly setups add a quarter of their points (capped at 25).
- Proximity: up to +15 when price is within 5% below the weekly trigger (half credit once triggered).
- Liquidity: up to +10, log-scaled from $50M to $5B average daily dollar volume.
- Names with an average daily range under 0.5% (typically pinned by a pending acquisition) have their score halved.
- The raw points (max 108) are rescaled to 0–100 so the top names don't tie at a cap.

The chosen weekly setup supplies the **trigger** and the start of the **reason** text, followed by Monthly 2U and
continuity context, e.g. `Weekly Inside bar — trigger 106.00 (+1.9% away) · Monthly 2U · Full continuity M+W+D green`.

## UI

- **Scanner**: ranked, sortable and filterable table of weekly setups (search, sector, continuity incl. Monthly 2U,
  weekly setup type, stocks/ETFs, min price, min dollar volume, max distance to trigger). M/W/D badges show the Strat number (text colour,
  yellow outline for `1`, purple for `3`) on a green/red fill for continuity; `H` marks a hammer.
- **Detail** (`/stock/SYMBOL`): interactive candlestick chart ([TradingView lightweight-charts](https://github.com/tradingview/lightweight-charts))
  with a Monthly/Weekly/Daily toggle, Strat numbers above recent bars, hammer arrows, and the dashed weekly trigger line.
- **Sectors**: SPDR sector ETFs (XLK, XLF, XLE, XLV, XLI, XLY, XLP, XLU, XLB, XLRE, XLC), industry ETFs
  (SMH, IGV, XBI, KRE, KBE, XOP, XHB, ITB, XRT, ITA, IYT, GDX, XME) and benchmarks, each with a labelled chart,
  its weekly setup and trigger, M/W/D badges and a strongest→weakest leaderboard. “Scan sector →” filters the scanner to that sector.

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
