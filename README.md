# Tilt Killer (formerly Strat Scanner)

A **local-only** stock scanner for Rob Smith's **The Strat**, long bias only. It scans liquid US names
(S&P 500 + Nasdaq-100 + extra theme names + sector/industry ETFs + the QQQ, SPY and IWM index ETFs) for **weekly** setups (inside weeks, weekly hammers and
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

Then open **http://127.0.0.1:5173**. The first visit opens on the State of the Market tab; after that the app reopens
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
| `npm run themes:report` | Validate `backend/data/themes.yaml` against 6 months of return correlations and write `backend/data/themes_report.md` (see [Themes](#themes-the-sector-unit)) |
| `npm run themes:sync` | Add theme tickers that are missing from the universe when they pass the liquidity filters, and prune theme-only names no theme lists any more (`--dry-run` through `python -m strat.themes sync --dry-run`) |
| `npm run themes:check` | Validate the theme file and list tickers not yet in the universe |
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

## Themes (the "sector" unit)

A **theme** is a group of stocks that actually move together (Cybersecurity, Memory & storage, Regional banks,
Neoclouds & AI infrastructure, …). Themes replace the sector and industry ETFs as the unit the app ranks: the
Themes tab, the Stock Scanner's Theme filter and the Theme strength score component all use them. The 24 sector and
industry ETFs are still scanned as ordinary ETFs, but they no longer rank anything.

The method is a hybrid, with the curated file always winning:

1. **Curated theme map** (`backend/data/themes.yaml`, versioned with a `version` number). Each theme has a `name`, a
   `description` and its **primary members** (`members`). A stock has **one primary theme**. A theme may also list
   **secondary members** (`also`): they appear dimmed on that theme's card and match the scanner's Theme filter, but
   they are not part of the theme's index and do not affect scoring. `keep` marks primary members that the correlation
   report flags but that were reviewed and deliberately kept. Tickers are space-separated strings (YAML would read a
   bare `ON` or `NO` as a boolean). The file is validated on load (unique names and ids, at least 3 primary members,
   no stock in two primary themes, no duplicates) and every problem is listed at once.
2. **Data validation** (`npm run themes:report`, `backend/strat/themes_report.py`). Over the last 126 sessions (about six
   months) of daily returns it computes each member's average correlation to the other primary members of its theme,
   both **raw** and **beta-adjusted** (the residual after removing the stock's beta to SPY, so a theme is not "cohesive"
   just because everything rises with the market). It then
   - flags members whose in-theme beta-adjusted correlation is below 0.15, or for whom another theme fits better by 0.10
     or more;
   - lists unassigned stocks whose best theme correlation is 0.30 or more, as candidates to add;
   - runs average-linkage hierarchical clustering on the residual correlations and compares the clusters with the
     curated themes (purity, outsiders, unassigned names).

   It only reports. Nothing is reassigned automatically. The latest run is committed as `backend/data/themes_report.md`
   (82 themes, 521 members, average in-theme correlation raw 0.60 and beta-adjusted 0.56, 20 members flagged, all 20
   reviewed and kept on purpose).
3. **Off-universe names.** Theme tickers that are not in the S&P 500 / Nasdaq-100 (NBIS, CRWV, SNDK, IREN, …) are added
   to `data/universe.csv` with the `THEME` tag by `npm run themes:sync`, if they pass the liquidity gate: average dollar
   volume at least the `STRAT_MIN_DOLLAR_VOLUME` default ($50M), price at least $1, average volume at least 100K shares, a last bar
   no older than 10 days, and not an ETF. Names that fail are reported and should be removed from the YAML. `npm run refresh:universe` keeps
   `THEME` rows.

**Theme index.** Each theme is scored and charted as an equal-weight, daily-rebalanced OHLC index of its primary members
(starting at 100). Every member's open/high/low/close of a day is divided by *its own previous close*, the ratios are
averaged, and the day's index candle is the previous index close times that average, so every member weighs the same
whatever its price, and a late listing never rewrites history. The index starts once at least half the members have data.
Its M/W/D Strat badges, weekly setups, continuity and H/I markers are computed on that index exactly as for a stock.

## How scoring works

Every name with a weekly setup gets an **actionability score**. For stocks it is the sum of seven components (raw
points, max **138**), rescaled to 0–100:

```
stocks: score = raw × 100 / 138        (capped at 100, rounded to 0.1)
ETFs:   score = raw × 100 / 123        (no Theme strength component)
themes: score = raw × 100 / 113        (no Liquidity or Theme strength component)
```

| Component | Max | How it is computed |
| --- | --- | --- |
| Monthly 2U | 20 | +20 if the current (still-forming) monthly candle is a 2U, otherwise 0. |
| Continuity | 38 | Price above the period open: Monthly +12, Weekly +12, Daily +6, plus +8 when all three are green. |
| Weekly setup | 25 | Points of the strongest weekly setup + 25% of every other weekly setup, capped at 25. Setup points: 2-1 → 2-1-2 or 3-1 → 3-1-2 pending 23, inside week 20, hammer 18, 2-1-2 / 3-1-2 triggered 12, 1-2-2 RevStrat 10, 2D-2U 9, hammer triggered 8. |
| Distance to trigger | 15 | `15 × (1 − d / 5)`, where `d` is how far (in %) price is below the weekly trigger: 15 at the trigger, 0 at 5% or more below. A setup that has already triggered gets a flat 7.5. |
| Liquidity | 10 | `10 × log10(ADV / $50M) / log10(100)`: 0 at a $50M average daily dollar volume (20 days), 10 at $5B or more. Not used for themes (an index has no volume of its own). |
| Relative momentum | 15 | `15 × blended percentile` of the 1M / 3M / 6M price returns, ranked within the peer group (details below). Stocks are ranked among stocks, ETFs among ETFs and themes among themes. |
| Theme strength | 15 | Stocks only. `15 × theme score / top theme score`, using the stock's **primary** theme and its score on the Themes page. The top-ranked theme gives the full 15; a theme at half the leader's score gives 7.5. The tooltip shows the theme, its score and rank, e.g. `Theme strength · Software & SaaS 91 (#2 of 82)`. 0 for a stock in no theme (and for ETFs, which are not scored on this component). |

Rescale: the raw maximum is 138 for stocks (20 + 38 + 25 + 15 + 10 + 15 + 15), 123 for ETFs (no Theme strength) and 113 for
themes (no Liquidity, no Theme strength), so a perfect row of any kind scores 100.

**Relative momentum details**

- **Returns** are price returns (percent) to the latest close over **1, 3 and 6 calendar months**. The base is the last
  close on or before the date one/three/six months earlier (`1M` base = last close on or before today − 1 month, and so on).
  A period is missing (`—`) when the history does not reach back that far. For a theme it is the equal-weight theme index
  return.
- **Percentile rank** within the peer group (stocks, ETFs or themes), per period: `(names below + ½ × names tied) / names with a return`,
  from 0 (worst) to 1 (best).
- **Weights**: `1M 20%`, `3M 40%`, `6M 40%`. The medium-term trend carries most of the weight, and the 1M return adds
  the recent turn without letting a one-month spike dominate. If a period is missing, the remaining weights are
  renormalized.
- **Points** = `15 × (0.20·P1M + 0.40·P3M + 0.40·P6M)`. The label shows the blended percentile, e.g. `Relative momentum · P92`, and
  the hover/detail text shows each return with its percentile, the number of peers and the weights. The weights are `MOMENTUM_WEIGHTS`
  in `backend/strat/perf.py`.

**Theme strength details**

- The ranking is the themes on the Themes page sorted by their own score (strongest first, ties by name), computed in
  the same scan. Because themes are scored without this component, the ranking does not depend on itself.
- Scan order: returns and percentile distributions first, then the theme indexes and their scores, then the stock rows.
- A stock's *secondary* themes never count; only its primary theme does. A symbol added from the Watchlist or
  Positions that no theme lists scores 0 for this component.

If the 20-day average daily range is under 0.5% of price (usually a stock pinned by a pending acquisition), the raw
total is halved; this shows as a negative "Pinned penalty" line.

When a name has several weekly setups, the one used for the trigger is the setup with the best combination of
setup points and closeness, with a small preference for setups that have not triggered yet.

**Worked example (NOW, ServiceNow, Oct 15 2026):**

| Component | Points | Why |
| --- | ---: | --- |
| Monthly 2U | 20 / 20 | the current month is 2U |
| Continuity | 38 / 38 | Monthly, Weekly and Daily are green (12 + 12 + 6), plus the +8 bonus |
| Weekly setup | 18 / 25 | a weekly hammer (18) |
| Distance to trigger | 13.45 / 15 | price 148.57 is 0.52% below the 149.34 trigger: `15 × (1 − 0.52/5)` |
| Liquidity | 7.4 / 10 | $1.5B/day: `10 × log10(1512/50) / 2` |
| Relative momentum | 13.75 / 15 | 1M +4.7% (P76), 3M +41.9% (P97), 6M +57.7% (P95) among 618 stocks: `0.20×0.76 + 0.40×0.97 + 0.40×0.95 = 0.92`, so `15 × 0.92` |
| Theme strength | 14.48 / 15 | Software & SaaS scores 91.4 (#2 of 82) against the leader, Life-science tools, at 94.7: `15 × 91.4 / 94.7` |
| **Raw total** | **125.07 / 138** | score `125.07 × 100 / 138 = 90.6` |

**A theme row (Life-science tools, same day):** Monthly 2U +20, continuity +38, weekly setup +23 (3-1 → 3-1-2), distance
+11.95, Relative momentum +14.03 (1M +10.9% P97, 3M +27.1% P95, 6M +47.8% P91 among 82 themes). Raw 106.98 / 113 gives a
score of 94.7, the top of the Themes page.

In the app, hover (or keyboard-focus) any score pill in the Stock Scanner, Watchlist or Positions table or on a
Themes or State of the Market card to see this breakdown.
The detail page has a **Score breakdown** panel with the same numbers plus a one-line explanation of each component.

**Performance columns.** The Stock Scanner, Watchlist and Positions tables, every theme card and every State of the
Market card show the **1M / 3M / 6M** price returns, green for gains and red for losses. In the tables they are sortable
columns (best first on the first click, unknown returns always last); the Themes page sorts cards by Score, 1M, 3M or 6M.

## UI

The top tabs follow the recommended workflow, left to right: **State of the Market** (read the indexes first),
**Themes** (find the strongest groups of stocks that move together; this tab was called *Sectors* before themes replaced the
sector ETFs, and `/sectors` still redirects), **Stock
Scanner** (drill into weekly setups, optionally filtered to a theme), **Watchlist** (track the names you picked) and
**Positions** (track what you bought against your entry).

- **State of the Market** (`/market`, the first tab): QQQ (Nasdaq-100), SPY (S&P 500) and IWM (Russell 2000), in that
  order, as larger versions of the Themes cards.
  - Each card has the same candlestick chart with **H** / **I** markers and the weekly trigger line, M/W/D Strat badges
    (continuity fill), a score with the hover breakdown and a **+** watchlist button. A green border means Monthly +
    Weekly green continuity.
  - Each card also shows the 1M / 3M / 6M price return, green or red.
  - A Monthly / Weekly / Daily toggle (saved separately from the Themes one) switches the charts.
  - A summary line counts how many of the three have Monthly + Weekly green continuity (and full M+W+D), with each
    index's score.
  - These are the only benchmark ETFs; DIA is no longer part of the universe. They are still scanned and appear in the
    Stock Scanner (they have no theme), but they are not on the Themes page or in its ranking.
- **Themes** (`/themes`): one card per theme (82 at the moment), strongest first.
  - Each card has a candlestick chart of the theme's equal-weight index with **H** hammer and **I** inside-bar markers
    and the weekly trigger line, its weekly setup and trigger, M/W/D Strat badges, the score (with the hover
    breakdown) and the 1M / 3M / 6M index return.
  - The member list shows each member as a chip with its day change; a green outline means Monthly + Weekly
    green, a blue underline means a weekly setup, dimmed dashed chips are secondary members. Chips link to the stock page.
    Long lists show the first 12 with **+N more**.
  - **Scan theme →** opens the Stock Scanner filtered to that theme.
  - A "strongest → weakest" leaderboard (top 12, **show all** for every theme; clicking a name
    jumps to its card), a search box finds a theme by name or by a member ticker (e.g. `NVDA`), and the sort buttons order the
    cards by Score, 1M, 3M or 6M. Cards load 24 at a time.
  - The Monthly / Weekly / Daily toggle and the sort are saved separately from the other tabs.
- **Stock Scanner** (`/`): ranked, sortable and filterable table of weekly setups.
  - Filters: search, **theme** (matches a stock's primary or secondary themes; also **No theme** for ETFs and stocks no theme lists), continuity (including Monthly 2U), weekly setup type and stocks/ETFs, using
    a custom dropdown (arrow keys, Home/End, type-to-jump, Enter/Space to pick, Esc or an outside click to close).
    The Setup filter has **Any**, **Awaiting trigger** (a trigger above price that has not traded yet), **Already
    triggered** (only rows whose weekly setup carries the TRIGGERED chip: 2-1-2 / 3-1-2 bullish, 2D-2U reversal, 1-2-2
    RevStrat and Hammer triggered), **Inside week** and **Weekly hammer**. The
    "To trigger" column is sortable by closeness to the weekly trigger.
  - Three log-scale sliders, each with a live readout such as `≥ $10` or `≥ 2.5M`:
    - **min price**: $1–$1,000, default $10 (`STRAT_MIN_PRICE`).
    - **min average dollar volume**: $10M–$5B.
    - **min average share volume**: 20-day average, 100K–50M shares.
  - All filters run in the browser, so the table updates instantly without a re-scan. Every filter value is saved in
    `localStorage`.
  - Columns include **Theme** (click it to filter by that theme), **1M / 3M / 6M** price returns (sortable, green/red),
    **Avg vol** (shares) and **Avg $vol**. The Watchlist and Positions tables have the same columns.
  - M/W/D badges show the Strat number (text colour, yellow outline for `1`, purple for `3`) on a green/red fill for
    continuity; `H` marks a hammer.
- **Detail** (`/stock/SYMBOL`): interactive candlestick chart ([TradingView lightweight-charts](https://github.com/tradingview/lightweight-charts))
  with a Monthly/Weekly/Daily toggle and the dashed weekly trigger line.
  - The chart has only two markers: a blue **H** arrow under hammers and a yellow **I** arrow under inside bars (Strat 1).
  - The other Strat numbers are shown in the M/W/D badges, not on the candles.
- **Watchlist** (`/watchlist`): a **+** button on every Stock Scanner row, on the detail page header and on each State of the Market card
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
- **Sticky selections**: the last tab (including the Stock Scanner's theme filter) and the M/W/D timeframe on the
  detail, Themes and State of the Market views are saved in `localStorage`. They survive navigation and full reloads, and opening the bare
  app URL reopens the last tab; a first-time visitor with nothing saved lands on **State of the Market**. Deep links such as
  `/stock/TDY` or `/?theme=memory` always win.
- **Loading states**: anything still loading shows a blue spinner with pulsing text (e.g. “Loading weekly setups…”).
  - Tables (Stock Scanner, Watchlist, Positions) show shimmering skeleton rows, and the chart views (State of the Market,
    Themes, detail page) show skeleton cards with a shimmering chart area, until the first data arrives.
  - During a data refresh a pulsing progress banner sits under the sticky tabs, e.g. “Refreshing data… 120/546 ·
    Downloading AMD…AMZN (5d)”, then “Refreshing earnings dates… 60/519”. It has a progress bar and disappears when
    the refresh is done. The header also shows the percentage.
  - With `prefers-reduced-motion: reduce` there is no pulsing, shimmer or spinning: the spinner becomes a static blue
    ring and the skeletons and banner are drawn flat, with the same text and progress bar.

## Layout

```
backend/
  strat/candles.py    Strat classification, continuity, hammer, long setups (pure, unit tested)
  strat/scoring.py    actionability score (Relative momentum, Theme strength)
  strat/perf.py       1M/3M/6M returns, percentile ranks and the momentum blend
  strat/themes.py     theme map loader/validator, equal-weight theme index, universe sync (`python -m strat.themes`)
  strat/themes_report.py  correlation validation and clustering report (`npm run themes:report`)
  strat/data.py       SQLite cache (bars, watchlist, positions, added symbols, earnings), yfinance download, resampling
  strat/members.py    effective universe = universe + watched/held off-universe symbols
  strat/earnings.py   upcoming earnings dates and BMO/AMC timing from yfinance
  strat/scanner.py    per-symbol scan + chart payloads
  strat/universe.py   S&P 500 / Nasdaq-100 / ETF / theme-addition universe (snapshot in data/universe.csv)
  strat/api.py        FastAPI app (localhost only)
  data/themes.yaml    curated theme map (source of truth), data/themes_report.md = latest validation report
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
| `GET /api/themes?tf=W` | Theme cards for a timeframe, strongest first: index candles, scan row and member chips |
| `GET /api/config` | Liquidity defaults and the theme list (`id`, `name`, `count`) for the Scanner's filter |
| `GET /api/market?tf=W` | State of the Market cards: QQQ, SPY and IWM, in that order |
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
