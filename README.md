# TiltKiller (formerly Strat Scanner)

A **local-only** stock scanner for market **leaders**, with Rob Smith's **The Strat** as the timing overlay, long bias only.
It scans liquid US names (S&P 500 + Nasdaq-100 + sector/industry ETFs + the QQQ, SPY and IWM index ETFs) and shows
**only the true leaders**: names in the top decile of 1M/3M/6M relative strength whose trend is still intact, ranked by a
leadership-first score. **Weekly** Strat setups (inside weeks, weekly hammers and bullish weekly combos) are a modest
timing bonus, not a gate: a leader with no setup still appears, labelled *No setup / leader* with its nearest trigger.
Monthly, Weekly and Daily candles are all classified and shown as context (Strat number and continuity).

It runs on your machine only (API and UI bind to `127.0.0.1`). There is no deploy or hosting config.
Data comes from Yahoo Finance via [yfinance](https://github.com/ranaroussi/yfinance) (no API key needed)
and is cached in a local SQLite file. One background fetcher keeps that cache current and fans the
result out to every open browser over a WebSocket. The page has no refresh button.

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
If the cache is empty, the first download (646 symbols, 3 years of daily bars) starts automatically and
takes about a minute. The top bar shows a live indicator: *Updating · N symbols* while that runs, then
*15-min delayed · updated 3:45 PM ET* once a scan is saved. Press `Ctrl+C` to stop both servers.

### Other commands

| Command | What it does |
| --- | --- |
| `npm run setup` | Install/update Python + web dependencies only |
| `npm run refresh` | Download the latest bars into the cache from the CLI. The running app does this itself; there is no refresh button |
| `npm run refresh:universe` | Rebuild the S&P 500 / Nasdaq-100 list from Wikipedia, then refresh |
| `npm run themes:report` | Validate `backend/data/themes.yaml` against 6 months of return correlations and write `backend/data/themes_report.md` (see [Themes](#themes-the-sector-unit)) |
| `npm run themes:sync` | Add theme tickers that are missing from the universe when they pass the liquidity filters, and prune theme-only names no theme lists any more (`--dry-run` through `python -m strat.themes sync --dry-run`) |
| `npm run themes:check` | Validate the theme file and list tickers not yet in the universe |
| `npm test` | Run the backend (pytest) and frontend (Vitest) unit tests |
| `npm run typecheck` | Type-check the frontend |
| `npm run backtest:leaders` | Cut the price cache off at historical dates and compare the old and new scoring (see [Backtest](#backtest)); add `-- --timeline` for the weekly rank of the reference leaders |
| `npm run morning:collect` | Store each session's top 10 leaders (as of the prior close), pull the 5-minute bars Yahoo still has, and fill entry results. Safe to re-run |
| `npm run morning:backfill` | The same window (12 months of leaders) and a rebuild of check-in ranks and outcomes from the stored 5-minute bars. With `STRAT_INTRADAY_PROVIDER=alpaca` this is also how older 15-minute bars are filled |
| `npm run morning:report` | Write `backend/data/morning_report.md`: win rate, average and median returns, stop-hit rate and expectancy at each morning time |

Each has a `make` equivalent (`make refresh`, `make test`, ...). The `refresh`/`test` npm scripts assume a
POSIX shell; on Windows run `backend\.venv\Scripts\python -m strat.refresh` / `-m pytest` from `backend/`.

### Configuration

Defaults can be changed with environment variables (the UI filters can also be changed live):

| Variable | Default | Meaning |
| --- | --- | --- |
| `STRAT_MIN_PRICE` | `10` | Minimum last price |
| `STRAT_MIN_DOLLAR_VOLUME` | `50000000` | Minimum average daily dollar volume |
| `STRAT_ADV_LOOKBACK_DAYS` | `20` | Days used for average dollar volume / range |
| `STRAT_HISTORY_PERIOD` | `3y` | History fetched for new symbols / a full catch-up |
| `STRAT_INCREMENTAL_PERIOD` | `3mo` | Window used when the cache is behind by more than a few sessions |
| `STRAT_POLL_SECONDS` | `900` | Minimum gap between intraday quote polls (15 minutes) |
| `STRAT_DATA_PROVIDER` | `yahoo` | Market-data provider. `yahoo` is the only implementation |
| `STRAT_SCHEDULER` | `1` | Set to `0` to disable the background fetcher (the test suite does this) |
| `STRAT_API_PORT` / `STRAT_WEB_PORT` | `8000` / `5173` | Local ports |
| `STRAT_CACHE_DB` | `backend/data/cache.sqlite3` | Cache location |
| `STRAT_AS_OF` | unset | Cut the cached history off at this date (`YYYY-MM-DD`) to see the scanner as it looked then, e.g. `STRAT_AS_OF=2026-08-13 npm run dev`. The top bar then reads *Cut-off view, data through …*. Live polling is skipped |
| `STRAT_INTRADAY_PROVIDER` | `yahoo` | Who serves 15-minute bars. `alpaca` is the optional backfill (free Basic plan, SIP, 15-minute delay) |
| `ALPACA_API_KEY_ID`, `ALPACA_API_SECRET_KEY` | unset | Alpaca keys. `STRAT_ALPACA_KEY` and `STRAT_ALPACA_SECRET` are accepted too. Never commit them |
| `STRAT_ALPACA_FEED` | `sip` | Alpaca feed. Leave this on `sip` for a backtest; `iex` is one exchange and a poor low |

Example: `STRAT_MIN_PRICE=20 STRAT_MIN_DOLLAR_VOLUME=100000000 npm run dev`.

### How prices stay current

A single thread in the API process is the only thing that talks to Yahoo:

- When the newest confirmed daily bar is older than the last completed session, it downloads history (5 days if the gap is small, 3 months if the cache is merely behind, 3 years for a symbol that has never been downloaded).
- During the regular session (09:30–16:00 America/New_York, weekdays) it polls quotes at most every 15 minutes. Today's bar is kept beside the confirmed history, so a restart cannot overwrite a finished day with a partial one.
- After each download it recomputes the scan and stores the rows in `scan_snapshot`. The next page load reads that snapshot immediately. Chart pages still build from the bar cache.
- The history pass after the close also runs the morning-leader job for the last few sessions: the top 10 as of the prior close, that day's 5-minute bars, and the entry results. It does not run on the intraday quote poll.
- Browsers connect to `/ws` (proxied by Vite). They receive the snapshot on connect, a delta when the scan changes, and a ping every 15 seconds. If the socket drops, the page reconnects on its own and falls back to `GET /api/status` until it is back.
- Splits are stored raw. A scan, a `STRAT_AS_OF` cut-off, and the backtest adjust a bar only by splits whose ex-date is on or before the date being viewed. A split that lands inside a forward-return window does not look like a crash.

`POST /api/refresh` is still there for operators and `npm run refresh`. The UI does not call it.

## What it computes

Weekly (Mon-Fri) and monthly candles are built from the cached daily bars. The **last candle is the
current, still-forming period**, which is how The Strat is read in real time.

**Strat number** of each candle vs. the previous one:

- `1` inside: does not take out the prior high or low
- `2U`: takes out the prior high only; `2D`: takes out the prior low only
- `3` outside: takes out both

**Continuity**: a timeframe is green when price is above that period's open (red if below).
Monthly **and** Weekly green is a timing nuance, not a default gate: the Stock Scanner's Continuity filter defaults to **Any** (see [Backtest](#backtest) for why).

**Hammer**: lower wick ≥ 2× body, small upper wick (≤ the body or ≤ 10% of the range), and a close in
the top third of the range.

**Long setups** are detected on the **weekly** timeframe only (a monthly or daily pattern is context, not a setup). A
weekly setup is optional for the scanner: leaders without one are listed as *No setup / leader*, and the Trigger column
shows their **nearest trigger** (the closer of this week's and last week's high above price, in muted type).

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

See [How scoring works](#how-scoring-works) for the leadership score.

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

**The highest scores go to the stocks that go up the most; the Strat setup is a small timing bonus.** The score is 0–100.
Of the 100 points, 90 describe leadership and price behaviour and 10 are Strat timing. The weights were chosen with the
[rank-quality backtest](#backtest) (not by taste): the size of a stock's outperformance over QQQ ranks the big multi-month
winners much better than a percentile does, because a percentile saturates at P99.

```
score = raw × breakdown factor × (1 − kill-candle penalty) × 100 / max        (0–100, rounded to 0.1)
max: 100 for stocks · 90 for ETFs (no Theme strength) · 85 for themes (no Theme strength, no Liquidity)
```

**Weights.** A line's *weight* is its share of the 100-point stock score (max points ÷ 100 for stocks; for ETFs and themes the
same points are rescaled by their smaller max of 90 / 85, e.g. relative strength is 15/90 ≈ 16.7% of an ETF's score). The tooltip
shows the weight next to each label (`Vs QQQ (45%)  +35.6 / 45`) and the sub-weights under it.

| Component | Max points | Weight (stock) | Sub-weights | How it is computed |
| --- | ---: | ---: | --- | --- |
| **Relative strength** | 15 | 15% | 1M 20% · 3M 40% · 6M 40% | `15 × blended percentile` of the 1M / 3M / 6M price returns within the peer group (stocks vs stocks, ETFs vs ETFs, themes vs themes). |
| **Vs QQQ** | 45 | 45% | 1M 20% · 3M 40% · 6M 40%; full credit at +45 / +120 / +210 pts | Return minus **QQQ's return** (QQQ only, not SPY) over the same period, credited linearly up to **+45 / +120 / +210 points** (1M / 3M / 6M) and weighted 20/40/40. A name that only keeps up with QQQ earns nothing. This is the magnitude that percentiles hide, and the biggest lever for ranking the biggest winners first. |
| **Theme strength** | 10 | 10% | none | Stocks only. `10 × (N − rank + 1) / N` for the stock's **primary** theme among the N themes on the Themes page (the top theme gets all 10). Themes are ranked by their own leadership score. 0 for a stock in no theme. |
| **Trend** | 10 | 10% | 10-day 5 pts · 20-day 5 pts; each = price above the average 3 + average rising 2 | Only the **10-day and 20-day** averages score. For each: +3 when the close is above it and +2 when it is rising (above its value 5 bars ago), so a name above a rising 10-day and a rising 20-day gets all 10. The 50-day average and the distance from the highs do not score; they only feed the breakdown rules below. |
| **Range tightness** | 5 | 5% | last-10 vs 50-day range 60% · last-5 vs 20-day contraction 40% | Calm, contracting daily ranges score high and loose, expanding ones low. See below. |
| **Strat timing · weekly setup** | 4 | 4% | none | `4 × setup points / 25`: the strongest weekly setup plus 25% of the others, capped at 25 setup points (2-1 → 2-1-2 or 3-1 → 3-1-2 pending 23, inside week 20, hammer 18, 2-1-2 / 3-1-2 triggered 12, 1-2-2 RevStrat 10, 2D-2U 9, hammer triggered 8). 0 with no setup. |
| **Strat timing · distance to trigger** | 2.5 | 2.5% | none | `2.5 × (1 − d / 5%)` for how far price is below the weekly trigger (0 at 5% or more below). An already triggered setup gets half credit. |
| **Strat timing · continuity** | 2 | 2% | Monthly 0.75 · Weekly 0.75 · Daily 0.25 · all three +0.25 | Price above the period open on each timeframe, plus a bonus when all three are green. |
| **Strat timing · Monthly 2U** | 1.5 | 1.5% | none | +1.5 when the current monthly candle is a 2U. |
| **Liquidity** | 5 | 5% | none | `5 × log10(ADV / $50M) / log10(100)`: 0 at a $50M average daily dollar volume (20 days), 5 at $5B or more. Not used for themes. |
| **Kill candle** | penalty | 0 (multiplier) | up to −25%, fading to 0 over 10 sessions | A multiplier on the whole score, shown in the tooltip as `Kill candle (2026-10-05)` with the points removed. See below. |
| **Total** | **100** | **100%** | | Leadership 80% (RS 15 + Vs QQQ 45 + Theme 10 + Trend 10), range tightness 5%, liquidity 5% and the Strat overlay 10% (4 + 2.5 + 2 + 1.5). |

The Strat overlay is **at most 10 points** (4 + 2.5 + 2 + 1.5), so a perfect setup cannot lift a non-leader, and the same
leader scores at most 10 points higher with the best setup than with none.

**What changed from the first version, and why (evidence in the [backtest](#backtest)).** The requested weights were
RS 32 / Vs QQQ 15 / Theme 20 / Trend 13 / Strat 15 / Liquidity 5. The scanner at those weights (without the tightness and kill-candle rules) ranked the biggest winners worse than
the final one on both the train and the test dates, so the defaults were moved to the table above, and the requested variant
is reported next to them in the pull request. That comparison changes several things at once, so it does not isolate Theme and Trend. To go back, edit the constants at the top of `backend/strat/scoring.py`
(`RS_POINTS`, `QQQ_POINTS`, `THEME_POINTS`, `TREND_ABOVE_POINTS` / `TREND_RISING_POINTS`, the Strat overlay points) and
`FULL_EXCESS_PCT` in `backend/strat/leadership.py`; the maximum points and weights in the tooltip follow from them.

**Range tightness (5 points).** `0.6 × f(ratio) + 0.4 × f(contraction)`, where `ratio` is the average true range (as a % of
price, gaps included) of the last 10 sessions over the stock's own 50-session average, and `contraction` is the last 5
sessions over the last 20. `f` is linear: full credit at a ratio of 0.85 (range 15% tighter than usual) or less and none at 1.25 or
more; for contraction, full at 0.80 and none at 1.20. The absolute range level is deliberately not scored: in the
backtest, calm large caps were not better winners, but stocks whose ranges were expanding against their own baseline were
worse. The tooltip shows `10-day range 8.8% of price vs 50-day 7.8% (1.13×); last 5 days 10.9% vs 20-day 7.6% (1.44×)`.
The constants are in `backend/strat/pricebehavior.py`.

**Kill candle (multiplier penalty).** One wide, heavy red day is a distribution warning. A kill candle is a daily candle
within the last 10 sessions that is red, has a true range of at least **2.5× the prior 20-day average true range**, volume
of at least **1.5× the prior 50-day average**, and closes in the **lower 35%** of its range. The score is multiplied by
`1 − 0.25 × (1 − age / 10)`: −25% on the day, fading linearly to nothing at 10 sessions, and **0 as soon as price closes
above the candle's high**. The thresholds were tuned on the backtest dates (looser ones flagged too many ordinary pullbacks
and cost more winners than they avoided). The row's RS chip also shows `kill candle MM-DD`.

**Breakdown demotion.** A leader that is losing its trend is demoted instead of being ranked on stale 6M strength. The
score is multiplied by a factor and the tooltip shows the cut as a negative line (`Breakdown penalty` / `Weakening penalty`):

| Level | Trigger (any) | Effect |
| --- | --- | --- |
| **Broken** | close below the 50-day average, or 25%+ below the 6-month high | score × 0.5, and the name is **removed from the leaders list** (it shows under *Broken leaders*) |
| **Weakening** | close below the 20-day average, or 12%+ below the 6-month high, or the **1M return negative while the 3M/6M percentiles (blended) are still ≥ P75** (strength rolling over) | score × 0.9, listed with an amber *weakening* flag |

The reasons are in the row's tooltip, in the RS chip next to the symbol and in the Reason text, e.g.
`below the 50-day average; 25% below the 6-month high; 1M -2.7% while 3M/6M strength is still high with the 10/20-day averages lost`.

If the 20-day average daily range is under 0.5% of price (usually a stock pinned by a pending acquisition), the score is
halved again; this shows as a negative "Pinned penalty" line.

**Who counts as a leader.** The scanner **filters** rather than just ranking lower. A name is a *leader* when its blended
1M/3M/6M relative-strength percentile is at least the **Min RS** slider (default **P90**, top decile of its peer group,
`LEADER_MIN_RS` in `backend/strat/leadership.py`) **and** its trend is not broken. The Stock Scanner's **Leadership**
filter has seven options: *Leaders* (uses the Min RS slider, 50–99 in steps of 1, shown as `≥ P90`), *Weekly setups · awaiting
trigger*, *Weekly setups · triggered*, *Recent breakouts*, *Failed breakouts*, *Broken leaders* and *All names*. The hero chips are
full-universe totals for those categories (not the current filters); click a chip or pick a Leadership option to dig in. The Min RS slider
applies to *Leaders* and both *Weekly setups* views; *Recent breakouts*, *Failed breakouts* and *Broken leaders* ignore it. The slider is saved
like the other filters; a saved "Broad leaders" choice becomes *Leaders* at Min RS 80. `GET /api/scan` takes `leaders_only`
(default true) and `min_rs`. The Setup filter defaults to **Any**, so no weekly setup is needed. Every leader row carries an
**RS chip** (the RS change such as `▼7`, with *weakening* / *broken* / *kill candle* flags and the NEW markers below; the RS percentile itself is in the tooltip, since it already drives the score).

**What changed lately (RS change and NEW markers).** RS is a point-in-time reading, so the chip shows how it is changing (change detection:
`backend/strat/change.py`, no stored snapshots). Every earlier session is recomputed the same way as today and as `STRAT_AS_OF`
cuts the history: each symbol's history is truncated at that session's close, its 1M/3M/6M returns are measured on it and
ranked against its peers *on that date* (stocks vs stocks, ETFs vs ETFs, themes vs themes), then blended with the usual 20/40/40
weights. The sessions are QQQ's trading calendar, so every symbol is compared on the same dates. The scoring weights are untouched.

| Marker | Definition | Shown as |
| --- | --- | --- |
| **RS change** | today's blended RS percentile minus the same measure **5 sessions earlier**, in whole percentile points between the two chip values (`RS 91` vs `RS 98` = −7). Moves smaller than **3 points** are left off the chip | `▼7` in red, `▲12` in green |
| **NEW weakening / broken** | the breakdown level is worse today than on at least one of the **last 3 sessions**: none → weakening, none → broken or weakening → broken. The date is the first session at the new (or a worse) level, so `since` is today when it happened today. Unchanged or improving levels never count; the marker disappears 3 sessions after the change | `– · NEW · weakening`, `▼9 · NEW · broken` |
| **NEW leader** (extra) | RS is at or above **P90** (`LEADER_MIN_RS`) with the trend not broken today, and was below P90 on at least one of the last 3 sessions. A new worsening takes the place of this marker. It uses the fixed P90 gate, not the Min RS slider | `▲9 · NEW · leader` |

The tooltip keeps the full reading (`Relative strength P91: …`, the prior value and its date) and adds a line for each marker, e.g. `RS change vs 5 sessions ago: P98 on 2026-10-09 → P91 (▼7)` and
`NEW weakening: changed on 2026-10-15 (1 session ago), from no breakdown flag.`. A missing history (a new listing, or a cut-off with
fewer than 6 sessions behind it) simply leaves the fields empty. The scan row exposes `rs_prev` (0..1), `rs_prev_date`, `rs_change`
(percentile points), and `leadership.breakdown_new` (`{from, to, since, sessions_ago}`) and `leadership.leader_new`
(`{since, sessions_ago, from_rs}`), all `null` when nothing happened. The prior sessions cost four extra ranking passes per scan
(`SNAPSHOT_OFFSETS` in `change.py`; the peer distributions are built once per date and reused for every symbol); the backtest skips them.

**Weekly setups (leaders you can act on now).** *Leaders* that also have a **long-side weekly Strat setup on the last weekly
candle**: RS at or above the Min RS slider (default P90), trend not broken (a *weakening* name stays; a *broken* one never
does) and `has_setup`. The Leadership filter splits them into **awaiting trigger** (`triggered` is false) and **triggered**
(`triggered` is true). The setups are the ones the scanner already classifies, nothing is duplicated
(`find_long_setups` in `backend/strat/candles.py`): an **inside week** (1), **2-1-2** and **3-1-2** in progress (the inside
bar is done and price has not yet broken its high), **2-1-2 / 3-1-2 / 1-2-2 / 2D-2U** already triggered (the chip says
TRIGGERED), and a **weekly hammer** (pending below its own high, or triggered above the prior high). Each row shows the
**trigger** (the weekly high for longs; the prior high once triggered) and **To trigger**, the distance from price (positive =
still below the trigger, negative = already through it), and the rows keep the normal score order. It uses the same slider
as *Leaders*, so each setup view is always a subset of Leaders at the same Min RS. "Last weekly candle" is the latest weekly
bar in the data: complete on a Friday, Saturday or Sunday, partial for a mid-week `STRAT_AS_OF` cut-off (e.g. Thursday
2026-08-13 uses the week in progress), exactly as the rest of the scanner reads it. Hover the option in the dropdown for the
same definition. See the *Weekly setups backtest* below for how the combined filter did.

**Recent breakouts (future leaders, early).** Meant to surface names before they are leaders, so it ignores the slider
and uses an RS floor of **P50** (`MIN_RS` in `backend/strat/breakout.py`) plus an unbroken trend. On the weekly chart:

- a **tight base** of 3–10 weeks: its average weekly true range is at most 0.85× the stock's own range over the 20 weeks
  before the base, and it is at most 15% deep (high to low);
- a **breakout**: one of the last 3 weekly candles closes above the base high, on weekly volume of at least **2× the
  10-week average** (a part-finished week is scaled to five sessions), closing in the upper 35% of its range;
- **no active kill candle** since;
- and it has **not failed**: a breakout whose base high price has since closed below is listed under *Failed breakouts* instead.

Rows get a **Breakout** badge (`Breakout 2026-10-05 · 8-week base`) and are ranked by the normal score. The volume and depth
thresholds were picked on the train dates and checked on the test dates (see the [breakout study](#recent-breakouts-backtest)).

**Failed breakouts (a warning, the opposite of Recent breakouts).** Names that broke out and then lost the breakout. It
reuses the Recent breakouts detection (`_breakout_at` in `backend/strat/breakout.py`, so the same tight 3–10 week base,
2× volume and upper-35% close), but looks further back and checks what price did afterwards (`find_failed_breakout`):

- the breakout week is one of the weekly candles **1 to 8 weeks back** (`FAILED_LOOKBACK_WEEKS`; the current week cannot have
  failed yet). If there are several, the most recent breakout is the one that counts;
- it has **failed** when the latest daily close is **below the base high** the breakout cleared (the *breakout level*; a close
  exactly at the level still holds). The failure date is the first close below the level in the current run below it, so a
  dip that was reclaimed does not count and a second dip is dated by the second dip;
- no trend or kill-candle condition (a wide heavy down day is what a failure looks like), and **RS at P50 or better**, the same
  floor as Recent breakouts. The Leadership option ignores the Min RS slider.

Rows get a red **Failed breakout** badge (`Failed breakout 2026-10-05 · 1.9% below`, the tooltip adds the level, volume and failure date), the table shows
**Broke out**, **Level**, **Below level** (latest close vs the level; the tooltip has the deepest close since) and **Failed**
(date, tooltip: sessions below) columns, and is ordered by the **most recent failure**; click *Below level* to order by
severity instead. A failed breakout is **no longer listed under Recent breakouts**, so the two options never overlap. The
rows come from the same scan, so `STRAT_AS_OF` works (the history after the cut-off is hidden, so the failure appears only
once the close below the level is on or before the cut-off). It is a warning or avoid signal, not a buy signal; the
*Failed breakouts backtest* section below shows what such names did next. Scoring is unchanged.

**Relative strength details**

- **Returns** are price returns (percent) to the latest close over **1, 3 and 6 calendar months**. The base is the last
  close on or before the date one/three/six months earlier. A period is missing (`—`) when the history does not reach
  back that far. For a theme it is the equal-weight theme index return.
- **Percentile rank** within the peer group, per period: `(names below + ½ × names tied) / names with a return`, from 0
  (worst) to 1 (best). If a period is missing, the remaining weights are renormalized. The weights are `MOMENTUM_WEIGHTS` in
  `backend/strat/perf.py`; the QQQ caps and breakdown thresholds are constants in `backend/strat/leadership.py`.
- The label shows the blended percentile, e.g. `Relative strength · P97`; the hover/detail text shows each return with its
  percentile, the number of peers and the weights.

**Theme strength details**

- Themes are scored with the same leadership formula (without Theme strength and Liquidity) and ranked by that score on the
  Themes page (strongest first, ties by name). A stock's theme points come from its theme's rank, so a stock in a leading
  theme (peer-group strength) scores higher; only its *primary* theme counts.
- Scan order: returns and percentile distributions first, then the theme indexes and their scores, then the stock rows.
  A symbol added from the Watchlist or Positions that no theme lists scores 0 for this component.

When a name has several weekly setups, the one used for the trigger is the setup with the best combination of setup points
and closeness, with a small preference for setups that have not triggered yet.

**Worked example (DELL, Dell Technologies, cut off at Aug 13 2026, `STRAT_AS_OF=2026-08-13`):** a leader with no weekly setup, #1 on that date.

| Component | Points | Why |
| --- | ---: | --- |
| Relative strength | 14.54 / 15 | 1M +15.8% (P86), 3M +102.8% (P100), 6M +320.9% (P100) among 618 stocks: `0.20×0.86 + 0.40×1.00 + 0.40×1.00 = 0.97` |
| Vs QQQ | 35.64 / 45 | +12.9 / +100.3 / +299.3 points over QQQ (full credit at +45 / +120 / +210): `0.2×0.29 + 0.4×0.84 + 0.4×1.00 = 0.79` |
| Theme strength | 9.88 / 10 | AI hardware & servers, #2 of 82 themes |
| Trend | 10 / 10 | above a rising 10-day (5) and a rising 20-day (5) average |
| Range tightness | 3.80 / 5 | 10-day range 7.7% of price vs 7.9% over 50 days (0.97×); last 5 days 7.0% vs 8.2% (0.85×) |
| Strat timing | 3 / 10 | no weekly setup (0), Monthly and Weekly green (1.5), Monthly 2U (1.5) |
| Liquidity | 4.29 / 5 | $2.6B/day |
| **Raw total** | **81.15 / 100** | score 81.2; nearest trigger 514.00 (+3.9%, this week's high) |

**The same family after a breakdown (HPE, Oct 16 2026):** RS fell to P83 (1M -2.7%), the close is below the 50-day average
and 25% under the 6-month high, so the raw 37.0 is multiplied by 0.5 (a −18.5 *Breakdown penalty*) for a score of 18.5, and
it is no longer a leader.

**Loose ranges (current data, Oct 16 2026):** NBIS has a 10-day range of 8.8% of price against 7.8% over 50 days (1.13×)
and 10.9% over the last 5 days against 7.6% over 20 (1.44×), so it earns 0.9 of the 5 tightness points; STX (1.03× and
1.11×) earns 2.1. Both are also off the leaders list (below P90 and trend lost).

In the app, hover (or keyboard-focus) any score pill in the Stock Scanner, Watchlist or Positions table or on a
Themes or State of the Market card to see this breakdown.
The detail page has a **Score breakdown** panel with the same numbers plus a one-line explanation of each component. Each line shows its weight and sub-weights.

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
- **Stock Scanner** (`/`): ranked, sortable and filterable table of market leaders, with their weekly setup (if any) as timing.
  - Filters: search, **Leadership** (*Leaders* by default, plus *Weekly setups · awaiting trigger*, *Weekly setups · triggered*, *Recent breakouts*, *Failed breakouts*, *Broken leaders* and *All names*; see [How scoring works](#how-scoring-works)), **theme** (matches a stock's primary or secondary themes; also **No theme** for ETFs and stocks no theme lists), continuity (defaults to **Any**; includes Monthly 2U), weekly setup type and stocks/ETFs, using
    a custom dropdown (arrow keys, Home/End, type-to-jump, Enter/Space to pick, Esc or an outside click to close).
    The Setup filter has **Any**, **Awaiting trigger** (a trigger above price that has not traded yet), **Already
    triggered** (only rows whose weekly setup carries the TRIGGERED chip: 2-1-2 / 3-1-2 bullish, 2D-2U reversal, 1-2-2
    RevStrat and Hammer triggered), **Inside week** and **Weekly hammer**. The
    "To trigger" column is sortable by closeness to the weekly trigger.
  - The **RS chip** under each symbol shows the change in RS percentile vs 5 sessions ago (`▼7` red for drops, `▲12` green for
    rises; moves under 3 points are left off) and a `NEW` marker for a breakdown that just worsened or a leader that just crossed P90 (last 3
    sessions). A name with no change and no flag shows no chip. See [What changed lately](#how-scoring-works).
  - A **Min RS** slider (50–99, step 1, default 90, readout `≥ P90`) sets the relative-strength cut of *Leaders* and both
    *Weekly setups* views; *Recent breakouts*, *Failed breakouts* and *Broken leaders* ignore it (the slider is hidden for those options).
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
  - Names stay on the list whether or not they are leaders or have a weekly setup; they are then marked “no active setup” (leaders: “No setup / leader”).
  - The list is stored in the `watchlist` table of the local SQLite cache, so it survives restarts and data refreshes.
  - **Add symbol** (on the Watchlist tab) takes any Yahoo Finance ticker, not just universe names: type it (it is
    upper-cased) and press Enter.
    - Tickers outside the S&P 500 / Nasdaq-100 / ETF universe (e.g. `SOFI`) are first validated by downloading
      their history with yfinance. Only a ticker Yahoo reports as missing is rejected (404); a network failure
      returns 502 instead.
    - Their bars, name and sector are cached, and while they are watched they get the same M/W/D Strat data, score
      and trigger, are included in every data refresh, and have a working detail page and chart.
    - They show an **Added** chip.
    - They appear in the Stock Scanner when they pass its filters like any other name (so, by default, when they are leaders).
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
  - Results are cached in the `earnings` table. The end-of-day history job refreshes them. On startup, entries older
    than 12 hours are refreshed in the background. The 15-minute quote poll does not.
  - When the source has no date, no icon is shown; nothing is guessed. ETFs never show it.
- **Sticky selections**: the last tab (including the Stock Scanner's theme filter) and the M/W/D timeframe on the
  detail, Themes and State of the Market views are saved in `localStorage`. They survive navigation and full reloads, and opening the bare
  app URL reopens the last tab; a first-time visitor with nothing saved lands on **State of the Market**. Deep links such as
  `/stock/TDY` or `/?theme=memory` always win.
- **Loading states**: anything still loading shows a blue spinner with pulsing text (e.g. “Loading weekly setups…”).
  - Tables (Stock Scanner, Watchlist, Positions) show shimmering skeleton rows, and the chart views (State of the Market,
    Themes, detail page) show skeleton cards with a shimmering chart area, until the first data arrives.
  - The top bar is a live indicator, not a button. A grey dot means *Connecting* or *Reconnecting*. A blue dot means
    *Updating · 80/646 symbols*. A green dot means *15-min delayed · updated 3:45 PM ET*. A yellow dot means
    *Cut-off view, data through 2026-08-13*. A failed download shows *Price update failed* under the tabs.
  - With `prefers-reduced-motion: reduce` there is no pulsing, shimmer or spinning: the spinner becomes a static blue
    ring and the skeletons are drawn flat.

## Backtest

```bash
npm run backtest:leaders                  # rank quality, old vs new, biweekly over the whole cache (takes a few minutes)
npm run backtest:leaders -- --timeline    # also the weekly rank of the reference leaders and when each was demoted
npm run backtest:leaders -- --dates 2026-05-15 2026-08-13 --no-old
```

**The objective is rank quality for big winners:** the highest scores should go to the stocks that go up the most, found
early and kept near #1 while the run lasts. For every other Friday from the start of the cache (2024-05-10) the script hides
every price after that date (the same cut-off as `STRAT_AS_OF`) and adjusts earlier bars only for splits that had
already happened, scores the whole universe with the **old** Strat-first score
(`legacy_scoring.py`, weekly-setup rows only) and the **new** leadership score (leaders only), and compares them with what
happened next, over the liquid stocks (price >= $10, 20-day average dollar volume >= $50M). Per period it reports:

- the forward **1M and 3M return of the top 1 / 5 / 10** of each list minus the median liquid stock;
- the **Spearman** rank correlation between score and forward 3M return inside the list;
- **capture**: how many of the 10 best forward-3M performers of the whole market were in the list's top 10 / top 30, how many
  of those *runs* the list caught in its top 10 within 6 dates, and the median number of sessions from the run's first
  cut-off to the first time the name stood in the top 10;
- the **rank of the reference names** (SNDK, MU, NBIS, AMD, DELL, HPE, ARM, PLTR) on every cut-off from 2025-11-01, with
  their RS percentile (SNDK's run is the main check);
- **Recent breakouts**, **Weekly setups** and **Failed breakouts**: see below.

Cut-offs before 2025-10-01 are the **train** period (where weights and thresholds were tuned) and the rest is the **test**
period; both are reported.
`--timeline` adds the weekly rank of the reference leaders between 2026-04-24 and the last bar, and the first week each was
demoted off the list (to check that demotion happens early enough to matter).

**Recent breakouts backtest.** Pooled over every date, the forward 1M / 3M return of the names listed in Recent breakouts
minus the median stock, the share of the breakouts that were not yet leaders and became leaders (RS >= P90, unbroken) 4-8
weeks later against the same rate for every mid-pack name (RS P50-P90), and per reference name when it first appeared in the
view and when it first became a leader.

**Weekly setups backtest.** Pooled over every date, the forward 1M / 3M return of the Weekly setups names (RS >= P90,
unbroken, a long-side weekly setup) minus the median liquid stock and minus QQQ, next to all Leaders without a setup and all
Leaders. In the cache the setup filter did **not** beat plain Leaders (see the pull request for the table), so the Strat
setup works as a timing view on top of leadership, not as a stock-selection edge.

**Failed breakouts backtest.** Pooled over every date, the forward 1M / 3M return of the Failed breakouts names (and of the
*fresh* ones, which lost the level within the last 10 sessions) minus the median liquid stock and minus QQQ, next to
Recent breakouts. The numbers are in the pull request. Because the detection is strict (a heavy-volume close above a tight
base), only a handful of names qualify on any date, so the sample is small and noisy.

Caveats: the universe is today's S&P 500 + Nasdaq-100 (survivorship bias), the market only has a few distinct regimes in the
cache, forward 3M windows overlap between neighbouring dates, and the test period is short. Treat the numbers as evidence
for the direction of a change, not as a promise of future returns. The results of the last run are in the pull request.

## Morning Leaders

The Morning Leaders tab is the opposite of a quote screen. It does not ask anyone to watch the tape.
It shows the top 10 leaders at the prior close, then which of those names had closed above the 20-period RMA by **9:45, 10:00, 10:15, 10:30 and 10:45 ET**, and how buying the ones that had has worked.

### No lookahead

Leaders for session D are the live scanner's top 10 stocks (leadership score, leader gate, price and dollar-volume filters) computed on bars through **the previous session's close**. The same cut-off as `STRAT_AS_OF` and the backtest. Session D's bar is not an input to the leader list. A check-in uses only 5-minute bars whose end is at or before that minute.

### Who gets bought

On the 5-minute chart a name qualifies once a bar **closes above** its 20-period RMA. That is Wilder's smoothing, the same average as TradingView `ta.rma`: the first value is a simple average of 20 closes, and each bar after that is `(close + 19 × previous) / 20`. Earlier sessions warm the average, so it already has a value at the open. A prior session's close above the average is not the cross. The cross is the first bar of this session.

A name that has not closed above the RMA by the check-in is not bought. Among the names that have, the earliest cross is first. Ties break by symbol. The cross time is stored with the pick.

The entry is the close of the 5-minute bar that ends at the check-in, not the close of the cross bar. The earliest buy is 9:45. The stop is 1% under that price. One R is 1% of the entry, so a close 3% above the entry is +3R and a stopped trade is −1R. The entry bar is not a stop. A later 5-minute bar, through the rest of the session and the next five sessions, stops the trade when it trades at or below the stop. From the stop day on the result is −1R. A bar that opens below the stop is counted as a gap and still books −1R; its high is not credited, because the order inside one bar is unknown. A later session with no 5-minute bars uses that day's daily bar. The entry day's daily low is not a stop, because it includes the wick before the entry.

Average R gives each morning one vote. Expectancy is the mean R per fill. Win rate and the stop-hit rate are per fill. The summary picks the check-in with the highest average stop-aware R by **day 3**, and shows how many names qualified, the total R, the stop-hit rate, how many gapped through the stop, and the average maximum favorable excursion. QQQ held from the same minute is the benchmark, without a stop.

### Single entry at the low of day

A second study keeps one entry per name per day and stops at the low of day, the session low from 9:30 through the entry bar. One R is that distance, so the same percent move is a different R on a tight stop than on a wide one. A later 5-minute bar at or below the stop exits at the stop. A bar that opens below the stop exits at that open and is counted as a gap.

Two rules sit side by side. The **10:30** book buys every top-10 name that has closed above the 20 RMA by 10:30, at the 10:30 close. It also keeps the first name, the first two, and the first three. The existing first name is the earliest cross, then the symbol. The caps order a tie by the leader-list rank (rank 1 is the best prior-close score) and then the symbol. When that rank tie-break picks a different first name, both first books are shown. The **EMA** book buys at the close of the first 5-minute bar at or after 9:45 that closes above the 20-period EMA (earlier sessions warm the average; nothing before 9:45 is an entry), plus a book that keeps only the first of those names. The report shows percent and R at the close and through day 5, with win rate, stop-hit rate, total R, expectancy, MFE, and the best, median, and worst fill, against QQQ from the same minute. The EMA book's average entry time is in the report.

### Strat reversal, 15-minute and 30-minute

A third study buys the first bullish Strat reversal of the day on each top-10 leader. 15-minute and 30-minute candles are aggregated from the stored 5-minute bars, aligned to 9:30. The patterns are the reversals already in `find_long_setups`: 2d-2u, 2d-1-2u, 3-1-2u, and 1-2d-2u. 3-2u is not a reversal in that list, so it is not used. The opening candle is context only. Entry is the first 5-minute trade above the prior candle's high, at the prior high, or at the open when the bar gaps through it. The earliest fill is 9:45 on the 15-minute chart and 10:00 on the 30-minute chart, and nothing is filled after 15:30.

The stop is fixed at the trigger: the lower of the prior candle's low and the entry candle's low so far, excluding the trigger bar. It is not the entry candle's final low. Hits are tracked only after the entry. One R is that distance. Each timeframe is reported four ways: every name, the first name only, and the same two books limited to names whose 5-minute chart had closed above the 20 RMA by the decision time. The benchmark is the 10:30 first-name RMA book.

### RMA cross trigger

A fourth study buys every top-10 leader at the close of the first 5-minute bar, from 9:45 on, that closes strictly above a 20-period average. Earlier sessions warm the average. A bar that ends before 9:45 is not an entry. A name that never closes above the average is not bought. One trade per name per day.

The same rule runs on the Wilder RMA, the 20 SMA, and the 20 EMA. A name that opens above the average is included. "Opened above" is the open of the first regular-session bar (the 9:30 print) strictly above the average carried from the prior session, before today's bars update it. Those fills are counted, and they still enter at the first 9:45-or-later close above the average.

The stop is that entry bar's low. One R is that distance. The entry bar is not a stop. A later bar at or below the stop exits at the stop. A bar that opens below the stop exits at the open. A bar whose low is not strictly under its close is skipped. The benchmark is the 10:30 first-name RMA book.

### EMA pullback reclaim

A fifth study buys a top-10 leader only after it has closed below the 20 EMA during today's session and then closed back above it. Earlier sessions warm the EMA. The reclaim bar has to end at 9:45 or later. A close back above before 9:45 does not fill, and the name has to close below the EMA again. A name that never closes below the EMA, including one that opened above it and stayed there, is not bought. One reclaim per name per day.

The same entry is stopped three ways: the reclaim bar's low, the lowest low from the first close below through that reclaim bar, and the session low from 9:30 through the entry. Each stop is reported for every name and for the first one, two, and three names that day. The order is the reclaim time, then the leader-list rank (rank 1 is the best prior-close score), then the symbol. A name inside the cap keeps its place when one stop is not under the entry. The benchmark is the 10:30 first-name RMA book.

### 5-minute Strat pullback

A sixth study buys a top-10 leader only after a 5-minute bar has closed above the 20 RMA and a later bar is a pullback: a 2D or an inside. The entry is the first trade above that bar's high. The patterns are 2d-2u, 2d-1-2u, 3-1-2u, 1-2d-2u, and 1-2u. A 2U after a 3 is not one of them. A bar that opens above the prior high fills at the open. The earliest fill is 9:45. One book stops taking new fills at 11:00 and one at 10:30. One trade per name per day.

The stop is the low from 9:30 through the entry bar. One R is that distance. First, first 2, and first 3 keep the best leader-list ranks among the names that filled. The same widths of the 10:30 rank-tie book sit in the next columns. The report also shows the dollar risk per share against the 10:30 entry on the same name, and how much of that 10:30 price the earlier fill saved.

A second cut of that study keeps a fill only when its time is from 10:00 through 10:30. The pullback bar can print earlier. A trigger before 10:00 is skipped. One trade per name. The books are the first name and the first two, ordered by trigger time (tie-break leader rank, then symbol) and, separately, by leader rank among the names that triggered in the window. Those sit next to the 10:30 rank-tie first and first-2 books.

### What Yahoo will and will not give you

Checked on 2026-10-18:

| Request | What came back |
| --- | --- |
| 15-minute `period=60d` | 60 sessions, 2026-07-24 through 2026-10-16. This is the widest 15-minute window that fills |
| 15-minute `start` older than 60 calendar days | Rejected: "must be within the last 60 days" |
| 5-minute `period=60d` | The same 60 sessions |
| 1-hour `period=730d` | Back to 2023-11-17 |

`npm run morning:collect` stores leader snapshots for 12 months from the daily cache (no intraday vendor needed for the list), 5-minute bars for the leaders and QQQ inside Yahoo's window, and 15-minute bars for the same names. Bars stay in SQLite, so each new session after the close extends the history. Re-running is a no-op for days that are already complete.

### Schema

All in the existing cache (`STRAT_CACHE_DB`):

| Table | Key | What it holds |
| --- | --- | --- |
| `leader_snapshots` | `(date, rank)` | The top 10 for that session: symbol, leadership score, RS, name, and `as_of` (the prior close) |
| `intraday_bars` | `(symbol, ts, interval)` | Raw 5-minute and 15-minute bars. `ts` is the bar **end** in America/New_York (`2026-10-16T09:35:00` for the first 5-minute bar). `source` is `yahoo` or `alpaca` |
| `interval_ranks` | `(date, window, rank)` | Who had closed above the 20 RMA, the cross time (`HH:MM`), and the buy order (earliest cross first). A name that had not crossed is stored with `qualified` 0 and is not a buy |
| `entry_results` | `(date, symbol, window)` | Entry, the 1% stop price, EOD and +1..+5 close results in R, stopped flag and day, stop result (−1R), gap flag, MFE, MAE. Only names that qualified. `window` is `09:45` … `10:45`. `role` is `leader` or `benchmark` (QQQ) |
| `single_entry` | `(date, symbol, rule, entry_time)` | The low-of-day study. `rule` is `rma1030`, `ema`, or `qqq`. Percent closes, the stop, the exit, and the gap flag |
| `strat_reversal` | `(date, symbol, timeframe, entry_time)` | The 15- and 30-minute reversal study. `timeframe` is 15, 30, or 0 for QQQ. Pattern, whether the 20 RMA had been crossed by the fill, and whether the entry candle finished as a 2U |
| `cross_trigger` | `(date, symbol, rule, entry_time)` | The first 5-minute close from 9:45 above the 20 RMA, 20 SMA, or 20 EMA. `rule` is `rma`, `sma`, `ema`, or `qqq`. The stop is the entry bar's low. `opened_above` marks a 9:30 open already above the prior session's average |
| `ema_reclaim` | `(date, symbol, rule, entry_time)` | The first 5-minute close from 9:45 back above the 20 EMA after a close below it today. `rule` is `reclaim` (entry-bar low), `pullback` (pullback low), `lod` (low of day through the entry), or `qqq` |
| `intraday_gaps` | `(symbol, date, interval)` | A completed session the provider had nothing for, so the next run does not ask again |

Prices are stored raw and adjusted on read with the same split table as the scanner. A split inside a hold is not a loss.

### Backfill, and the five calls a day production needs

The collector asks only for symbol-days that are missing. After the close that is one session of the top 10 plus QQQ. A day of 15-minute bars for about 100 names is a few thousand rows, which is **one Alpaca call** (page limit 10,000) or a couple of Yahoo calls. Together with the daily history download the app already does, a production morning stays around five vendor calls. Twelve months of leaders is a local scan, not an API call.

Yahoo cannot backfill the six to twelve months of 15-minute bars this study wants. For a personal backtest of about 100 to 650 symbols, in the order worth trying:

| Source | Cost | What you actually get | Fit |
| --- | --- | --- | --- |
| **Alpaca Basic** | $0 | SIP historical bars since 2016, including 15-minute. The free plan's limit is the **latest 15 minutes** (the `end` must be at least 15 minutes old). 200 requests/minute. One symbol-year of 15-minute bars is about 6,500 rows, under one page, so ~100 symbols is a minute and ~650 is a few minutes at the rate cap | **Use this.** `STRAT_INTRADAY_PROVIDER=alpaca` plus the two key variables. The feed defaults to `sip`. Do not use `iex` for a stop-at-the-low study: IEX is one exchange and roughly 2–3% of volume, so the lows are wrong |
| Massive Starter | $29/month | Minute aggregates, 5 years, 15-minute delayed, flat files. Resample to 15 minutes. One month is enough to backfill, then cancel. Confirm the personal-use licence on the plan you buy | Best paid bulk dump if you would rather not open an Alpaca account |
| EODHD intraday | $29.99/month | No native 15-minute bar. 5-minute US bars from October 2020 (600-day window per call) resample cleanly. Intraday is stored raw and is **not** revised for later splits; this app's split table has to do that | Fine, more work than Alpaca |
| Twelve Data Grow | from $29/month | Native 15-minute, up to 5,000 bars per call (a year is two calls). Free Basic is 800 credits/day, one credit per symbol, so a 100-name recent window fits in a day and 650 names does not | Usable. The free tier is a thin backfill, not twelve months of the whole universe |
| Tiingo | $0–$30/month | IEX intraday. Same problem as Alpaca's IEX feed: the low is not the market's low | Skip for this study |
| IBKR (the account you already have) | Included with the brokerage | 15-minute bars are allowed. The step-size tables disagree on whether one request can be a week or a month; plan on **one week per request** to stay inside both. The hard pacing note (60 requests / 10 minutes) is written for bars of 30 seconds or less and is described as lifted for 1-minute and larger, with a soft throttle that still disconnects a noisy client. 100 symbols × 52 weeks is about 5,200 requests. TWS or the gateway has to be logged in. Personal use of your own market data is the compliant path | Works, and it is the slow one. Alpaca is a smaller project for the same SIP-quality bars |

Alpaca's own docs call IEX "the only feed that can be used without a subscription" in one page and, on the historical FAQ, say anything older than 15 minutes is available on Basic with `feed=sip`. This client sends `feed=sip` and a historical `end`. If a key is rejected, the error is the response body, not a silent fall-back to IEX.

### Reading it

`GET /api/morning?week=2026-10-12` returns that Monday–Friday board and the cached aggregate. The first call reads SQLite; the next call with the same rows is served from memory. The page has no dev-server labels.

## Layout

```
backend/
  strat/candles.py    Strat classification, continuity, hammer, long setups (pure, unit tested)
  strat/scoring.py    leadership-first score (relative strength, benchmarks, theme, trend; Strat timing overlay; breakdown penalty)
  strat/leadership.py trend structure, QQQ excess, breakdown detection, leader cut, nearest trigger
  strat/legacy_scoring.py  the previous Strat-first score, kept only for the backtest comparison
  strat/backtest.py   rank-quality backtest over biweekly cut-offs (`npm run backtest:leaders`)
  strat/perf.py       1M/3M/6M returns, percentile ranks and the relative-strength blend
  strat/change.py     RS change vs 5 sessions ago and NEW breakdown / NEW leader flags (prior-session ranks, pure functions)
  strat/themes.py     theme map loader/validator, equal-weight theme index, universe sync (`python -m strat.themes`)
  strat/themes_report.py  correlation validation and clustering report (`npm run themes:report`)
  strat/data.py       SQLite cache (bars, splits, session bar, scan snapshot, watchlist, positions, earnings, morning tables)
  strat/provider.py   MarketDataProvider; Yahoo is the Phase 1 daily implementation
  strat/intraday.py   15-minute providers (Yahoo, optional Alpaca)
  strat/morning.py    5-minute RMA cross, outcomes, expectancy (pure)
  strat/morning_collect.py  idempotent collector (`python -m strat.morning_collect`)
  strat/morning_report.py   backtest report (`python -m strat.morning_report`)
  strat/scheduler.py  when to download history vs poll the open session
  strat/adjust.py     point-in-time split adjustment
  strat/hub.py        WebSocket fan-out (one upstream fetcher, N browsers)
  strat/members.py    effective universe = universe + watched/held off-universe symbols
  strat/earnings.py   upcoming earnings dates and BMO/AMC timing from yfinance
  strat/scanner.py    per-symbol scan + chart payloads
  strat/universe.py   S&P 500 / Nasdaq-100 / ETF / theme-addition universe (snapshot in data/universe.csv)
  strat/api.py        FastAPI app (localhost only), including `GET /ws`
  data/themes.yaml    curated theme map (source of truth), data/themes_report.md = latest validation report
  tests/              pytest suite
web/                  React + Vite + lightweight-charts UI
scripts/              setup + dev launcher used by `npm run dev`
```

### Local API

The UI talks to the backend on `127.0.0.1:8000` (proxied through Vite as `/api` and `/ws`):

| Endpoint | Purpose |
| --- | --- |
| `GET /api/scan` | Ranked scan rows, leaders only by default (`leaders_only=false` for every name, `min_rs=0.8` for a looser cut). Rows without a weekly setup carry `nearest_trigger`; every row carries `rs_prev`, `rs_prev_date`, `rs_change` and `leadership.breakdown_new` / `leader_new` (see *What changed lately*) |
| `GET /api/symbol/{symbol}` | Scan row plus M/W/D chart candles for one symbol |
| `GET /api/themes?tf=W` | Theme cards for a timeframe, strongest first: index candles, scan row and member chips |
| `GET /api/config` | Liquidity defaults, `leader_min_rs` and the theme list (`id`, `name`, `count`) for the Scanner's filter |
| `GET /api/market?tf=W` | State of the Market cards: QQQ, SPY and IWM, in that order |
| `GET /api/watchlist` | Watched symbols (`symbols`), their scan rows (`rows`) and any without cached data yet (`missing`) |
| `POST /api/watchlist` | Add any ticker, body `{"symbol": "SOFI"}`. Returns 404 only if Yahoo Finance has no such symbol and 502 if the lookup fails |
| `DELETE /api/watchlist/{symbol}` | Remove a symbol |
| `GET /api/positions` | Open positions: `symbols` and `positions` (`symbol`, `entry_price`, `shares`, `entry_date`, scan `row` or `null` before data is cached) |
| `POST /api/positions` | Open a position in any ticker, body `{"symbol": "NVDA", "entry_price": 196.4, "shares": 40, "entry_date": "2026-09-22"}`. `entry_price` defaults to the last price, `entry_date` to today (US/Eastern) and `shares` is optional. Removes the name from the watchlist. 404 for unknown tickers, 409 if already held, 422 for a future date or non-positive numbers |
| `PUT /api/positions/{symbol}` | Edit `entry_price`, `shares` and `entry_date` |
| `DELETE /api/positions/{symbol}` | Close (remove) a position |
| `POST /api/positions/{symbol}/watchlist` | Move a position back to the watchlist |
| `GET /api/morning?week=YYYY-MM-DD` | Morning Leaders board for that week (Monday is inferred) plus the cached per-interval stats |
| `GET /api/status` | Cache status: `updating`, `version`, `computed_at`, `delay` (`15m` on Yahoo) |
| `WS /ws` | Snapshot on connect, deltas after a rescan, `ping` every 15 seconds |
| `POST /api/refresh` | Operator hook for a download. The scheduler calls the same job; the UI does not |

Not investment advice. Yahoo Finance data is unofficial and can be delayed or incomplete.
