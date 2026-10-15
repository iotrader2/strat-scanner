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

Every name with a weekly setup gets an **actionability score**. For stocks it is the sum of six components (raw
points, max **123**), rescaled to 0–100:

```
stocks: score = raw × 100 / 123        (capped at 100, rounded to 0.1)
ETFs:   score = raw × 100 / 108        (no Sector strength component, see below)
```

| Component | Max | How it is computed |
| --- | --- | --- |
| Monthly 2U | 20 | +20 if the current (still-forming) monthly candle is a 2U, otherwise 0. |
| Continuity | 38 | Price above the period open: Monthly +12, Weekly +12, Daily +6, plus +8 when all three are green. |
| Weekly setup | 25 | Points of the strongest weekly setup + 25% of every other weekly setup, capped at 25. Setup points: 2-1 → 2-1-2 or 3-1 → 3-1-2 pending 23, inside week 20, hammer 18, 2-1-2 / 3-1-2 triggered 12, 1-2-2 RevStrat 10, 2D-2U 9, hammer triggered 8. |
| Distance to trigger | 15 | `15 × (1 − d / 5)`, where `d` is how far (in %) price is below the weekly trigger: 15 at the trigger, 0 at 5% or more below. A setup that has already triggered gets a flat 7.5. |
| Liquidity | 10 | `10 × log10(ADV / $50M) / log10(100)`: 0 at a $50M average daily dollar volume (20 days), 10 at $5B or more. |
| Sector strength | 15 | `15 × ETF score / top ETF score`, using the stock's sector ETF (see the mapping below) and its score on the Sectors page. The top-ranked sector/industry ETF gives the full 15; an ETF at half the leader's score gives 7.5. The tooltip shows the ETF, its score and its rank, e.g. `Sector strength · XBI 12 (#23 of 24)`. 0 when the ETF has no data. |

**Sector strength details**

- The ranking is the 24 sector and industry ETFs on the Sectors page (11 SPDR sectors + 13 industry ETFs), sorted by
  their own score, strongest first; ties are broken by symbol. Benchmarks (SPY, QQQ, IWM, DIA) are not ranked.
- ETFs are scored first (without this component, so their scale stays at 108), then every stock is scored against
  that ranking in the same scan. Because the ETF scores are the ranking, ETFs never get Sector strength themselves.
- Each stock maps to its GICS sector's SPDR ETF, except where an industry ETF is a clearly better benchmark:

  | Industry (GICS sub-industry / ICB subsector / Yahoo industry) | ETF |
  | --- | --- |
  | Semiconductors; Semiconductor Materials & Equipment | SMH |
  | Application Software; Systems Software; Software (ICB); Software - Application / Infrastructure (Yahoo) | IGV |
  | Biotechnology | XBI |
  | Regional Banks | KRE |
  | Diversified Banks | KBE |
  | Oil & Gas Exploration & Production (Yahoo: Oil & Gas E&P) | XOP |
  | Homebuilding (Yahoo: Residential Construction) | ITB |
  | Aerospace & Defense (ICB: Aerospace, Defense) | ITA |
  | Gold | GDX |
  | Steel; Copper; Aluminum; Diversified / Other Industrial Metals & Mining | XME |
  | Rail Transportation; Cargo Ground Transportation; Air Freight & Logistics; Passenger Airlines (Yahoo: Railroads, Integrated Freight & Logistics, Trucking, Airlines) | IYT |
  | Apparel, Automotive, Home Improvement, Computer & Electronics, Homefurnishing and Other Specialty Retail (Yahoo: Specialty Retail, Apparel Retail, Auto & Truck Dealerships) | XRT |
  | everything else, e.g. Pharmaceuticals, Health Care Equipment, Broadline Retail (AMZN), Building Products | SPDR sector ETF (XLK, XLV, XLY, …) |

  For example MRNA (Biotechnology) uses XBI rather than XLV, NVDA uses SMH, MSFT uses IGV and AAPL (Technology
  Hardware) stays on XLK. The table lives in `INDUSTRY_ETF` in `backend/strat/universe.py`.
- Industries come from the `industry` column of `data/universe.csv` (GICS sub-industry from the S&P 500 list, ICB
  subsector for Nasdaq-100-only names). `npm run refresh:universe` rebuilds it; `python -m strat.universe --industries`
  (in `backend/`) only refills the column. Symbols added from the Watchlist or Positions use the Yahoo Finance industry,
  saved when they are added. Older additions are looked up on the next data refresh. A stock whose sector has no
  ETF (sector `Other`) scores 0 for this component.

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
- Sector strength: +6.1. TDY (Electronic Equipment & Instruments) maps to XLK, which scores 30.9 (#17 of 24) against
  the leader XLV at 75.7, so `15 × 30.9 / 75.7`.
- Raw total: 106.6 out of 123, so the score is `106.6 × 100 / 123 = 86.7`.

**Second example (MRNA, Oct 15 2026, no weekly setup):** Monthly 2U +20, continuity +38, weekly setup 0, distance 0,
liquidity +9.3, Sector strength +2.5 (XBI scores 12.4, #23 of 24: `15 × 12.4 / 75.7`). Raw 69.7 / 123 gives a score of 56.7.

In the app, hover (or keyboard-focus) any score pill in the Stock Scanner, Watchlist or Positions table or on a
Sectors card to see this breakdown.
The detail page has a **Score breakdown** panel with the same numbers plus a one-line explanation of each component.

## UI

The top tabs follow the recommended workflow, left to right: **Sectors** (find the strongest groups), **Stock
Scanner** (drill into weekly setups, optionally filtered to a sector), **Watchlist** (track the names you picked) and
**Positions** (track what you bought against your entry).

- **Sectors** (`/sectors`): SPDR sector ETFs (XLK, XLF, XLE, XLV, XLI, XLY, XLP, XLU, XLB, XLRE, XLC), industry ETFs
  (SMH, IGV, XBI, KRE, KBE, XOP, XHB, ITB, XRT, ITA, IYT, GDX, XME) and benchmarks.
  - Each card has a candlestick chart with **I** inside-bar markers, its weekly setup and trigger, M/W/D badges and a score.
  - Cards and the leaderboard are sorted strongest first on every timeframe.
  - “Scan sector →” opens the Stock Scanner filtered to that sector.
- **Stock Scanner** (`/`): ranked, sortable and filterable table of weekly setups.
  - Filters: search, sector, continuity (including Monthly 2U), weekly setup type and stocks/ETFs, using
    a custom dropdown (arrow keys, Home/End, type-to-jump, Enter/Space to pick, Esc or an outside click to close). The
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
  - Every row has a **Move to Positions →** button for when you buy. It opens a small form: entry price (prefilled
    with the last price), shares (optional) and entry date (today by default, no future dates). Saving removes the name
    from the Watchlist and opens it in Positions.
- **Positions** (`/positions`): your open positions, with a count badge on the tab.
  - Same columns, badges, earnings icon and score tooltip as the Watchlist, plus **Entry** (price with the entry date
    under it), **Last** price, **% G/L** (green for a gain, red for a loss), **$ P/L** (only when shares were entered)
    and **Days held** (calendar days since the entry date). The header cards total the open $ P/L.
  - The row **⋯** menu (same dropdown styling and keyboard support) has **Edit entry…**, **Move back to Watchlist**
    and **Close position…**; closing asks for confirmation and deletes the entry.
  - **Add position** takes any ticker directly (validated and cached like Add symbol), with an optional entry price
    (blank means the last price), shares and entry date.
  - Stored in the `positions` table of the local SQLite cache. Off-universe names keep refreshing while they are
    watched or held. There are no stops.
- **Earnings caution**: a ⚠ icon next to the symbol (Stock Scanner, Watchlist, Positions and detail header) marks a stock with
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
  strat/data.py       SQLite cache (bars, watchlist, positions, added symbols, earnings), yfinance download, resampling
  strat/members.py    effective universe = universe + watched/held off-universe symbols
  strat/earnings.py   upcoming earnings dates and BMO/AMC timing from yfinance
  strat/scanner.py    per-symbol scan + chart payloads
  strat/universe.py   S&P 500 / Nasdaq-100 / ETF universe (snapshot in data/universe.csv), industry -> sector ETF map
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
| `GET /api/positions` | Open positions: `symbols` and `positions` (`symbol`, `entry_price`, `shares`, `entry_date`, scan `row` or `null` before data is cached) |
| `POST /api/positions` | Open a position in any ticker, body `{"symbol": "NVDA", "entry_price": 196.4, "shares": 40, "entry_date": "2026-09-22"}`. `entry_price` defaults to the last price, `entry_date` to today (US/Eastern) and `shares` is optional. Removes the name from the watchlist. 404 for unknown tickers, 409 if already held, 422 for a future date or non-positive numbers |
| `PUT /api/positions/{symbol}` | Edit `entry_price`, `shares` and `entry_date` |
| `DELETE /api/positions/{symbol}` | Close (remove) a position |
| `POST /api/positions/{symbol}/watchlist` | Move a position back to the watchlist |
| `GET /api/status`, `POST /api/refresh` | Cache status and data refresh |

Not investment advice. Yahoo Finance data is unofficial and can be delayed or incomplete.
