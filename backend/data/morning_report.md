# Morning leaders

Which of the five morning check-ins is the best time to buy the leaders that have qualified.
Leaders are the scanner's top 10 stocks as of the **prior close**. A name is bought only after a
5-minute bar has closed above its 20-period RMA. Nothing here looks ahead.

A name is bought at a check-in only after a 5-minute bar has closed above its 20-period RMA (Wilder smoothing, the same average as TradingView ta.rma). Earlier sessions warm that average so it is valid at the open; they do not count as the cross. The earliest cross is bought first. The entry is the close of the 5-minute bar that ends at the check-in. The stop is 1% under that price. One R is 1% of the entry, so a stopped trade is −1R from the stop day on, including when a later 5-minute bar opens through the stop.

## What was collected

- Leader sessions stored: 251 (2510 rows).
- 5-minute bars stored: 247806 (2026-07-24T09:35:00 → 2026-10-16T16:00:00).
- 15-minute bars stored: 199653 (2026-07-24T09:45:00 → 2026-10-16T16:00:00).
- Bar sources: {'yahoo': 128}.
- Sessions with entry results: 59.
- Yahoo 5-minute and 15-minute history is about the last 59 calendar days (`period=60d`, 60 sessions). Older sessions keep their leader snapshot.

Sample-size caveat: the names bought in one morning move together, so 40 mornings are not 400 independent bets.
Average R gives each morning one vote. Expectancy is the mean R per fill. Win rate and the stop-hit rate are per fill.
Mornings when nobody had crossed are left out of the return columns and included in the qualified average.
A split inside the hold is adjusted out; it is not a loss.

## By check-in

1R is 1% of the entry. Qualified is the average number of the top 10 that had closed above the 20 RMA, including mornings when the count was zero.
EOD through +5d are stop-aware: a trade that has been stopped counts as −1R from the stop day on.
The stop is 1% under the entry. A later 5-minute bar at or below that price stops the trade. Gaps are fills whose stopping bar opened below the stop; they still book −1R.
A morning stays out of a horizon until that hold is finished: some name has the close stored, or every name is already stopped.
Days, fills, total R, win rate, stop-hit rate, gaps and expectancy are the +3 day sample. Each horizon's average uses the mornings finished through that horizon, so EOD can include a morning that does not yet have a day-3 close.
Avg MFE is the best R reached before the stop or the end of the +5 day hold, averaged over fills resolved by day 3.
9:45 is the earliest buy. QQQ is the same clock-time hold, without a stop.

| Window | Days | Fills | Qualified | EOD | +1d | +2d | +3d | +4d | +5d | Win | Stop | Gaps | Total R | Expectancy | Avg MFE |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 09:45 | 57 | 369 | 6.3 | -0.03R | -0.15R | -0.31R | -0.28R | -0.38R | -0.39R | 10.0% | 89.7% | 31 | -117.6R | -0.32R | +2.01R |
| 10:00 | 57 | 401 | 6.9 | -0.05R | -0.26R | -0.48R | -0.55R | -0.59R | -0.58R | 7.7% | 92.3% | 40 | -215.9R | -0.54R | +1.82R |
| 10:15 | 57 | 417 | 7.2 | -0.03R | -0.09R | -0.18R | -0.12R | -0.20R | -0.17R | 12.5% | 87.3% | 42 | -42.9R | -0.10R | +2.41R |
| 10:30 | 57 | 440 | 7.5 | +0.08R | +0.10R | +0.07R | +0.05R | -0.04R | +0.01R | 15.4% | 84.1% | 39 | +12.9R | +0.03R | +2.63R |
| 10:45 | 57 | 446 | 7.7 | +0.05R | +0.05R | -0.01R | 0.00R | -0.04R | +0.02R | 15.2% | 84.3% | 41 | +3.3R | +0.01R | +2.63R |

## Best time to buy leaders

**10:30** has the highest average +3d result: +0.05R per morning (15.4% of fills ahead, n = 57 mornings / 440 fills, total +12.9R).

On average 7.5 of the ten leaders had closed above the 20 RMA by 10:30.

A 1% stop was hit 84.1% of the time by +3d. 39 of those fills gapped through the stop and still booked −1R. Expectancy is +0.03R per trade. The average trade reached +2.63R in its favor before the stop or day 5.

Against holding QQQ from the same minute: -0.38R.

That is a description of this sample, not a promise. Overlapping holds, a short window, and today's index membership (survivorship) all apply.

## Single entry: 10:30 RMA and the 20 EMA

Two entry rules, each with every qualifying name and with only the first name that day. The 10:30 book buys a top-10 leader at the 10:30 close once a 5-minute bar has closed above the 20 RMA. The EMA book buys at the close of the first 5-minute bar at or after 9:45 that closes above the 20-period EMA; earlier sessions warm that average, and nothing before 9:45 is an entry. The stop is the low from 9:30 through the entry bar. One R is that distance. A later bar at or below the stop exits at the stop. A bar that opens below the stop exits at the open and is counted as a gap. Ties break by symbol.

Average entry time and average stop distance, per fill: **10:30 all** enters at 10:30 with an average stop 1.90% under the entry; **10:30 first** enters at 10:30 with an average stop 1.61% under the entry; **EMA all** enters at 10:22 on average (median 9:45) with an average stop 1.82% under the entry; **EMA first** enters at 9:46 on average (median 9:45) with an average stop 1.53% under the entry.

Average % and average R give each morning one vote. Expectancy, win rate, the stop-hit rate, and best, median, and worst are per fill. Total R sums those fills. From the stop day on the result is the exit: the stop price, or the open when the bar gapped through. vs QQQ is that morning's stop-aware percent minus QQQ held from the same minute, with no stop on QQQ. MFE is the best R reached before the stop or the end of the +5 day hold.

| | 10:30 all | 10:30 first | EMA all | EMA first |
| --- | ---: | ---: | ---: | ---: |
| EOD days | 59 | 59 | 60 | 60 |
| EOD fills | 451 | 59 | 597 | 60 |
| EOD avg % | +0.11% | +0.16% | -0.08% | -0.07% |
| EOD avg R | +0.04R | +0.12R | -0.08R | -0.02R |
| EOD win | 40.4% | 44.1% | 39.4% | 38.3% |
| EOD stop | 36.1% | 39.0% | 40.9% | 56.7% |
| EOD gaps | 3 | 1 | 3 | 0 |
| EOD total R | +4.8R | +6.9R | -49.2R | -1.2R |
| EOD expectancy | +0.01R | +0.12R | -0.08R | -0.02R |
| EOD avg MFE | +2.41R | +2.57R | +2.04R | +1.99R |
| EOD median R | -0.24R | -0.19R | -0.36R | -1.00R |
| EOD best R | +14.35R | +4.88R | +12.17R | +10.15R |
| EOD worst R | -3.00R | -1.03R | -1.09R | -1.00R |
| EOD median % | -0.18% | -0.15% | -0.40% | -0.57% |
| EOD best % | +6.30% | +6.14% | +10.38% | +10.38% |
| EOD worst % | -6.28% | -3.33% | -5.10% | -3.35% |
| EOD vs QQQ | +0.09% | +0.14% | -0.07% | -0.06% |
| +1d days | 58 | 59 | 59 | 60 |
| +1d fills | 442 | 59 | 588 | 60 |
| +1d avg % | +0.03% | -0.32% | -0.12% | -0.50% |
| +1d avg R | +0.03R | -0.08R | -0.11R | -0.05R |
| +1d win | 32.8% | 23.7% | 30.4% | 23.3% |
| +1d stop | 56.1% | 62.7% | 60.9% | 71.7% |
| +1d gaps | 26 | 6 | 43 | 2 |
| +1d total R | +8.6R | -4.8R | -64.1R | -3.1R |
| +1d expectancy | +0.02R | -0.08R | -0.11R | -0.05R |
| +1d avg MFE | +2.45R | +2.57R | +2.06R | +1.99R |
| +1d median R | -1.00R | -1.00R | -1.00R | -1.00R |
| +1d best R | +16.52R | +15.13R | +23.00R | +23.00R |
| +1d worst R | -4.56R | -4.56R | -6.53R | -1.77R |
| +1d median % | -0.53% | -0.73% | -0.81% | -0.90% |
| +1d best % | +15.08% | +9.30% | +14.96% | +7.91% |
| +1d worst % | -9.18% | -4.22% | -7.87% | -5.20% |
| +1d vs QQQ | -0.10% | -0.43% | -0.20% | -0.58% |
| +2d days | 57 | 58 | 58 | 60 |
| +2d fills | 438 | 58 | 578 | 60 |
| +2d avg % | -0.01% | -0.29% | -0.09% | -0.92% |
| +2d avg R | +0.01R | +0.07R | -0.18R | -0.36R |
| +2d win | 28.1% | 19.0% | 27.2% | 13.3% |
| +2d stop | 67.8% | 77.6% | 69.7% | 85.0% |
| +2d gaps | 38 | 9 | 54 | 4 |
| +2d total R | -5.7R | +4.3R | -104.4R | -21.4R |
| +2d expectancy | -0.01R | +0.07R | -0.18R | -0.36R |
| +2d avg MFE | +2.45R | +2.59R | +2.07R | +1.99R |
| +2d median R | -1.00R | -1.00R | -1.00R | -1.00R |
| +2d best R | +22.75R | +22.75R | +19.06R | +19.06R |
| +2d worst R | -4.71R | -4.56R | -7.05R | -1.77R |
| +2d median % | -0.75% | -1.13% | -0.99% | -1.16% |
| +2d best % | +19.13% | +13.99% | +19.42% | +7.03% |
| +2d worst % | -19.77% | -4.22% | -18.45% | -5.20% |
| +2d vs QQQ | -0.26% | -0.51% | -0.28% | -1.07% |
| +3d days | 57 | 58 | 58 | 60 |
| +3d fills | 438 | 58 | 578 | 60 |
| +3d avg % | -0.08% | -0.17% | -0.11% | -0.98% |
| +3d avg R | -0.01R | +0.29R | -0.19R | -0.32R |
| +3d win | 23.3% | 19.0% | 23.0% | 11.7% |
| +3d stop | 73.3% | 77.6% | 75.1% | 86.7% |
| +3d gaps | 43 | 9 | 60 | 5 |
| +3d total R | -21.1R | +17.1R | -108.2R | -19.5R |
| +3d expectancy | -0.05R | +0.29R | -0.19R | -0.32R |
| +3d avg MFE | +2.45R | +2.59R | +2.07R | +1.99R |
| +3d median R | -1.00R | -1.00R | -1.00R | -1.00R |
| +3d best R | +22.74R | +21.56R | +24.45R | +24.45R |
| +3d worst R | -8.06R | -4.56R | -7.05R | -1.77R |
| +3d median % | -0.93% | -1.13% | -1.13% | -1.21% |
| +3d best % | +16.89% | +16.89% | +18.31% | +5.77% |
| +3d worst % | -19.77% | -4.22% | -18.45% | -5.20% |
| +3d vs QQQ | -0.51% | -0.58% | -0.42% | -1.31% |
| +4d days | 56 | 58 | 57 | 60 |
| +4d fills | 429 | 58 | 568 | 60 |
| +4d avg % | -0.18% | -0.27% | -0.02% | -0.98% |
| +4d avg R | -0.11R | +0.16R | -0.13R | -0.23R |
| +4d win | 20.3% | 17.2% | 20.9% | 11.7% |
| +4d stop | 76.9% | 77.6% | 78.0% | 86.7% |
| +4d gaps | 42 | 9 | 60 | 5 |
| +4d total R | -53.3R | +9.2R | -72.2R | -13.7R |
| +4d expectancy | -0.12R | +0.16R | -0.13R | -0.23R |
| +4d avg MFE | +2.47R | +2.59R | +2.09R | +1.99R |
| +4d median R | -1.00R | -1.00R | -1.00R | -1.00R |
| +4d best R | +23.88R | +19.39R | +30.58R | +30.58R |
| +4d worst R | -18.68R | -4.56R | -7.05R | -1.77R |
| +4d median % | -1.02% | -1.21% | -1.19% | -1.27% |
| +4d best % | +17.64% | +16.14% | +20.77% | +9.36% |
| +4d worst % | -19.77% | -4.22% | -18.45% | -5.20% |
| +4d vs QQQ | -0.78% | -0.77% | -0.54% | -1.45% |
| +5d days | 56 | 58 | 57 | 60 |
| +5d fills | 429 | 58 | 568 | 60 |
| +5d avg % | -0.18% | -0.22% | +0.06% | -0.91% |
| +5d avg R | -0.15R | +0.33R | -0.09R | -0.14R |
| +5d win | 18.6% | 15.5% | 19.0% | 8.3% |
| +5d stop | 79.2% | 81.0% | 79.9% | 90.0% |
| +5d gaps | 46 | 9 | 64 | 5 |
| +5d total R | -53.1R | +19.2R | -51.6R | -8.5R |
| +5d expectancy | -0.12R | +0.33R | -0.09R | -0.14R |
| +5d avg MFE | +2.47R | +2.59R | +2.09R | +1.99R |
| +5d median R | -1.00R | -1.00R | -1.00R | -1.00R |
| +5d best R | +36.12R | +25.56R | +33.79R | +33.79R |
| +5d worst R | -35.26R | -4.56R | -7.61R | -1.77R |
| +5d median % | -1.08% | -1.33% | -1.22% | -1.27% |
| +5d best % | +20.97% | +15.85% | +27.14% | +14.83% |
| +5d worst % | -19.77% | -4.99% | -18.45% | -5.20% |
| +5d vs QQQ | -0.93% | -0.84% | -0.61% | -1.54% |
