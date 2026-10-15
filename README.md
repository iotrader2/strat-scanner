# strat-scanner

A **local-only** stock scanner for Rob Smith's **The Strat**, long bias only. It scans liquid US names
(S&P 500 + Nasdaq-100 + sector/industry ETFs) for **weekly** setups (inside weeks, weekly hammers and
bullish weekly Strat combos) and ranks them by an *actionability* score. Monthly, Weekly and Daily candles are all
classified and shown as context (Strat number and continuity).

It runs on your machine only (API and UI bind to `127.0.0.1`). There is no deploy or hosting config.
Data comes from Yahoo Finance via [yfinance](https://github.com/ranaroussi/yfinance) (no API key needed)
and is cached in a local SQLite file.

## Quick start

Requirements: **Python 3.10+** and **Node.js 20.19+ or 22.12+** (npm), as required by Vite 8. If the `node` on
your PATH is older, `npm run dev` picks the newest compatible version installed with nvm. On macOS, a Homebrew
`python3.1x` is used when the system `python3` is too old.

```bash
npm run dev        # or: make dev
```

Then open **http://127.0.0.1:5173**. The first visit opens on the Sectors tab; after that the app reopens
whichever tab you used last.

`npm run dev` does everything on first run: it creates `backend/.venv`, installs the Python requirements and the
web dependencies, starts the FastAPI backend on `127.0.0.1:8000` and the Vite UI on `127.0.0.1:5173`.
If the cache is empty, the first download (~550 symbols, 3 years of daily bars) starts automatically and
takes about a minute; the top bar shows progress. Press `Ctrl+C` to stop both servers.

### Other commands

| Command | What it does |
| --- | --- |
| `npm run setup` | Install/update Python + web dependencies only |
| `npm run refresh` | Download the latest bars into the cache from the CLI (the **↻ Refresh data** button also updates earnings dates) |
| `npm run refresh:universe` | Rebuild the S&P 500 / Nasdaq-100 list from Wikipedia, then refresh |
| `npm test` | Run the backend (pytest) and frontend (Vitest) unit tests |
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
The best names have Monthly **and** Weekly green; the Stock Scanner defaults to that filter.

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

See [How scoring works](#how-scoring-works) for the actionability score.

The chosen weekly setup supplies the **trigger** and the start of the **reason** text, followed by Monthly 2U and
continuity context, e.g. `Weekly Inside bar — trigger 106.00 (+1.9% away) · Monthly 2U · Full continuity M+W+D green`.

## How scoring works

Every name with a weekly setup gets an **actionability score**. It is the sum of five components (raw points,
max **108**), rescaled to 0–100:

```
score = raw × 100 / 108        (capped at 100, rounded to 0.1)
```

| Component | Max | How it is computed |
| --- | --- | --- |
| Monthly 2U | 20 | +20 if the current (still-forming) monthly candle is a 2U, otherwise 0. |
| Continuity | 38 | Price above the period open: Monthly +12, Weekly +12, Daily +6, plus +8 when all three are green. |
| Weekly setup | 25 | Points of the strongest weekly setup + 25% of every other weekly setup, capped at 25. Setup points: 2-1 → 2-1-2 or 3-1 → 3-1-2 pending 23, inside week 20, hammer 18, 2-1-2 / 3-1-2 triggered 12, 1-2-2 RevStrat 10, 2D-2U 9, hammer triggered 8. |
| Distance to trigger | 15 | `15 × (1 − d / 5)`, where `d` is how far (in %) price is below the weekly trigger: 15 at the trigger, 0 at 5% or more below. A setup that has already triggered gets a flat 7.5. |
| Liquidity | 10 | `10 × log10(ADV / $50M) / log10(100)`: 0 at a $50M average daily dollar volume (20 days), 10 at $5B or more. |

If the 20-day average daily range is under 0.5% of price (usually a stock pinned by a pending acquisition), the raw
total is halved; this shows as a negative "Pinned penalty" line.

When a name has several weekly setups, the one used for the trigger is the setup with the best combination of
setup points and closeness, with a small preference for setups that have not triggered yet.

**Worked example (TDY, Oct 15 2026):**

- Monthly 2U: +20.
- Continuity: +38 (all three timeframes green, including the +8 bonus).
- Weekly setup: +25. A 3-1 → 3-1-2 pending setup (23) plus 25% of a weekly hammer (4.5) is 27.5, capped at 25.
- Distance to trigger: +14.9. Price 619.00 is 0.04% below the 619.22 trigger, so `15 × (1 − 0.04/5)`.
- Liquidity: +2.6. The average dollar volume of $164M/day gives `10 × log10(164/50) / 2`.
- Raw total: 100.5 out of 108, so the score is `100.5 × 100 / 108 = 93`.

In the app, hover (or keyboard-focus) any score pill in the Stock Scanner table or on a Sectors card to see this breakdown.
The detail page has a **Score breakdown** panel with the same numbers plus a one-line explanation of each component.

## UI

The top tabs follow the recommended workflow, left to right: **Sectors** (find the strongest groups), **Stock
Scanner** (drill into weekly setups, optionally filtered to a sector) and **Watchlist** (track the names you picked).

- **Sectors** (`/sectors`): SPDR sector ETFs (XLK, XLF, XLE, XLV, XLI, XLY, XLP, XLU, XLB, XLRE, XLC), industry ETFs
  (SMH, IGV, XBI, KRE, KBE, XOP, XHB, ITB, XRT, ITA, IYT, GDX, XME) and benchmarks.
  - Each card has a candlestick chart with **I** inside-bar markers, its weekly setup and trigger, M/W/D badges and a score.
  - Cards and the leaderboard are sorted strongest first on every timeframe.
  - “Scan sector →” opens the Stock Scanner filtered to that sector.
- **Stock Scanner** (`/`): ranked, sortable and filterable table of weekly setups.
  - Filters: search, sector, continuity (including Monthly 2U), weekly setup type and stocks/ETFs. The
    "To trigger" column is sortable by closeness to the weekly trigger.
  - Three log-scale sliders, each with a live readout such as `≥ $10` or `≥ 2.5M`:
    - **min price**: $1–$1,000, default $10 (`STRAT_MIN_PRICE`).
    - **min average dollar volume**: $10M–$5B.
    - **min average share volume**: 20-day average, 100K–50M shares.
  - All filters run in the browser, so the table updates instantly without a re-scan. Every filter value is saved in
    `localStorage`.
  - Columns include **Avg vol** (shares) and **Avg $vol**.
  - M/W/D badges show the Strat number (text colour, yellow outline for `1`, purple for `3`) on a green/red fill for
    continuity; `H` marks a hammer.
- **Detail** (`/stock/SYMBOL`): interactive candlestick chart ([TradingView lightweight-charts](https://github.com/tradingview/lightweight-charts))
  with a Monthly/Weekly/Daily toggle and the dashed weekly trigger line.
  - The chart has only two markers: a blue **H** arrow under hammers and a yellow **I** arrow under inside bars (Strat 1).
  - The other Strat numbers are shown in the M/W/D badges, not on the candles.
- **Watchlist** (`/watchlist`): a **+** button on every Stock Scanner row, on the detail page header and on each Sectors card
  adds the symbol.
  - Once a name is watched the button shows a check, which turns into **−** on hover, and clicking it removes the name.
  - The Watchlist tab shows a count badge.
  - It lists the watched names with the Stock Scanner's columns, badges, trigger and score tooltip. The first-column
    check/**−** toggle removes a name.
  - Names stay on the list after their weekly setup goes away; they are then marked “no active setup”.
  - The list is stored in the `watchlist` table of the local SQLite cache, so it survives restarts and data refreshes.
  - **Add symbol** (on the Watchlist tab) takes any Yahoo Finance ticker, not just universe names: type it (it is
    upper-cased) and press Enter.
    - Tickers outside the S&P 500 / Nasdaq-100 / ETF universe (e.g. `SOFI`) are first validated by downloading
      their history with yfinance. Only a ticker Yahoo reports as missing is rejected (404); a network failure
      returns 502 instead.
    - Their bars, name and sector are cached, and while they are watched they get the same M/W/D Strat data, score
      and trigger, are included in every data refresh, and have a working detail page and chart.
    - They show an **Added** chip.
    - They appear in the Stock Scanner only when they have a weekly setup and pass its filters like any other name.
- **Earnings caution**: a ⚠ icon next to the symbol (Stock Scanner, Watchlist and detail header) marks a stock with
  earnings in the next 10 calendar days, counting today.
  - Hover or focus it to see the date and timing: **BMO** (before open), **AMC** (after close) or **time TBD**.
    When Yahoo only gives an estimated date range, the range is shown.
  - Dates come from yfinance (`Ticker.calendar` for the date; `get_earnings_dates` for the scheduled time).
  - A time before 09:30 ET is BMO, 16:00 ET or later is AMC, and anything else (including date-only entries) is
    time TBD.
  - Results are cached in the `earnings` table and re-fetched on every data refresh. On startup, entries older
    than 12 hours are refreshed in the background.
  - When the source has no date, no icon is shown; nothing is guessed. ETFs never show it.
- **Sticky selections**: the last tab (including the Stock Scanner's sector filter) and the M/W/D timeframe on the
  detail and Sectors views are saved in `localStorage`. They survive navigation and full reloads, and opening the bare
  app URL reopens the last tab; a first-time visitor with nothing saved lands on **Sectors**. Deep links such as
  `/stock/TDY` or `/?sector=Energy` always win.

## Layout

```
backend/
  strat/candles.py    Strat classification, continuity, hammer, long setups (pure, unit tested)
  strat/scoring.py    actionability score
  strat/data.py       SQLite cache (bars, watchlist, added symbols, earnings), yfinance download, resampling
  strat/members.py    effective universe = universe + watched off-universe symbols
  strat/earnings.py   upcoming earnings dates and BMO/AMC timing from yfinance
  strat/scanner.py    per-symbol scan + chart payloads
  strat/universe.py   S&P 500 / Nasdaq-100 / ETF universe (snapshot in data/universe.csv)
  strat/api.py        FastAPI app (localhost only)
  tests/              pytest suite
web/                  React + Vite + lightweight-charts UI
scripts/              setup + dev launcher used by `npm run dev`
```

### Local API

The UI talks to the backend on `127.0.0.1:8000` (proxied through Vite as `/api`):

| Endpoint | Purpose |
| --- | --- |
| `GET /api/scan` | Ranked weekly setups |
| `GET /api/symbol/{symbol}` | Scan row plus M/W/D chart candles for one symbol |
| `GET /api/sectors?tf=W` | Sector/industry ETF cards for a timeframe |
| `GET /api/watchlist` | Watched symbols (`symbols`), their scan rows (`rows`) and any without cached data yet (`missing`) |
| `POST /api/watchlist` | Add any ticker, body `{"symbol": "SOFI"}`. Returns 404 only if Yahoo Finance has no such symbol and 502 if the lookup fails |
| `DELETE /api/watchlist/{symbol}` | Remove a symbol |
| `GET /api/status`, `POST /api/refresh` | Cache status and data refresh |

Not investment advice. Yahoo Finance data is unofficial and can be delayed or incomplete.
