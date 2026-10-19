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

Two entry rules, each with every qualifying name and with only the first name that day. The 10:30 book buys a top-10 leader at the 10:30 close once a 5-minute bar has closed above the 20 RMA. The EMA book buys at the close of the first 5-minute bar at or after 9:45 that closes above the 20-period EMA; earlier sessions warm that average, and nothing before 9:45 is an entry. The stop is the low from 9:30 through the entry bar. One R is that distance. A later bar at or below the stop exits at the stop. A bar that opens below the stop exits at the open and is counted as a gap. The existing first name is the earliest cross, and a tie breaks by symbol. The 10:30 caps take the first two and the first three names in a different tie-break: earliest cross, then the leader-list rank, then the symbol. Rank 1 is the best prior-close score. When that rank tie-break picks a different first name, both first books are shown.

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

### 10:30 RMA, first two and first three

First 2 and First 3 are the earliest 20 RMA crosses, then the better leader-list rank, then the symbol. The First column is the existing book, which breaks a tie by symbol. On 38 mornings the rank tie-break picks a different first name, so that book is shown beside it.

Every one of these buys at the 10:30 close. The stop is the low from 9:30 through that bar. One R is that distance. R per trade is the expectancy, the mean R per fill. Average R gives each morning one vote. First is the existing book. All is every name that had closed above the 20 RMA by 10:30.

Average stop under the entry: **First** stop 1.61%; **First, rank tie** stop 2.07%; **First 2** stop 2.08%; **First 3** stop 2.00%; **All** stop 1.90%.

| | First | First, rank tie | First 2 | First 3 | All |
| --- | ---: | ---: | ---: | ---: | ---: |
| EOD days | 59 | 59 | 59 | 59 | 59 |
| EOD fills | 59 | 59 | 118 | 177 | 451 |
| EOD avg % | +0.16% | +0.59% | +0.12% | +0.16% | +0.11% |
| EOD avg R | +0.12R | +0.57R | +0.24R | +0.17R | +0.04R |
| EOD win | 44.1% | 54.2% | 40.7% | 44.1% | 40.4% |
| EOD stop | 39.0% | 27.1% | 32.2% | 32.8% | 36.1% |
| EOD gaps | 1 | 1 | 2 | 2 | 3 |
| EOD total R | +6.9R | +33.7R | +27.8R | +29.7R | +4.8R |
| EOD expectancy | +0.12R | +0.57R | +0.24R | +0.17R | +0.01R |
| EOD avg MFE | +2.57R | +3.85R | +3.39R | +3.28R | +2.41R |
| EOD median R | -0.19R | +0.06R | -0.20R | -0.15R | -0.24R |
| EOD best R | +4.88R | +14.35R | +14.35R | +14.35R | +14.35R |
| EOD worst R | -1.03R | -1.03R | -3.00R | -3.00R | -3.00R |
| EOD median % | -0.15% | +0.24% | -0.17% | -0.12% | -0.18% |
| EOD best % | +6.14% | +6.14% | +6.14% | +6.14% | +6.30% |
| EOD worst % | -3.33% | -3.33% | -6.28% | -6.28% | -6.28% |
| EOD vs QQQ | +0.14% | +0.57% | +0.09% | +0.13% | +0.09% |
| +1d days | 59 | 59 | 59 | 59 | 58 |
| +1d fills | 59 | 59 | 118 | 177 | 442 |
| +1d avg % | -0.32% | +0.93% | +0.16% | +0.18% | +0.03% |
| +1d avg R | -0.08R | +0.90R | +0.50R | +0.33R | +0.03R |
| +1d win | 23.7% | 40.7% | 33.1% | 33.9% | 32.8% |
| +1d stop | 62.7% | 47.5% | 55.1% | 54.2% | 56.1% |
| +1d gaps | 6 | 4 | 9 | 12 | 26 |
| +1d total R | -4.8R | +53.2R | +59.2R | +58.2R | +8.6R |
| +1d expectancy | -0.08R | +0.90R | +0.50R | +0.33R | +0.02R |
| +1d avg MFE | +2.57R | +3.85R | +3.39R | +3.28R | +2.45R |
| +1d median R | -1.00R | -0.64R | -1.00R | -1.00R | -1.00R |
| +1d best R | +15.13R | +15.13R | +16.52R | +16.52R | +16.52R |
| +1d worst R | -4.56R | -2.52R | -3.00R | -4.56R | -4.56R |
| +1d median % | -0.73% | -0.57% | -0.69% | -0.62% | -0.53% |
| +1d best % | +9.30% | +15.08% | +15.08% | +15.08% | +15.08% |
| +1d worst % | -4.22% | -5.37% | -6.68% | -6.77% | -9.18% |
| +1d vs QQQ | -0.43% | +0.85% | +0.06% | +0.07% | -0.10% |
| +2d days | 58 | 58 | 58 | 58 | 57 |
| +2d fills | 58 | 58 | 116 | 174 | 438 |
| +2d avg % | -0.29% | +0.63% | +0.15% | +0.13% | -0.01% |
| +2d avg R | +0.07R | +0.74R | +0.54R | +0.41R | +0.01R |
| +2d win | 19.0% | 31.0% | 28.4% | 29.9% | 28.1% |
| +2d stop | 77.6% | 62.1% | 68.1% | 65.5% | 67.8% |
| +2d gaps | 9 | 7 | 12 | 16 | 38 |
| +2d total R | +4.3R | +42.8R | +63.0R | +70.8R | -5.7R |
| +2d expectancy | +0.07R | +0.74R | +0.54R | +0.41R | -0.01R |
| +2d avg MFE | +2.59R | +3.89R | +3.42R | +3.31R | +2.45R |
| +2d median R | -1.00R | -1.00R | -1.00R | -1.00R | -1.00R |
| +2d best R | +22.75R | +22.75R | +22.75R | +22.75R | +22.75R |
| +2d worst R | -4.56R | -2.52R | -3.00R | -4.71R | -4.71R |
| +2d median % | -1.13% | -1.03% | -0.93% | -0.78% | -0.75% |
| +2d best % | +13.99% | +13.99% | +13.99% | +13.99% | +19.13% |
| +2d worst % | -4.22% | -4.16% | -6.68% | -19.77% | -19.77% |
| +2d vs QQQ | -0.51% | +0.42% | -0.08% | -0.10% | -0.26% |
| +3d days | 58 | 58 | 58 | 58 | 57 |
| +3d fills | 58 | 58 | 116 | 174 | 438 |
| +3d avg % | -0.17% | +0.74% | +0.26% | +0.22% | -0.08% |
| +3d avg R | +0.29R | +0.85R | +0.68R | +0.51R | -0.01R |
| +3d win | 19.0% | 29.3% | 25.9% | 25.9% | 23.3% |
| +3d stop | 77.6% | 69.0% | 71.5% | 70.1% | 73.3% |
| +3d gaps | 9 | 8 | 13 | 18 | 43 |
| +3d total R | +17.1R | +49.2R | +79.4R | +88.6R | -21.1R |
| +3d expectancy | +0.29R | +0.85R | +0.68R | +0.51R | -0.05R |
| +3d avg MFE | +2.59R | +3.89R | +3.42R | +3.31R | +2.45R |
| +3d median R | -1.00R | -1.00R | -1.00R | -1.00R | -1.00R |
| +3d best R | +21.56R | +21.56R | +22.74R | +22.74R | +22.74R |
| +3d worst R | -4.56R | -2.52R | -3.00R | -4.71R | -8.06R |
| +3d median % | -1.13% | -1.03% | -1.00% | -0.97% | -0.93% |
| +3d best % | +16.89% | +16.89% | +16.89% | +16.89% | +16.89% |
| +3d worst % | -4.22% | -4.16% | -6.68% | -19.77% | -19.77% |
| +3d vs QQQ | -0.58% | +0.37% | -0.14% | -0.19% | -0.51% |
| +4d days | 58 | 58 | 58 | 58 | 56 |
| +4d fills | 58 | 58 | 116 | 174 | 429 |
| +4d avg % | -0.27% | +0.61% | +0.28% | +0.10% | -0.18% |
| +4d avg R | +0.16R | +0.87R | +0.69R | +0.33R | -0.11R |
| +4d win | 17.2% | 24.1% | 23.3% | 21.8% | 20.3% |
| +4d stop | 77.6% | 70.7% | 73.3% | 73.6% | 76.9% |
| +4d gaps | 9 | 8 | 13 | 20 | 42 |
| +4d total R | +9.2R | +50.7R | +79.9R | +56.7R | -53.3R |
| +4d expectancy | +0.16R | +0.87R | +0.69R | +0.33R | -0.12R |
| +4d avg MFE | +2.59R | +3.89R | +3.42R | +3.31R | +2.47R |
| +4d median R | -1.00R | -1.00R | -1.00R | -1.00R | -1.00R |
| +4d best R | +19.39R | +19.39R | +23.88R | +23.88R | +23.88R |
| +4d worst R | -4.56R | -2.52R | -3.00R | -18.68R | -18.68R |
| +4d median % | -1.21% | -1.18% | -1.03% | -1.00% | -1.02% |
| +4d best % | +16.14% | +17.64% | +17.64% | +17.64% | +17.64% |
| +4d worst % | -4.22% | -4.16% | -6.68% | -19.77% | -19.77% |
| +4d vs QQQ | -0.77% | +0.14% | -0.24% | -0.43% | -0.78% |
| +5d days | 58 | 58 | 58 | 58 | 56 |
| +5d fills | 58 | 58 | 116 | 174 | 429 |
| +5d avg % | -0.22% | +0.71% | +0.22% | +0.11% | -0.18% |
| +5d avg R | +0.33R | +1.12R | +0.61R | +0.33R | -0.15R |
| +5d win | 15.5% | 24.1% | 22.4% | 21.3% | 18.6% |
| +5d stop | 81.0% | 75.9% | 76.7% | 76.4% | 79.2% |
| +5d gaps | 9 | 9 | 15 | 23 | 46 |
| +5d total R | +19.2R | +64.8R | +70.7R | +58.3R | -53.1R |
| +5d expectancy | +0.33R | +1.12R | +0.61R | +0.33R | -0.12R |
| +5d avg MFE | +2.59R | +3.89R | +3.42R | +3.31R | +2.47R |
| +5d median R | -1.00R | -1.00R | -1.00R | -1.00R | -1.00R |
| +5d best R | +25.56R | +25.56R | +36.12R | +36.12R | +36.12R |
| +5d worst R | -4.56R | -2.52R | -35.26R | -35.26R | -35.26R |
| +5d median % | -1.33% | -1.18% | -1.07% | -1.08% | -1.08% |
| +5d best % | +15.85% | +20.97% | +20.97% | +20.97% | +20.97% |
| +5d worst % | -4.99% | -4.99% | -14.00% | -19.77% | -19.77% |
| +5d vs QQQ | -0.84% | +0.10% | -0.44% | -0.56% | -0.93% |

Average R from the close through day 5, one number per book in the column order above:

- **First**: +0.12R, -0.08R, +0.07R, +0.29R, +0.16R, +0.33R.
- **First, rank tie**: +0.57R, +0.90R, +0.74R, +0.85R, +0.87R, +1.12R.
- **First 2**: +0.24R, +0.50R, +0.54R, +0.68R, +0.69R, +0.61R.
- **First 3**: +0.17R, +0.33R, +0.41R, +0.51R, +0.33R, +0.33R.
- **All**: +0.04R, +0.03R, +0.01R, -0.01R, -0.11R, -0.15R.

### One 10:30 first morning

**2026-10-09**, **CRWD** (CrowdStrike), prior-close leader rank 7. Day 3 on this fill is -1.00R, the median of the 53 completed first fills other than the best, +21.56R on 2026-07-31. It is the most recent fill in that typical group with a day-5 close. It is the existing First book: earliest cross, then the symbol. The rank tie-break that morning would have bought TEAM first.

The first 5-minute bar of the session to close above the 20 RMA ended at 9:35. That close was $267.64 and the RMA was $264.30.
The entry is the 10:30 close, $266.65. The stop is the low from 9:30 through that bar, $262.44. The stop sits 1.58% under the entry, so 1R is $4.21.

The stop was hit on the +1 session (2026-10-12), the 5-minute bar ending 13:15. The bar traded down to the stop (open $263.05, low $262.17) and the exit is $262.44.

The close columns are the session close against the entry, with no stop. The booked columns are what the study keeps: from the stop session on, the exit.

| | Date | Close | Close % | Close R | Booked % | Booked R |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| EOD | 2026-10-09 | $275.04 | +3.15% | +1.99R | +3.15% | +1.99R |
| +1d | 2026-10-12 | $263.01 | -1.37% | -0.86R | -1.58% | -1.00R |
| +2d | 2026-10-13 | $261.21 | -2.04% | -1.29R | -1.58% | -1.00R |
| +3d | 2026-10-14 | $249.29 | -6.51% | -4.12R | -1.58% | -1.00R |
| +4d | 2026-10-15 | $244.57 | -8.28% | -5.24R | -1.58% | -1.00R |
| +5d | 2026-10-16 | $227.39 | -14.72% | -9.33R | -1.58% | -1.00R |

Qualified that morning, in the existing symbol order, then the rank order. A name qualifies when a 5-minute bar has closed above the 20 RMA by 10:30 and the low from 9:30 through 10:30 is under that close.

**Symbol order:** CRWD rank 7 at 09:35; DELL rank 6 at 09:35; HPE rank 4 at 09:35; MRNA rank 3 at 09:35; OKTA rank 5 at 09:35; P rank 8 at 09:35; TEAM rank 2 at 09:35; MPC rank 9 at 09:40; VLO rank 10 at 09:45.
**Rank order:** TEAM rank 2 at 09:35; MRNA rank 3 at 09:35; HPE rank 4 at 09:35; OKTA rank 5 at 09:35; DELL rank 6 at 09:35; CRWD rank 7 at 09:35; P rank 8 at 09:35; MPC rank 9 at 09:40; VLO rank 10 at 09:45.

Skipped:

- **CTVA** (Corteva, Inc.), leader rank 1: no 5-minute close above the 20 RMA by 10:30.

## Stop sweep, 10:30 rank tie

First and First 2 of the 10:30 rank-tie book. The entry stays the 10:30 close after a 5-minute bar has closed above the 20 RMA. The order is the earliest cross, then the leader rank, then the symbol. Only the stop changes. Each stop is set at 10:30 from prices known then and is never moved. A stop that is not strictly under the entry is skipped, and a later name does not take the slot. One R is the distance from the entry down to that stop. R per trade and total R size every fill to risk 1R. Average percent and total percent keep the same position size on every fill, so a tight stop does not inflate them.

These stops are judged on 5-minute bars. A very tight stop is sensitive to that bar size and to slippage: the low of a 5-minute bar can trade through a stop that a finer tape would have filled, and the order inside the bar is unknown. The slippage variant fills every stop exit 0.05% worse than the stop or the gap open. The risk unit stays the original stop, so a touch can book worse than -1R.

Candidates are ranked by day-3 R per trade, and again by day-3 total R. The tightest stop near the top is the smallest average stop among those within 0.05R of the best day-3 R per trade. Low of day is the current baseline.


### First

**0.25%** is the best day-3 R per trade on First at +1.85R (59 fills, total +109.4R). Low of day is +0.85R per trade, total +49.2R. The same stop also leads on total R. That stop is the tightest within 0.05R of the best. Its average stop is 0.25%. With 0.05% slippage on the stop exit it is +1.67R per trade (total +98.6R).

| Stop | Stop % | Skipped | Fills | R/trade | Total R | Win | Stop | Gaps | Avg % | Total % | MFE | Median R | Best | Worst | 30m | Slip R | Slip total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **0.25%** (best R, tightest near top) | 0.25% | 0 | 59 | +1.85R | +109.4R | 8.5% | 91.5% | 6 | +0.46% | +27.3% | +6.91R | -1.00R | +63.19R | -11.06R | 69.5% | +1.67R | +98.6R |
| 20 RMA | 1.25% | 13 | 45 | +1.78R | +80.0R | 22.2% | 77.8% | 7 | +0.12% | +5.2% | +5.63R | -1.00R | +59.67R | -5.09R | 15.2% | +1.68R | +75.7R |
| RMA - 0.1 ATR | 1.57% | 6 | 52 | +1.50R | +77.9R | 25.0% | 75.0% | 8 | +0.26% | +13.3% | +4.53R | -1.00R | +34.83R | -2.21R | 11.3% | +1.44R | +74.6R |
| 10:30 bar | 0.26% | 2 | 57 | +1.44R | +82.3R | 8.8% | 91.2% | 4 | +0.54% | +30.9% | +7.25R | -1.00R | +61.61R | -9.69R | 64.9% | +1.00R | +57.3R |
| 0.50% | 0.50% | 0 | 59 | +1.15R | +68.1R | 11.9% | 88.1% | 5 | +0.58% | +34.1% | +5.66R | -1.00R | +33.78R | -5.53R | 37.3% | +1.07R | +63.0R |
| Last 2 bars | 0.39% | 1 | 58 | +1.06R | +61.4R | 10.3% | 89.7% | 6 | +0.38% | +22.0% | +6.48R | -1.00R | +61.61R | -14.60R | 51.7% | +0.79R | +45.9R |
| 0.10x daily ATR | 0.52% | 0 | 59 | +1.05R | +62.1R | 11.9% | 88.1% | 5 | +0.56% | +32.9% | +4.92R | -1.00R | +31.04R | -3.91R | 40.7% | +0.96R | +56.8R |
| Last 3 bars | 0.49% | 0 | 59 | +0.98R | +58.0R | 10.2% | 89.8% | 6 | +0.28% | +16.4% | +6.04R | -1.00R | +61.61R | -14.60R | 47.5% | +0.77R | +45.3R |
| 15-min low | 0.49% | 0 | 59 | +0.98R | +58.0R | 10.2% | 89.8% | 6 | +0.28% | +16.4% | +6.04R | -1.00R | +61.61R | -14.60R | 47.5% | +0.77R | +45.3R |
| Low since cross | 2.07% | 0 | 58 | +0.85R | +49.2R | 29.3% | 69.0% | 8 | +0.74% | +42.8% | +3.89R | -1.00R | +21.56R | -2.52R | 8.5% | +0.82R | +47.4R |
| Low of day | 2.07% | 0 | 58 | +0.85R | +49.2R | 29.3% | 69.0% | 8 | +0.74% | +42.8% | +3.89R | -1.00R | +21.56R | -2.52R | 8.5% | +0.82R | +47.4R |
| 0.75% | 0.75% | 0 | 59 | +0.60R | +35.5R | 15.2% | 84.8% | 8 | +0.45% | +26.6% | +4.05R | -1.00R | +22.52R | -3.69R | 30.5% | +0.55R | +32.2R |
| 1x 5-min ATR | 0.66% | 0 | 59 | +0.59R | +34.9R | 11.9% | 88.1% | 7 | +0.43% | +25.1% | +4.35R | -1.00R | +23.38R | -5.31R | 33.9% | +0.52R | +30.7R |
| 0.20x daily ATR | 1.05% | 0 | 59 | +0.56R | +32.8R | 18.6% | 81.4% | 5 | +0.67% | +39.6% | +3.54R | -1.00R | +15.52R | -1.96R | 22.0% | +0.51R | +30.4R |
| 0.15x daily ATR | 0.79% | 0 | 59 | +0.55R | +32.3R | 15.2% | 84.8% | 7 | +0.42% | +24.9% | +3.93R | -1.00R | +20.69R | -2.61R | 32.2% | +0.49R | +28.9R |
| 30-min low | 0.74% | 0 | 59 | +0.50R | +29.4R | 13.6% | 86.4% | 8 | +0.11% | +6.7% | +5.03R | -1.00R | +34.40R | -8.23R | 35.6% | +0.36R | +21.1R |
| 1.5x 5-min ATR | 0.98% | 0 | 59 | +0.44R | +25.9R | 17.0% | 83.0% | 6 | +0.48% | +28.4% | +3.54R | -1.00R | +15.58R | -3.54R | 23.7% | +0.39R | +23.2R |
| 1.50% | 1.50% | 0 | 58 | +0.35R | +20.5R | 24.1% | 75.9% | 6 | +0.53% | +30.7% | +3.14R | -1.00R | +11.26R | -2.48R | 1.7% | +0.33R | +19.0R |
| 2x 5-min ATR | 1.31% | 0 | 58 | +0.31R | +17.9R | 22.4% | 77.6% | 11 | +0.50% | +29.0% | +3.37R | -1.00R | +11.69R | -3.23R | 8.5% | +0.28R | +16.0R |
| 0.25x daily ATR | 1.31% | 0 | 59 | +0.29R | +17.3R | 20.3% | 79.7% | 8 | +0.47% | +27.7% | +3.10R | -1.00R | +12.41R | -2.96R | 13.6% | +0.26R | +15.4R |
| 1.00% | 1.00% | 0 | 58 | +0.27R | +15.8R | 15.5% | 84.5% | 7 | +0.27% | +15.8% | +3.18R | -1.00R | +16.89R | -2.76R | 17.0% | +0.23R | +13.4R |
| 3x 5-min ATR | 1.97% | 0 | 57 | +0.20R | +11.3R | 29.8% | 70.2% | 9 | +0.76% | +43.3% | +2.46R | -1.00R | +7.79R | -2.15R | 1.7% | +0.18R | +10.1R |
| 0.50x daily ATR | 2.62% | 0 | 56 | +0.19R | +10.5R | 39.3% | 60.7% | 8 | +0.69% | +38.5% | +2.07R | -1.00R | +6.21R | -2.07R | 0.0% | +0.17R | +9.8R |
| 0.33x daily ATR | 1.73% | 0 | 57 | +0.17R | +9.7R | 26.3% | 73.7% | 8 | +0.38% | +21.5% | +2.68R | -1.00R | +9.40R | -2.52R | 3.4% | +0.15R | +8.4R |

R per trade from the close through day 5. This is the fixed 1R-risk view.

| Stop | EOD | +1d | +2d | +3d | +4d | +5d |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| **0.25%** (best R, tightest near top) | +1.04R | +2.01R | +1.75R | +1.85R | +1.61R | +2.18R |
| 20 RMA | +0.85R | +1.94R | +1.92R | +1.78R | +1.35R | +1.87R |
| RMA - 0.1 ATR | +0.56R | +0.98R | +1.20R | +1.50R | +1.17R | +0.82R |
| 10:30 bar | +1.54R | +2.48R | +1.35R | +1.44R | +1.12R | +1.05R |
| 0.50% | +0.71R | +1.40R | +1.03R | +1.15R | +0.94R | +1.17R |
| Last 2 bars | +1.19R | +1.97R | +1.01R | +1.06R | +0.71R | +0.75R |
| 0.10x daily ATR | +0.51R | +1.08R | +0.85R | +1.05R | +0.83R | +1.01R |
| Last 3 bars | +0.98R | +1.67R | +0.91R | +0.98R | +0.67R | +0.76R |
| 15-min low | +0.98R | +1.67R | +0.91R | +0.98R | +0.67R | +0.76R |
| Low since cross | +0.57R | +0.90R | +0.74R | +0.85R | +0.87R | +1.12R |
| Low of day | +0.57R | +0.90R | +0.74R | +0.85R | +0.87R | +1.12R |
| 0.75% | +0.33R | +0.72R | +0.47R | +0.60R | +0.45R | +0.66R |
| 1x 5-min ATR | +0.39R | +0.85R | +0.51R | +0.59R | +0.42R | +0.55R |
| 0.20x daily ATR | +0.16R | +0.61R | +0.39R | +0.56R | +0.55R | +0.74R |
| 0.15x daily ATR | +0.33R | +0.71R | +0.42R | +0.55R | +0.38R | +0.56R |
| 30-min low | +0.90R | +1.18R | +0.56R | +0.50R | +0.38R | +0.76R |
| 1.5x 5-min ATR | +0.21R | +0.49R | +0.25R | +0.44R | +0.38R | +0.50R |
| 1.50% | +0.29R | +0.59R | +0.30R | +0.35R | +0.48R | +0.60R |
| 2x 5-min ATR | +0.29R | +0.56R | +0.29R | +0.31R | +0.34R | +0.49R |
| 0.25x daily ATR | +0.16R | +0.45R | +0.23R | +0.29R | +0.31R | +0.40R |
| 1.00% | +0.25R | +0.39R | +0.17R | +0.27R | +0.15R | +0.31R |
| 3x 5-min ATR | +0.17R | +0.32R | +0.20R | +0.20R | +0.23R | +0.29R |
| 0.50x daily ATR | +0.18R | +0.28R | +0.19R | +0.19R | +0.26R | +0.21R |
| 0.33x daily ATR | +0.20R | +0.36R | +0.16R | +0.17R | +0.24R | +0.32R |

Average percent from the close through day 5. This is the same position size on every fill.

| Stop | EOD | +1d | +2d | +3d | +4d | +5d |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| **0.25%** (best R, tightest near top) | +0.26% | +0.50% | +0.44% | +0.46% | +0.40% | +0.54% |
| 20 RMA | +0.49% | +0.56% | +0.26% | +0.12% | -0.14% | +0.11% |
| RMA - 0.1 ATR | +0.46% | +0.44% | +0.34% | +0.26% | -0.02% | +0.13% |
| 10:30 bar | +0.37% | +0.73% | +0.52% | +0.54% | +0.48% | +0.60% |
| 0.50% | +0.36% | +0.70% | +0.51% | +0.58% | +0.47% | +0.59% |
| Last 2 bars | +0.34% | +0.61% | +0.36% | +0.38% | +0.28% | +0.40% |
| 0.10x daily ATR | +0.33% | +0.61% | +0.46% | +0.56% | +0.45% | +0.57% |
| Last 3 bars | +0.30% | +0.50% | +0.26% | +0.28% | +0.17% | +0.29% |
| 15-min low | +0.30% | +0.50% | +0.26% | +0.28% | +0.17% | +0.29% |
| Low since cross | +0.59% | +0.93% | +0.63% | +0.74% | +0.61% | +0.71% |
| Low of day | +0.59% | +0.93% | +0.63% | +0.74% | +0.61% | +0.71% |
| 0.75% | +0.25% | +0.54% | +0.35% | +0.45% | +0.34% | +0.49% |
| 1x 5-min ATR | +0.28% | +0.56% | +0.36% | +0.43% | +0.31% | +0.43% |
| 0.20x daily ATR | +0.29% | +0.78% | +0.51% | +0.67% | +0.72% | +0.95% |
| 0.15x daily ATR | +0.37% | +0.60% | +0.32% | +0.42% | +0.31% | +0.46% |
| 30-min low | +0.42% | +0.49% | +0.10% | +0.11% | 0.00% | +0.18% |
| 1.5x 5-min ATR | +0.30% | +0.51% | +0.27% | +0.48% | +0.44% | +0.59% |
| 1.50% | +0.43% | +0.89% | +0.44% | +0.53% | +0.72% | +0.89% |
| 2x 5-min ATR | +0.48% | +0.81% | +0.49% | +0.50% | +0.56% | +0.81% |
| 0.25x daily ATR | +0.31% | +0.71% | +0.39% | +0.47% | +0.54% | +0.71% |
| 1.00% | +0.25% | +0.39% | +0.17% | +0.27% | +0.15% | +0.31% |
| 3x 5-min ATR | +0.40% | +0.79% | +0.67% | +0.76% | +0.74% | +0.94% |
| 0.50x daily ATR | +0.55% | +0.86% | +0.68% | +0.69% | +0.84% | +0.75% |
| 0.33x daily ATR | +0.42% | +0.70% | +0.33% | +0.38% | +0.50% | +0.68% |

R per trade with 0.05% slippage on stop exits.

| Stop | EOD | +1d | +2d | +3d | +4d | +5d |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| **0.25%** (best R, tightest near top) | +0.88R | +1.84R | +1.58R | +1.67R | +1.43R | +2.00R |
| 20 RMA | +0.77R | +1.86R | +1.83R | +1.68R | +1.25R | +1.77R |
| RMA - 0.1 ATR | +0.51R | +0.93R | +1.14R | +1.44R | +1.11R | +0.75R |
| 10:30 bar | +1.12R | +2.06R | +0.91R | +1.00R | +0.68R | +0.61R |
| 0.50% | +0.64R | +1.33R | +0.94R | +1.07R | +0.85R | +1.08R |
| Last 2 bars | +0.95R | +1.71R | +0.75R | +0.79R | +0.44R | +0.48R |
| 0.10x daily ATR | +0.44R | +1.00R | +0.77R | +0.96R | +0.74R | +0.92R |
| Last 3 bars | +0.79R | +1.47R | +0.69R | +0.77R | +0.46R | +0.54R |
| 15-min low | +0.79R | +1.47R | +0.69R | +0.77R | +0.46R | +0.54R |
| Low since cross | +0.56R | +0.88R | +0.71R | +0.82R | +0.84R | +1.08R |
| Low of day | +0.56R | +0.88R | +0.71R | +0.82R | +0.84R | +1.08R |
| 0.75% | +0.29R | +0.67R | +0.41R | +0.55R | +0.39R | +0.60R |
| 1x 5-min ATR | +0.34R | +0.78R | +0.44R | +0.52R | +0.34R | +0.48R |
| 0.20x daily ATR | +0.13R | +0.58R | +0.35R | +0.51R | +0.51R | +0.69R |
| 0.15x daily ATR | +0.29R | +0.66R | +0.37R | +0.49R | +0.32R | +0.50R |
| 30-min low | +0.78R | +1.05R | +0.42R | +0.36R | +0.23R | +0.61R |
| 1.5x 5-min ATR | +0.18R | +0.45R | +0.20R | +0.39R | +0.33R | +0.46R |
| 1.50% | +0.28R | +0.57R | +0.27R | +0.33R | +0.45R | +0.57R |
| 2x 5-min ATR | +0.27R | +0.54R | +0.26R | +0.28R | +0.30R | +0.45R |
| 0.25x daily ATR | +0.14R | +0.42R | +0.20R | +0.26R | +0.28R | +0.37R |
| 1.00% | +0.22R | +0.36R | +0.13R | +0.23R | +0.11R | +0.27R |
| 3x 5-min ATR | +0.16R | +0.31R | +0.19R | +0.18R | +0.21R | +0.27R |
| 0.50x daily ATR | +0.18R | +0.28R | +0.18R | +0.17R | +0.25R | +0.20R |
| 0.33x daily ATR | +0.19R | +0.35R | +0.14R | +0.15R | +0.22R | +0.29R |


### First 2

**10:30 bar** is the best day-3 R per trade on First 2 at +1.51R (113 fills, total +170.2R). Low of day is +0.68R per trade, total +79.4R. The same stop also leads on total R. That stop is the tightest within 0.05R of the best. Its average stop is 0.26%. With 0.05% slippage on the stop exit it is +1.01R per trade (total +114.1R).

| Stop | Stop % | Skipped | Fills | R/trade | Total R | Win | Stop | Gaps | Avg % | Total % | MFE | Median R | Best | Worst | 30m | Slip R | Slip total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **10:30 bar** (best R, tightest near top) | 0.26% | 5 | 113 | +1.51R | +170.2R | 6.2% | 93.8% | 8 | +0.25% | +28.2% | +6.70R | -1.00R | +80.93R | -9.69R | 71.7% | +1.01R | +114.1R |
| Last 2 bars | 0.43% | 2 | 116 | +1.42R | +164.9R | 7.8% | 92.2% | 11 | +0.13% | +15.0% | +6.59R | -1.00R | +80.93R | -14.60R | 60.3% | +1.07R | +124.2R |
| Last 3 bars | 0.53% | 1 | 117 | +1.41R | +164.5R | 7.7% | 92.3% | 11 | +0.03% | +3.6% | +6.33R | -1.00R | +80.93R | -14.60R | 53.8% | +1.18R | +138.1R |
| 15-min low | 0.53% | 1 | 117 | +1.41R | +164.5R | 7.7% | 92.3% | 11 | +0.03% | +3.6% | +6.33R | -1.00R | +80.93R | -14.60R | 53.8% | +1.18R | +138.1R |
| RMA - 0.1 ATR | 1.76% | 15 | 101 | +1.39R | +140.7R | 22.8% | 74.3% | 13 | -0.03% | -2.9% | +4.36R | -1.00R | +63.12R | -2.60R | 12.6% | +1.34R | +135.3R |
| 30-min low | 0.78% | 1 | 117 | +1.21R | +141.1R | 10.3% | 89.7% | 12 | -0.17% | -19.6% | +5.91R | -1.00R | +80.93R | -8.23R | 36.8% | +1.05R | +123.3R |
| 0.25% | 0.25% | 0 | 118 | +0.93R | +109.9R | 6.8% | 93.2% | 6 | +0.23% | +27.5% | +5.51R | -1.00R | +63.19R | -11.06R | 72.0% | +0.75R | +88.0R |
| Low since cross | 2.05% | 0 | 116 | +0.71R | +82.0R | 25.9% | 71.5% | 13 | +0.28% | +32.1% | +3.45R | -1.00R | +22.74R | -3.00R | 11.9% | +0.65R | +74.9R |
| Low of day | 2.08% | 0 | 116 | +0.68R | +79.4R | 25.9% | 71.5% | 13 | +0.26% | +29.8% | +3.42R | -1.00R | +22.74R | -3.00R | 11.9% | +0.62R | +72.2R |
| 0.50% | 0.50% | 0 | 118 | +0.59R | +70.2R | 10.2% | 89.8% | 7 | +0.30% | +35.1% | +4.33R | -1.00R | +33.78R | -5.53R | 44.9% | +0.51R | +59.6R |
| 20 RMA | 1.46% | 28 | 88 | +0.55R | +48.3R | 13.6% | 84.1% | 10 | -0.51% | -45.1% | +3.50R | -1.00R | +59.67R | -5.09R | 22.2% | +0.46R | +40.1R |
| 0.10x daily ATR | 0.52% | 0 | 118 | +0.54R | +63.9R | 10.2% | 89.8% | 8 | +0.27% | +32.3% | +3.92R | -1.00R | +31.04R | -5.69R | 50.8% | +0.45R | +52.8R |
| 0.20x daily ATR | 1.04% | 0 | 118 | +0.28R | +32.5R | 16.1% | 83.9% | 10 | +0.38% | +44.6% | +3.01R | -1.00R | +15.52R | -4.26R | 19.5% | +0.23R | +27.3R |
| 0.75% | 0.75% | 0 | 118 | +0.23R | +26.8R | 12.7% | 87.3% | 12 | +0.17% | +20.1% | +3.31R | -1.00R | +22.52R | -3.69R | 33.9% | +0.17R | +20.0R |
| 0.15x daily ATR | 0.78% | 0 | 118 | +0.18R | +20.8R | 12.7% | 87.3% | 12 | +0.12% | +14.0% | +3.21R | -1.00R | +20.69R | -5.68R | 35.6% | +0.12R | +13.6R |
| 1x 5-min ATR | 0.67% | 0 | 118 | +0.12R | +14.7R | 10.2% | 89.8% | 11 | +0.10% | +11.7% | +3.46R | -1.00R | +23.38R | -5.74R | 42.4% | +0.05R | +5.6R |
| 0.25x daily ATR | 1.30% | 0 | 118 | +0.06R | +6.6R | 17.8% | 82.2% | 16 | +0.17% | +20.4% | +2.70R | -1.00R | +12.41R | -3.41R | 11.9% | +0.02R | +2.5R |
| 1.5x 5-min ATR | 1.00% | 0 | 116 | +0.04R | +4.7R | 13.8% | 86.2% | 12 | +0.05% | +6.2% | +2.88R | -1.00R | +15.58R | -3.83R | 20.3% | -0.01R | -1.0R |
| 1.50% | 1.50% | 0 | 114 | +0.01R | +1.4R | 20.2% | 79.0% | 14 | +0.02% | +2.0% | +2.46R | -1.00R | +11.26R | -3.65R | 3.4% | -0.01R | -1.6R |
| 1.00% | 1.00% | 0 | 116 | +0.01R | +1.1R | 13.8% | 86.2% | 12 | +0.01% | +1.1% | +2.72R | -1.00R | +16.89R | -5.48R | 21.2% | -0.03R | -3.9R |
| 3x 5-min ATR | 2.00% | 0 | 112 | -0.02R | -2.2R | 24.1% | 75.0% | 17 | +0.10% | +11.5% | +2.12R | -1.00R | +9.62R | -2.47R | 0.9% | -0.04R | -4.6R |
| 0.50x daily ATR | 2.60% | 0 | 112 | -0.03R | -3.1R | 33.0% | 66.1% | 16 | +0.08% | +8.8% | +1.74R | -1.00R | +6.21R | -2.07R | 0.9% | -0.04R | -4.7R |
| 0.33x daily ATR | 1.71% | 0 | 114 | -0.05R | -6.1R | 21.9% | 78.1% | 17 | 0.00% | +0.5% | +2.23R | -1.00R | +9.40R | -2.58R | 4.2% | -0.08R | -9.0R |
| 2x 5-min ATR | 1.33% | 0 | 114 | -0.06R | -6.7R | 17.5% | 82.5% | 19 | -0.05% | -5.3% | +2.58R | -1.00R | +11.69R | -3.23R | 9.3% | -0.09R | -10.7R |

R per trade from the close through day 5. This is the fixed 1R-risk view.

| Stop | EOD | +1d | +2d | +3d | +4d | +5d |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| **10:30 bar** (best R, tightest near top) | +0.98R | +1.73R | +1.31R | +1.51R | +1.09R | +2.08R |
| Last 2 bars | +0.86R | +1.68R | +1.30R | +1.42R | +1.01R | +2.14R |
| Last 3 bars | +0.76R | +1.56R | +1.27R | +1.41R | +1.01R | +2.15R |
| 15-min low | +0.76R | +1.56R | +1.27R | +1.41R | +1.01R | +2.15R |
| RMA - 0.1 ATR | +0.51R | +0.83R | +1.14R | +1.39R | +1.21R | +1.50R |
| 30-min low | +0.81R | +1.33R | +1.23R | +1.21R | +1.08R | +2.37R |
| 0.25% | +0.45R | +1.16R | +0.96R | +0.93R | +0.87R | +1.49R |
| Low since cross | +0.24R | +0.51R | +0.56R | +0.71R | +0.71R | +0.64R |
| Low of day | +0.24R | +0.50R | +0.54R | +0.68R | +0.69R | +0.61R |
| 0.50% | +0.20R | +0.63R | +0.48R | +0.59R | +0.49R | +0.49R |
| 20 RMA | +0.18R | +0.69R | +0.66R | +0.55R | +0.33R | +0.55R |
| 0.10x daily ATR | +0.10R | +0.45R | +0.39R | +0.54R | +0.43R | +0.43R |
| 0.20x daily ATR | -0.06R | +0.21R | +0.12R | +0.28R | +0.31R | +0.31R |
| 0.75% | +0.04R | +0.31R | +0.15R | +0.23R | +0.15R | +0.14R |
| 0.15x daily ATR | +0.02R | +0.22R | +0.10R | +0.18R | +0.09R | +0.09R |
| 1x 5-min ATR | +0.03R | +0.24R | +0.10R | +0.12R | +0.10R | +0.15R |
| 0.25x daily ATR | +0.01R | +0.08R | -0.03R | +0.06R | +0.09R | +0.05R |
| 1.5x 5-min ATR | -0.03R | +0.08R | -0.03R | +0.04R | +0.05R | +0.07R |
| 1.50% | +0.09R | +0.16R | 0.00R | +0.01R | +0.08R | +0.04R |
| 1.00% | +0.06R | +0.06R | -0.05R | +0.01R | -0.05R | -0.07R |
| 3x 5-min ATR | +0.03R | +0.06R | -0.06R | -0.02R | +0.05R | +0.03R |
| 0.50x daily ATR | +0.02R | +0.03R | -0.05R | -0.03R | +0.05R | -0.03R |
| 0.33x daily ATR | +0.06R | +0.03R | -0.09R | -0.05R | +0.01R | -0.03R |
| 2x 5-min ATR | +0.03R | +0.09R | -0.04R | -0.06R | -0.02R | +0.01R |

Average percent from the close through day 5. This is the same position size on every fill.

| Stop | EOD | +1d | +2d | +3d | +4d | +5d |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| **10:30 bar** (best R, tightest near top) | +0.15% | +0.33% | +0.22% | +0.25% | +0.20% | +0.34% |
| Last 2 bars | +0.08% | +0.26% | +0.12% | +0.13% | +0.06% | +0.24% |
| Last 3 bars | +0.02% | +0.16% | +0.02% | +0.03% | -0.04% | +0.14% |
| 15-min low | +0.02% | +0.16% | +0.02% | +0.03% | -0.04% | +0.14% |
| RMA - 0.1 ATR | +0.12% | -0.03% | -0.03% | -0.03% | -0.05% | +0.08% |
| 30-min low | +0.09% | +0.08% | -0.15% | -0.17% | -0.21% | +0.01% |
| 0.25% | +0.11% | +0.29% | +0.24% | +0.23% | +0.22% | +0.37% |
| Low since cross | +0.12% | +0.18% | +0.17% | +0.28% | +0.30% | +0.24% |
| Low of day | +0.12% | +0.16% | +0.15% | +0.26% | +0.28% | +0.22% |
| 0.50% | +0.10% | +0.32% | +0.24% | +0.30% | +0.25% | +0.25% |
| 20 RMA | +0.04% | -0.14% | -0.38% | -0.51% | -0.62% | -0.59% |
| 0.10x daily ATR | +0.09% | +0.27% | +0.20% | +0.27% | +0.22% | +0.22% |
| 0.20x daily ATR | 0.00% | +0.33% | +0.18% | +0.38% | +0.46% | +0.48% |
| 0.75% | +0.03% | +0.23% | +0.11% | +0.17% | +0.11% | +0.11% |
| 0.15x daily ATR | +0.07% | +0.20% | +0.07% | +0.12% | +0.06% | +0.06% |
| 1x 5-min ATR | +0.04% | +0.15% | +0.05% | +0.10% | +0.05% | +0.05% |
| 0.25x daily ATR | +0.07% | +0.21% | +0.03% | +0.17% | +0.26% | +0.23% |
| 1.5x 5-min ATR | +0.02% | +0.07% | -0.05% | +0.05% | +0.03% | +0.02% |
| 1.50% | +0.13% | +0.25% | 0.00% | +0.02% | +0.12% | +0.06% |
| 1.00% | +0.06% | +0.06% | -0.05% | +0.01% | -0.05% | -0.07% |
| 3x 5-min ATR | +0.13% | +0.14% | -0.04% | +0.10% | +0.16% | +0.11% |
| 0.50x daily ATR | +0.08% | +0.16% | -0.02% | +0.08% | +0.28% | +0.09% |
| 0.33x daily ATR | +0.12% | +0.13% | -0.10% | 0.00% | +0.14% | +0.08% |
| 2x 5-min ATR | +0.10% | +0.12% | -0.04% | -0.05% | -0.02% | 0.00% |

R per trade with 0.05% slippage on stop exits.

| Stop | EOD | +1d | +2d | +3d | +4d | +5d |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| **10:30 bar** (best R, tightest near top) | +0.50R | +1.24R | +0.82R | +1.01R | +0.59R | +1.58R |
| Last 2 bars | +0.53R | +1.34R | +0.96R | +1.07R | +0.66R | +1.78R |
| Last 3 bars | +0.55R | +1.34R | +1.05R | +1.18R | +0.79R | +1.93R |
| 15-min low | +0.55R | +1.34R | +1.05R | +1.18R | +0.79R | +1.93R |
| RMA - 0.1 ATR | +0.47R | +0.78R | +1.09R | +1.34R | +1.16R | +1.44R |
| 30-min low | +0.67R | +1.19R | +1.08R | +1.05R | +0.92R | +2.22R |
| 0.25% | +0.28R | +0.98R | +0.78R | +0.75R | +0.69R | +1.30R |
| Low since cross | +0.19R | +0.46R | +0.50R | +0.65R | +0.65R | +0.58R |
| Low of day | +0.19R | +0.45R | +0.48R | +0.62R | +0.63R | +0.55R |
| 0.50% | +0.12R | +0.55R | +0.40R | +0.51R | +0.40R | +0.40R |
| 20 RMA | +0.10R | +0.60R | +0.57R | +0.46R | +0.24R | +0.45R |
| 0.10x daily ATR | +0.02R | +0.36R | +0.30R | +0.45R | +0.34R | +0.33R |
| 0.20x daily ATR | -0.10R | +0.17R | +0.07R | +0.23R | +0.26R | +0.26R |
| 0.75% | -0.01R | +0.25R | +0.10R | +0.17R | +0.09R | +0.08R |
| 0.15x daily ATR | -0.03R | +0.17R | +0.04R | +0.12R | +0.03R | +0.02R |
| 1x 5-min ATR | -0.04R | +0.17R | +0.02R | +0.05R | +0.02R | +0.07R |
| 0.25x daily ATR | -0.01R | +0.05R | -0.06R | +0.02R | +0.05R | +0.02R |
| 1.5x 5-min ATR | -0.07R | +0.04R | -0.07R | -0.01R | 0.00R | +0.02R |
| 1.50% | +0.08R | +0.14R | -0.02R | -0.01R | +0.05R | +0.02R |
| 1.00% | +0.03R | +0.03R | -0.09R | -0.03R | -0.09R | -0.11R |
| 3x 5-min ATR | +0.02R | +0.04R | -0.08R | -0.04R | +0.03R | 0.00R |
| 0.50x daily ATR | +0.02R | +0.02R | -0.06R | -0.04R | +0.03R | -0.04R |
| 0.33x daily ATR | +0.05R | +0.01R | -0.11R | -0.08R | -0.01R | -0.06R |
| 2x 5-min ATR | +0.01R | +0.06R | -0.07R | -0.09R | -0.05R | -0.02R |


### One 10:30 rank-tie morning

**2026-08-27**, **TEAM** (Atlassian Corporation), prior-close leader rank 1. Day 3 on the low-of-day stop is +0.38R. The rank-tie first book averages +0.85R by day 3. This is the winner closest to that average. The best fill in that book is +21.56R on 2026-07-31 (CRWD), and this morning is not that one.

The first 5-minute bar of the session to close above the 20 RMA ended at 9:35. That close was $177.38 and the RMA was $168.91.
5 names crossed on the bar ending 9:35. TEAM is first among them because leader rank 1 is the best on that bar. The others on that bar: CRL rank 4, CRWD rank 6, VEEV rank 9, IQV rank 10.
The symbol tie-break would have bought CRL first. This fill is the rank-tie book, the +0.85R study.

The entry is the 10:30 close, $181.99. The low-of-day stop is $168.73, 7.29% under the entry, so 1R is $13.26.

The low-of-day stop was not hit through the day-5 close.

The close columns are the session close against the entry, with no stop. The booked columns are what this stop keeps.

| | Date | Close | Close % | Close R | Booked % | Booked R |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| EOD | 2026-08-27 | $185.62 | +1.99% | +0.27R | +1.99% | +0.27R |
| +1d | 2026-08-28 | $190.41 | +4.63% | +0.64R | +4.63% | +0.64R |
| +2d | 2026-08-31 | $194.17 | +6.69% | +0.92R | +6.69% | +0.92R |
| +3d | 2026-09-01 | $187.03 | +2.77% | +0.38R | +2.77% | +0.38R |
| +4d | 2026-09-02 | $186.44 | +2.45% | +0.34R | +2.45% | +0.34R |
| +5d | 2026-09-03 | $194.68 | +6.97% | +0.96R | +6.97% | +0.96R |

The tightest stop near the top of the First book is **0.25%**. On this trade that stop is $181.53, 0.25% under the entry, so 1R is $0.46. Day 3 books -1.00R and -0.25%. It was inside the first 30 minutes after entry. That stop was hit on the entry session (2026-08-27), the 5-minute bar ending 10:35. The bar traded down to the stop (open $181.80, low $181.26).

The close columns are the session close against the entry, with no stop. The booked columns are what this stop keeps.

| | Date | Close | Close % | Close R | Booked % | Booked R |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| EOD | 2026-08-27 | $185.62 | +1.99% | +7.98R | -0.25% | -1.00R |
| +1d | 2026-08-28 | $190.41 | +4.63% | +18.52R | -0.25% | -1.00R |
| +2d | 2026-08-31 | $194.17 | +6.69% | +26.77R | -0.25% | -1.00R |
| +3d | 2026-09-01 | $187.03 | +2.77% | +11.08R | -0.25% | -1.00R |
| +4d | 2026-09-02 | $186.44 | +2.45% | +9.78R | -0.25% | -1.00R |
| +5d | 2026-09-03 | $194.68 | +6.97% | +27.89R | -0.25% | -1.00R |

## 5-minute Strat pullback

A top-10 leader qualifies when a 5-minute bar closes above the 20 RMA. After that, the next trade waits for a pullback, a 2D or an inside bar, and buys the first trade above that bar's high. The patterns are 2d-2u, 2d-1-2u, 3-1-2u, 1-2d-2u, and 1-2u. A bar that opens above the prior high fills at the open. The earliest fill is 9:45. One book stops taking new fills at 11:00 and one at 10:30. The stop is the low from 9:30 through the entry bar. One R is that distance. First, first 2, and first 3 are the best leader-list ranks among the names that filled, rank 1 ahead of rank 2. The columns beside them are the 10:30 rank-tie books, bought at the 10:30 close.

The name has to close above the 20 RMA first. The pullback is a later 5-minute bar that is a 2D or an inside, and the buy is the first trade above that bar's high. A 2U straight after a 3 is not a pullback. A bar that opens above the prior high fills at the open, and that fill is known at the bar's start, so the bar that ends five minutes after the cutoff can still fill at its open. A through-trade is known at the bar's end. The earliest fill is 9:45. One trade per name per day. The stop is the low from 9:30 through the entry bar, including that bar's low. The entry bar is not a stop. A later bar at or below the stop exits at the stop. A bar that opens below the stop exits at the open.

First, first 2, and first 3 are the best leader-list ranks among the names that actually filled. Rank 1 is the best prior-close score. A name that never triggers does not take a slot. The columns beside them are the 10:30 rank-tie books, bought at the 10:30 close with the same low-of-day stop. Risk per share is the entry minus that stop. The entry comparison is the 10:30 price minus this fill, as a percent of the 10:30 price, averaged over the names that have both fills. Positive means the pullback fill was lower.

**10:30 pullback, first** is the best of these pullback books by day 3 at -0.16R per morning (n = 59 mornings / 59 fills). The 10:30 rank-tie first book is +0.85R by day 3, and its first 2 is +0.68R. On the mornings both have a day-3 result, this book is -1.00R versus the rank-tie first book.


### Pullback, in by 11:00

**First** enters at 10:06 on average (median 10:00) with an average stop 2.33% under the entry, $5.38 of risk per share against $5.45 at the 10:30 entry (-0.12% versus that price, positive means a lower fill, n = 58); **First 2** enters at 10:05 on average (median 10:00) with an average stop 2.19% under the entry, $5.21 of risk per share against $5.36 at the 10:30 entry (0.00% versus that price, positive means a lower fill, n = 117); **First 3** enters at 10:05 on average (median 10:00) with an average stop 2.00% under the entry, $4.74 of risk per share against $4.90 at the 10:30 entry (-0.04% versus that price, positive means a lower fill, n = 175); **All** enters at 10:04 on average (median 10:00) with an average stop 1.85% under the entry, $4.56 of risk per share against $4.68 at the 10:30 entry (-0.08% versus that price, positive means a lower fill, n = 451).

Day 3, side by side. Average % and average R give each morning one vote. R per trade, win, stop, total R, MFE, and best and worst are per fill.

| | First | 10:30 first | First 2 | 10:30 first 2 | First 3 | 10:30 first 3 | All | 10:30 all |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Day 3 days | 59 | 58 | 58 | 58 | 58 | 58 | 57 | 57 |
| Day 3 fills | 59 | 58 | 116 | 116 | 174 | 174 | 443 | 438 |
| Day 3 avg % | +0.08% | +0.74% | -0.25% | +0.26% | -0.33% | +0.22% | -0.12% | -0.08% |
| Day 3 avg R | -0.22R | +0.85R | -0.22R | +0.68R | -0.28R | +0.51R | -0.22R | -0.01R |
| Day 3 win | 25.4% | 29.3% | 22.4% | 25.9% | 23.6% | 25.9% | 21.4% | 23.3% |
| Day 3 stop | 71.2% | 69.0% | 74.1% | 71.5% | 74.1% | 70.1% | 75.2% | 73.3% |
| Day 3 total R | -12.9R | +49.2R | -26.0R | +79.4R | -49.2R | +88.6R | -111.8R | -21.1R |
| Day 3 R per trade | -0.22R | +0.85R | -0.22R | +0.68R | -0.28R | +0.51R | -0.25R | -0.05R |
| Day 3 avg MFE | +1.88R | +3.89R | +1.95R | +3.42R | +1.94R | +3.31R | +1.90R | +2.45R |
| Day 3 best R | +7.44R | +21.56R | +10.50R | +22.74R | +10.50R | +22.74R | +11.48R | +22.74R |
| Day 3 worst R | -2.93R | -2.52R | -2.93R | -3.00R | -6.01R | -4.71R | -6.01R | -8.06R |
| Day 3 vs 10:30 first | -1.05R | — | -1.07R | — | -1.13R | — | -1.10R | — |
| Day 3 vs 10:30 first 2 | -0.89R | — | -0.91R | — | -0.97R | — | -0.94R | — |

Average R from the close through day 5:

- **First** R: -0.08R, -0.03R, -0.11R, -0.22R, -0.25R, -0.18R.
- **10:30 first** R: +0.57R, +0.90R, +0.74R, +0.85R, +0.87R, +1.12R.
- **First 2** R: -0.05R, -0.02R, -0.13R, -0.22R, -0.27R, -0.18R.
- **10:30 first 2** R: +0.24R, +0.50R, +0.54R, +0.68R, +0.69R, +0.61R.
- **First 3** R: -0.06R, -0.04R, -0.17R, -0.28R, -0.47R, -0.49R.
- **10:30 first 3** R: +0.17R, +0.33R, +0.41R, +0.51R, +0.33R, +0.33R.
- **All** R: -0.07R, -0.08R, -0.18R, -0.22R, -0.30R, -0.30R.
- **10:30 all** R: +0.04R, +0.03R, +0.01R, -0.01R, -0.11R, -0.15R.

Average percent from the close through day 5:

- **First** %: -0.02%, +0.18%, +0.27%, +0.08%, -0.15%, -0.06%.
- **10:30 first** %: +0.59%, +0.93%, +0.63%, +0.74%, +0.61%, +0.71%.
- **First 2** %: -0.04%, -0.01%, -0.09%, -0.25%, -0.34%, -0.29%.
- **10:30 first 2** %: +0.12%, +0.16%, +0.15%, +0.26%, +0.28%, +0.22%.
- **First 3** %: 0.00%, +0.07%, -0.05%, -0.33%, -0.59%, -0.68%.
- **10:30 first 3** %: +0.16%, +0.18%, +0.13%, +0.22%, +0.10%, +0.11%.
- **All** %: +0.03%, 0.00%, -0.06%, -0.12%, -0.21%, -0.21%.
- **10:30 all** %: +0.11%, +0.03%, -0.01%, -0.08%, -0.18%, -0.18%.

### Pullback, in by 10:30

**First** enters at 10:00 with an average stop 2.13% under the entry, $4.41 of risk per share against $4.43 at the 10:30 entry (-0.11% versus that price, positive means a lower fill, n = 59); **First 2** enters at 10:00 with an average stop 2.10% under the entry, $4.77 of risk per share against $4.86 at the 10:30 entry (-0.03% versus that price, positive means a lower fill, n = 118); **First 3** enters at 10:00 with an average stop 1.89% under the entry, $4.48 of risk per share against $4.61 at the 10:30 entry (-0.06% versus that price, positive means a lower fill, n = 177); **All** enters at 10:00 with an average stop 1.81% under the entry, $4.44 of risk per share against $4.57 at the 10:30 entry (-0.09% versus that price, positive means a lower fill, n = 418).

Day 3, side by side. Average % and average R give each morning one vote. R per trade, win, stop, total R, MFE, and best and worst are per fill.

| | First | 10:30 first | First 2 | 10:30 first 2 | First 3 | 10:30 first 3 | All | 10:30 all |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Day 3 days | 59 | 58 | 58 | 58 | 58 | 58 | 57 | 57 |
| Day 3 fills | 59 | 58 | 116 | 116 | 174 | 174 | 407 | 438 |
| Day 3 avg % | +0.16% | +0.74% | -0.27% | +0.26% | -0.55% | +0.22% | -0.26% | -0.08% |
| Day 3 avg R | -0.16R | +0.85R | -0.30R | +0.68R | -0.45R | +0.51R | -0.31R | -0.01R |
| Day 3 win | 27.1% | 29.3% | 21.6% | 25.9% | 20.7% | 25.9% | 20.2% | 23.3% |
| Day 3 stop | 72.9% | 69.0% | 76.7% | 71.5% | 78.2% | 70.1% | 76.7% | 73.3% |
| Day 3 total R | -9.7R | +49.2R | -34.8R | +79.4R | -78.7R | +88.6R | -126.2R | -21.1R |
| Day 3 R per trade | -0.16R | +0.85R | -0.30R | +0.68R | -0.45R | +0.51R | -0.31R | -0.05R |
| Day 3 avg MFE | +2.21R | +3.89R | +1.84R | +3.42R | +1.73R | +3.31R | +1.85R | +2.45R |
| Day 3 best R | +7.44R | +21.56R | +7.44R | +22.74R | +7.44R | +22.74R | +11.48R | +22.74R |
| Day 3 worst R | -2.93R | -2.52R | -2.93R | -3.00R | -6.01R | -4.71R | -6.01R | -8.06R |
| Day 3 vs 10:30 first | -1.00R | — | -1.15R | — | -1.30R | — | -1.19R | — |
| Day 3 vs 10:30 first 2 | -0.83R | — | -0.98R | — | -1.14R | — | -1.02R | — |

Average R from the close through day 5:

- **First** R: -0.03R, +0.13R, -0.03R, -0.16R, -0.20R, -0.07R.
- **10:30 first** R: +0.57R, +0.90R, +0.74R, +0.85R, +0.87R, +1.12R.
- **First 2** R: -0.04R, -0.07R, -0.22R, -0.30R, -0.36R, -0.30R.
- **10:30 first 2** R: +0.24R, +0.50R, +0.54R, +0.68R, +0.69R, +0.61R.
- **First 3** R: -0.09R, -0.17R, -0.36R, -0.45R, -0.52R, -0.58R.
- **10:30 first 3** R: +0.17R, +0.33R, +0.41R, +0.51R, +0.33R, +0.33R.
- **All** R: -0.08R, -0.13R, -0.29R, -0.31R, -0.34R, -0.34R.
- **10:30 all** R: +0.04R, +0.03R, +0.01R, -0.01R, -0.11R, -0.15R.

Average percent from the close through day 5:

- **First** %: 0.00%, +0.45%, +0.39%, +0.16%, -0.05%, +0.16%.
- **10:30 first** %: +0.59%, +0.93%, +0.63%, +0.74%, +0.61%, +0.71%.
- **First 2** %: +0.02%, +0.02%, -0.12%, -0.27%, -0.42%, -0.38%.
- **10:30 first 2** %: +0.12%, +0.16%, +0.15%, +0.26%, +0.28%, +0.22%.
- **First 3** %: -0.04%, -0.07%, -0.30%, -0.55%, -0.68%, -0.84%.
- **10:30 first 3** %: +0.16%, +0.18%, +0.13%, +0.22%, +0.10%, +0.11%.
- **All** %: +0.03%, -0.06%, -0.21%, -0.26%, -0.32%, -0.37%.
- **10:30 all** %: +0.11%, +0.03%, -0.01%, -0.08%, -0.18%, -0.18%.

### CRWD on 2026-10-09, the 5-minute pullback

**2026-10-09**, **CRWD** (CrowdStrike), prior-close leader rank 7. This is the same morning as the 10:30 first example. The pullback buys the break of the pullback bar instead of waiting for the 10:30 close. Rank 7 is not the first name that day; the example is this trade.

The first 5-minute bar of the session to close above the 20 RMA ended at 9:35. That close was $267.64 and the RMA was $264.30.

The bar before the trigger made a high of $263.78. The trigger bar opened at $263.65 and traded up to $265.96. The open is under that prior high, so the fill is the prior high, $263.78, at 9:55. The pattern is 2d-2u.

That prior high is the price described as about $263.79.

The stop is the low from 9:30 through the entry bar, $262.44. It sits 0.51% under the entry, so 1R is $1.34. A stop this tight turns a small dollar move into a large R until the stop books −1R.

The 10:30 entry on this name is $266.65, with the same stop at $262.44 and 1R of $4.21. This fill is $2.87 lower, +1.08% of the 10:30 price, and risks $1.34 a share instead of $4.21.

The 10:30 cutoff keeps this same trade, because the fill is before 10:30.

The stop was hit on the +1 session (2026-10-12), the 5-minute bar ending 13:15. The bar traded down to the stop (open $263.05, low $262.17) and the exit is $262.44.

The close columns are the session close against this entry, with no stop. The booked columns are what the study keeps: from the stop session on, the exit.

| | Date | Close | Close % | Close R | Booked % | Booked R |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| EOD | 2026-10-09 | $275.04 | +4.27% | +8.40R | +4.27% | +8.40R |
| +1d | 2026-10-12 | $263.01 | -0.29% | -0.57R | -0.51% | -1.00R |
| +2d | 2026-10-13 | $261.21 | -0.97% | -1.92R | -0.51% | -1.00R |
| +3d | 2026-10-14 | $249.29 | -5.49% | -10.81R | -0.51% | -1.00R |
| +4d | 2026-10-15 | $244.57 | -7.28% | -14.34R | -0.51% | -1.00R |
| +5d | 2026-10-16 | $227.39 | -13.80% | -27.16R | -0.51% | -1.00R |

## 5-minute pullback, 10:00 to 10:30

The same pullback, with the fill kept only when its time is from 10:00 through 10:30. A pullback bar can print before 10:00. A trigger before 10:00 is skipped, and the scan keeps looking for the next one inside the window. One trade per name. Time first and time first 2 take the earliest fills. A tie breaks by leader rank, then the symbol. Rank first and rank first 2 take the best leader-list ranks among the names that triggered in the window. The last two columns are the 10:30 rank-tie books, bought at the 10:30 close.

The stop is still the low from 9:30 through the entry bar. One R is that distance. A morning with no trigger in the window counts as zero fills. Time first 2 keeps the two earliest fills. Rank first 2 keeps the two best leader-list ranks. First 1 is the first name of that same list. The 10:30 columns are the rank-tie books, entered at the 10:30 close.

Before the cap, 1 tape morning had no trigger in the window, 0 had one, 0 had two, and 59 had three or more.

**10:00–10:30, first by rank** is the best of these four books by day 3 at +0.03R per morning (n = 59 mornings / 59 fills). The 10:30 rank-tie first book is +0.85R, and its first 2 is +0.68R. Paired, this book is -0.80R versus the rank-tie first book and -0.63R versus first 2.

**Time first** enters at 10:02 on average (median 10:00) with an average stop 1.98% under the entry, $4.63 of risk per share against $4.51 at the 10:30 entry (-0.11% versus that price, n = 59; mornings with 0/1/2 fills: 1/59/0); **Time first 2** enters at 10:03 on average (median 10:00) with an average stop 1.88% under the entry, $4.53 of risk per share against $4.51 at the 10:30 entry (-0.08% versus that price, n = 118; mornings with 0/1/2 fills: 1/0/59); **Rank first** enters at 10:11 on average (median 10:05) with an average stop 2.18% under the entry, $4.49 of risk per share against $4.52 at the 10:30 entry (-0.08% versus that price, n = 59; mornings with 0/1/2 fills: 1/59/0); **Rank first 2** enters at 10:10 on average (median 10:05) with an average stop 2.22% under the entry, $5.09 of risk per share against $4.98 at the 10:30 entry (-0.11% versus that price, n = 118; mornings with 0/1/2 fills: 1/0/59).

| | Time first | Time first 2 | Rank first | Rank first 2 | 10:30 first | 10:30 first 2 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Day 3 days | 58 | 57 | 59 | 58 | 58 | 58 |
| Day 3 fills | 58 | 114 | 59 | 116 | 58 | 116 |
| Day 3 avg % | -0.81% | -0.28% | +0.40% | -0.27% | +0.74% | +0.26% |
| Day 3 avg R | -0.55R | -0.24R | +0.03R | -0.21R | +0.85R | +0.68R |
| Day 3 win | 17.2% | 22.8% | 30.5% | 23.3% | 29.3% | 25.9% |
| Day 3 stop | 81.0% | 75.4% | 69.5% | 75.0% | 69.0% | 71.5% |
| Day 3 gaps | 5 | 12 | 5 | 12 | 8 | 13 |
| Day 3 total R | -32.0R | -26.9R | +1.9R | -23.9R | +49.2R | +79.4R |
| Day 3 R per trade | -0.55R | -0.24R | +0.03R | -0.21R | +0.85R | +0.68R |
| Day 3 avg MFE | +1.59R | +1.83R | +2.34R | +1.88R | +3.89R | +3.42R |
| Day 3 best R | +5.90R | +9.62R | +7.34R | +7.34R | +21.56R | +22.74R |
| Day 3 worst R | -2.83R | -4.83R | -2.83R | -2.83R | -2.52R | -3.00R |
| Day 3 vs 10:30 first | -1.40R | -1.12R | -0.80R | -1.05R | — | — |
| Day 3 vs 10:30 first 2 | -1.24R | -0.95R | -0.63R | -0.89R | — | — |

Average R from the close through day 5:

- **Time first** R: +0.02R, -0.26R, -0.42R, -0.55R, -0.57R, -0.45R.
- **Time first 2** R: -0.03R, -0.09R, -0.15R, -0.24R, -0.34R, -0.30R.
- **Rank first** R: -0.07R, +0.10R, +0.12R, +0.03R, +0.04R, +0.17R.
- **Rank first 2** R: -0.06R, -0.13R, -0.16R, -0.21R, -0.25R, -0.16R.
- **10:30 first** R: +0.57R, +0.90R, +0.74R, +0.85R, +0.87R, +1.12R.
- **10:30 first 2** R: +0.24R, +0.50R, +0.54R, +0.68R, +0.69R, +0.61R.

Average percent from the close through day 5:

- **Time first** %: -0.16%, -0.36%, -0.56%, -0.81%, -0.92%, -0.80%.
- **Time first 2** %: -0.09%, -0.15%, -0.13%, -0.28%, -0.50%, -0.49%.
- **Rank first** %: -0.09%, +0.39%, +0.51%, +0.40%, +0.24%, +0.44%.
- **Rank first 2** %: -0.10%, -0.13%, -0.17%, -0.27%, -0.39%, -0.35%.
- **10:30 first** %: +0.59%, +0.93%, +0.63%, +0.74%, +0.61%, +0.71%.
- **10:30 first 2** %: +0.12%, +0.16%, +0.15%, +0.26%, +0.28%, +0.22%.

### CRWD on 2026-10-09, inside 10:00 to 10:30

Inside the window the fill is $266.88 at 10:10, pattern 1-2u. The stop is $262.44, so 1R is $4.44.

The earlier pullback, outside this window, was $263.78 at 9:55.

The 10:30 close on this name is $266.65, 1R $4.21. This window's fill is -0.09% versus that price and risks $4.44 a share.

## Strat reversal: 15-minute and 30-minute

Bullish reversals are 2d-2u, 2d-1-2u, 3-1-2u, and 1-2d-2u, the same four this repo treats as reversals. 3-2u is not one of them, so it is not used. 15-minute and 30-minute candles are built from the stored 5-minute bars, aligned to 9:30. The opening candle is context only, so the earliest entry is 9:45 on the 15-minute chart and 10:00 on the 30-minute chart. Entry is the first trade above the prior candle's high. A 5-minute bar that opens above that high fills at its open. The stop is the lower of the prior candle's low and the entry candle's low so far, excluding the trigger bar, and it stays there. Hits are tracked only after the entry. One R is that distance. The RMA books keep a name only when a 5-minute bar had closed above the 20 RMA by the decision time. First name is the earliest entry that day, then the symbol. Nothing after 15:30.

The entry does not wait for the candle to close. If the completed candle takes out the prior low as well and finishes as a 3, the trade is kept. The pattern label is the prefix, and the share that finished as a 2U is below. A 2D followed by an inside is 1-2d-2u only, not also 2d-2u. A 2D with anything else before it, including a 3, is 2d-2u.

The stop is fixed when the trade is filled: the lower of the prior candle's low and the lows of the 5-minute bars in the entry candle that had already closed. The trigger bar's own low is not included, and the stop is not moved down to the entry candle's final low. A later 5-minute bar at or below the stop exits at the stop. A bar that opens below the stop exits at the open and can book worse than −1R. A trigger whose stop is not below the entry is skipped, and the scan continues for a later reversal that day. A through-trade may use the trigger bar's close for the 20 RMA check. A gap fill at the open uses only bars that had already closed.

**30-minute first** is the best of these books by day 3 at -0.22R per morning (n = 59 mornings / 59 fills). The 10:30 first-name RMA book, the benchmark, is +0.29R by day 3. On the mornings both books have a day-3 result, this book is -0.51R versus that one.

Average % and average R give each morning one vote. Expectancy, win rate, the stop-hit rate, and best, median, and worst are per fill. vs QQQ is that morning's stop-aware percent minus QQQ held from the same minute, with no stop on QQQ. vs 10:30 first is the paired excess in R against the 10:30 first-name RMA book.

### 15-minute

**All** enters at 10:48 on average (median 10:35) with an average stop 0.96% under the entry (2d-2u 315, 2d-1-2u 153, 3-1-2u 48, 1-2d-2u 84; finished as 2U 84%); **First** enters at 10:01 on average (median 10:00) with an average stop 1.58% under the entry (2d-2u 35, 2d-1-2u 10, 3-1-2u 13, 1-2d-2u 2; finished as 2U 95%); **RMA all** enters at 10:56 on average (median 10:45) with an average stop 0.91% under the entry (2d-2u 231, 2d-1-2u 91, 3-1-2u 44, 1-2d-2u 68; finished as 2U 86%); **RMA first** enters at 10:09 on average (median 10:05) with an average stop 1.42% under the entry (2d-2u 31, 2d-1-2u 6, 3-1-2u 18, 1-2d-2u 5; finished as 2U 92%).

| | All | First | RMA all | RMA first |
| --- | ---: | ---: | ---: | ---: |
| EOD days | 60 | 60 | 60 | 60 |
| EOD fills | 600 | 60 | 434 | 60 |
| EOD avg % | +0.02% | -0.03% | +0.17% | +0.37% |
| EOD avg R | +0.03R | -0.05R | +0.15R | +0.27R |
| EOD win | 36.0% | 46.7% | 36.4% | 48.3% |
| EOD stop | 56.5% | 35.0% | 56.5% | 33.3% |
| EOD gaps | 6 | 1 | 5 | 0 |
| EOD total R | +16.7R | -3.1R | +38.2R | +16.4R |
| EOD expectancy | +0.03R | -0.05R | +0.09R | +0.27R |
| EOD avg MFE | +2.81R | +2.14R | +2.90R | +2.29R |
| EOD median R | -1.00R | -0.13R | -1.00R | -0.04R |
| EOD best R | +11.56R | +2.51R | +11.56R | +6.32R |
| EOD worst R | -1.77R | -1.08R | -1.77R | -1.02R |
| EOD median % | -0.42% | -0.29% | -0.39% | -0.07% |
| EOD best % | +6.53% | +4.60% | +6.53% | +6.28% |
| EOD worst % | -3.65% | -2.28% | -3.65% | -2.28% |
| EOD vs QQQ | +0.02% | -0.04% | +0.18% | +0.37% |
| EOD vs 10:30 first | -0.07R | -0.15R | +0.06R | +0.18R |
| +1d days | 59 | 59 | 59 | 59 |
| +1d fills | 590 | 59 | 425 | 59 |
| +1d avg % | +0.03% | +0.03% | +0.03% | -0.15% |
| +1d avg R | +0.03R | -0.06R | +0.07R | -0.16R |
| +1d win | 22.9% | 35.6% | 21.9% | 30.5% |
| +1d stop | 75.4% | 61.0% | 76.2% | 64.4% |
| +1d gaps | 34 | 6 | 22 | 6 |
| +1d total R | +15.8R | -3.3R | +11.2R | -9.2R |
| +1d expectancy | +0.03R | -0.06R | +0.03R | -0.16R |
| +1d avg MFE | +2.85R | +2.17R | +2.95R | +2.32R |
| +1d median R | -1.00R | -1.00R | -1.00R | -1.00R |
| +1d best R | +18.84R | +5.26R | +18.84R | +6.22R |
| +1d worst R | -6.03R | -3.70R | -6.03R | -3.70R |
| +1d median % | -0.60% | -0.80% | -0.57% | -0.71% |
| +1d best % | +14.32% | +14.32% | +14.32% | +14.32% |
| +1d worst % | -5.62% | -4.78% | -5.62% | -4.78% |
| +1d vs QQQ | -0.06% | -0.08% | -0.06% | -0.25% |
| +1d vs 10:30 first | +0.11R | +0.03R | +0.15R | -0.07R |
| +2d days | 58 | 59 | 58 | 59 |
| +2d fills | 580 | 59 | 422 | 59 |
| +2d avg % | -0.09% | -0.20% | -0.14% | -0.61% |
| +2d avg R | -0.15R | -0.27R | -0.18R | -0.60R |
| +2d win | 15.9% | 25.4% | 13.7% | 17.0% |
| +2d stop | 83.8% | 74.6% | 85.8% | 83.0% |
| +2d gaps | 45 | 7 | 31 | 7 |
| +2d total R | -89.1R | -16.1R | -106.5R | -35.4R |
| +2d expectancy | -0.15R | -0.27R | -0.25R | -0.60R |
| +2d avg MFE | +2.87R | +2.17R | +2.95R | +2.32R |
| +2d median R | -1.00R | -1.00R | -1.00R | -1.00R |
| +2d best R | +25.50R | +5.72R | +25.50R | +3.80R |
| +2d worst R | -26.61R | -3.70R | -26.61R | -3.70R |
| +2d median % | -0.68% | -0.97% | -0.68% | -0.96% |
| +2d best % | +18.03% | +12.12% | +18.03% | +12.12% |
| +2d worst % | -19.91% | -4.78% | -19.91% | -4.78% |
| +2d vs QQQ | -0.29% | -0.34% | -0.33% | -0.75% |
| +2d vs 10:30 first | -0.23R | -0.34R | -0.26R | -0.68R |
| +3d days | 58 | 59 | 58 | 59 |
| +3d fills | 580 | 59 | 422 | 59 |
| +3d avg % | -0.16% | -0.33% | -0.18% | -0.57% |
| +3d avg R | -0.25R | -0.35R | -0.23R | -0.54R |
| +3d win | 12.1% | 18.6% | 10.9% | 11.9% |
| +3d stop | 87.4% | 79.7% | 88.4% | 86.4% |
| +3d gaps | 50 | 8 | 34 | 7 |
| +3d total R | -142.2R | -20.5R | -128.0R | -31.8R |
| +3d expectancy | -0.25R | -0.35R | -0.30R | -0.54R |
| +3d avg MFE | +2.87R | +2.17R | +2.95R | +2.32R |
| +3d median R | -1.00R | -1.00R | -1.00R | -1.00R |
| +3d best R | +20.96R | +6.83R | +20.96R | +6.83R |
| +3d worst R | -26.61R | -3.70R | -26.61R | -3.70R |
| +3d median % | -0.71% | -1.18% | -0.69% | -1.18% |
| +3d best % | +16.25% | +15.76% | +16.25% | +15.76% |
| +3d worst % | -19.91% | -4.78% | -19.91% | -4.78% |
| +3d vs QQQ | -0.51% | -0.62% | -0.52% | -0.85% |
| +3d vs 10:30 first | -0.55R | -0.64R | -0.54R | -0.84R |
| +4d days | 57 | 59 | 57 | 59 |
| +4d fills | 570 | 59 | 413 | 59 |
| +4d avg % | -0.10% | -0.23% | -0.15% | -0.62% |
| +4d avg R | -0.18R | -0.32R | -0.18R | -0.53R |
| +4d win | 11.4% | 17.0% | 10.4% | 11.9% |
| +4d stop | 88.4% | 81.4% | 89.3% | 86.4% |
| +4d gaps | 50 | 8 | 34 | 7 |
| +4d total R | -101.7R | -18.8R | -101.0R | -31.1R |
| +4d expectancy | -0.18R | -0.32R | -0.24R | -0.53R |
| +4d avg MFE | +2.90R | +2.17R | +2.98R | +2.32R |
| +4d median R | -1.00R | -1.00R | -1.00R | -1.00R |
| +4d best R | +29.48R | +8.88R | +29.48R | +8.88R |
| +4d worst R | -26.61R | -3.70R | -26.61R | -3.70R |
| +4d median % | -0.71% | -1.16% | -0.69% | -1.13% |
| +4d best % | +19.11% | +14.21% | +15.50% | +13.14% |
| +4d worst % | -19.91% | -4.78% | -19.91% | -4.78% |
| +4d vs QQQ | -0.66% | -0.65% | -0.71% | -1.04% |
| +4d vs 10:30 first | -0.38R | -0.47R | -0.38R | -0.69R |
| +5d days | 57 | 59 | 57 | 59 |
| +5d fills | 570 | 59 | 413 | 59 |
| +5d avg % | +0.03% | -0.01% | -0.01% | -0.57% |
| +5d avg R | -0.07R | -0.26R | -0.02R | -0.50R |
| +5d win | 10.9% | 15.2% | 9.9% | 10.2% |
| +5d stop | 88.9% | 83.0% | 89.8% | 88.1% |
| +5d gaps | 51 | 9 | 35 | 8 |
| +5d total R | -41.3R | -15.3R | -52.8R | -29.5R |
| +5d expectancy | -0.07R | -0.26R | -0.13R | -0.50R |
| +5d avg MFE | +2.90R | +2.17R | +2.98R | +2.32R |
| +5d median R | -1.00R | -1.00R | -1.00R | -1.00R |
| +5d best R | +31.26R | +7.70R | +31.26R | +7.70R |
| +5d worst R | -26.61R | -3.70R | -26.61R | -3.70R |
| +5d median % | -0.71% | -1.18% | -0.70% | -1.18% |
| +5d best % | +22.69% | +17.21% | +18.71% | +13.75% |
| +5d worst % | -19.91% | -4.78% | -19.91% | -4.78% |
| +5d vs QQQ | -0.69% | -0.55% | -0.72% | -1.14% |
| +5d vs 10:30 first | -0.45R | -0.59R | -0.40R | -0.84R |

### 30-minute

**All** enters at 11:54 on average (median 11:35) with an average stop 0.97% under the entry (2d-2u 291, 2d-1-2u 167, 3-1-2u 42, 1-2d-2u 78; finished as 2U 82%); **First** enters at 10:34 on average (median 10:35) with an average stop 1.58% under the entry (2d-2u 35, 2d-1-2u 10, 3-1-2u 14, 1-2d-2u 1; finished as 2U 90%); **RMA all** enters at 12:05 on average (median 11:45) with an average stop 0.89% under the entry (2d-2u 224, 2d-1-2u 113, 3-1-2u 40, 1-2d-2u 66; finished as 2U 80%); **RMA first** enters at 10:41 on average (median 10:35) with an average stop 1.43% under the entry (2d-2u 34, 2d-1-2u 6, 3-1-2u 16, 1-2d-2u 4; finished as 2U 93%).

| | All | First | RMA all | RMA first |
| --- | ---: | ---: | ---: | ---: |
| EOD days | 60 | 60 | 60 | 60 |
| EOD fills | 578 | 60 | 443 | 60 |
| EOD avg % | -0.03% | +0.08% | -0.01% | +0.02% |
| EOD avg R | -0.04R | +0.09R | -0.04R | +0.02R |
| EOD win | 37.2% | 45.0% | 37.0% | 45.0% |
| EOD stop | 50.5% | 31.7% | 50.6% | 33.3% |
| EOD gaps | 4 | 0 | 4 | 0 |
| EOD total R | -23.4R | +5.6R | -11.1R | +1.2R |
| EOD expectancy | -0.04R | +0.09R | -0.03R | +0.02R |
| EOD avg MFE | +2.67R | +2.31R | +2.71R | +2.11R |
| EOD median R | -1.00R | -0.13R | -1.00R | -0.13R |
| EOD best R | +10.44R | +3.95R | +10.44R | +3.95R |
| EOD worst R | -1.10R | -1.00R | -1.10R | -1.00R |
| EOD median % | -0.35% | -0.17% | -0.34% | -0.15% |
| EOD best % | +7.25% | +5.86% | +7.25% | +5.86% |
| EOD worst % | -5.36% | -2.69% | -5.36% | -2.32% |
| EOD vs QQQ | -0.01% | +0.05% | 0.00% | +0.01% |
| EOD vs 10:30 first | -0.15R | -0.01R | -0.14R | -0.10R |
| +1d days | 59 | 59 | 59 | 59 |
| +1d fills | 568 | 59 | 434 | 59 |
| +1d avg % | -0.09% | -0.15% | -0.08% | -0.15% |
| +1d avg R | -0.18R | -0.26R | -0.17R | -0.27R |
| +1d win | 20.4% | 27.1% | 19.4% | 25.4% |
| +1d stop | 77.1% | 66.1% | 78.3% | 67.8% |
| +1d gaps | 51 | 5 | 40 | 5 |
| +1d total R | -99.3R | -15.2R | -69.7R | -16.1R |
| +1d expectancy | -0.17R | -0.26R | -0.16R | -0.27R |
| +1d avg MFE | +2.71R | +2.34R | +2.76R | +2.14R |
| +1d median R | -1.00R | -1.00R | -1.00R | -1.00R |
| +1d best R | +14.91R | +4.14R | +14.91R | +4.96R |
| +1d worst R | -15.75R | -2.09R | -15.75R | -2.09R |
| +1d median % | -0.63% | -0.83% | -0.61% | -0.92% |
| +1d best % | +14.16% | +14.07% | +14.16% | +14.07% |
| +1d worst % | -8.15% | -3.27% | -8.15% | -3.27% |
| +1d vs QQQ | -0.16% | -0.27% | -0.15% | -0.25% |
| +1d vs 10:30 first | -0.10R | -0.18R | -0.09R | -0.19R |
| +2d days | 59 | 59 | 59 | 59 |
| +2d fills | 568 | 59 | 434 | 59 |
| +2d avg % | -0.14% | -0.22% | -0.15% | -0.45% |
| +2d avg R | -0.26R | -0.33R | -0.25R | -0.48R |
| +2d win | 16.0% | 23.7% | 14.3% | 18.6% |
| +2d stop | 83.5% | 74.6% | 85.2% | 79.7% |
| +2d gaps | 63 | 10 | 51 | 10 |
| +2d total R | -141.4R | -19.4R | -113.7R | -28.2R |
| +2d expectancy | -0.25R | -0.33R | -0.26R | -0.48R |
| +2d avg MFE | +2.71R | +2.34R | +2.76R | +2.14R |
| +2d median R | -1.00R | -1.00R | -1.00R | -1.00R |
| +2d best R | +15.93R | +4.20R | +15.93R | +4.20R |
| +2d worst R | -21.34R | -3.60R | -21.34R | -3.60R |
| +2d median % | -0.69% | -1.06% | -0.66% | -1.08% |
| +2d best % | +18.61% | +11.87% | +18.61% | +11.87% |
| +2d worst % | -20.06% | -3.46% | -20.06% | -3.46% |
| +2d vs QQQ | -0.31% | -0.41% | -0.32% | -0.67% |
| +2d vs 10:30 first | -0.33R | -0.40R | -0.32R | -0.55R |
| +3d days | 59 | 59 | 59 | 59 |
| +3d fills | 568 | 59 | 434 | 59 |
| +3d avg % | -0.20% | -0.11% | -0.24% | -0.52% |
| +3d avg R | -0.32R | -0.22R | -0.31R | -0.51R |
| +3d win | 12.7% | 18.6% | 11.3% | 11.9% |
| +3d stop | 86.6% | 78.0% | 88.0% | 84.8% |
| +3d gaps | 67 | 11 | 54 | 11 |
| +3d total R | -173.0R | -12.8R | -147.3R | -30.0R |
| +3d expectancy | -0.30R | -0.22R | -0.34R | -0.51R |
| +3d avg MFE | +2.71R | +2.34R | +2.76R | +2.14R |
| +3d median R | -1.00R | -1.00R | -1.00R | -1.00R |
| +3d best R | +15.96R | +7.88R | +15.96R | +6.87R |
| +3d worst R | -21.34R | -3.60R | -21.34R | -3.60R |
| +3d median % | -0.72% | -1.19% | -0.69% | -1.19% |
| +3d best % | +16.15% | +15.51% | +16.15% | +15.51% |
| +3d worst % | -20.06% | -3.96% | -20.06% | -3.96% |
| +3d vs QQQ | -0.50% | -0.42% | -0.56% | -0.89% |
| +3d vs 10:30 first | -0.61R | -0.51R | -0.60R | -0.81R |
| +4d days | 59 | 59 | 59 | 59 |
| +4d fills | 568 | 59 | 434 | 59 |
| +4d avg % | -0.16% | +0.09% | -0.31% | -0.46% |
| +4d avg R | -0.30R | -0.17R | -0.38R | -0.46R |
| +4d win | 11.6% | 20.3% | 10.1% | 13.6% |
| +4d stop | 88.0% | 78.0% | 89.4% | 84.8% |
| +4d gaps | 70 | 11 | 57 | 11 |
| +4d total R | -166.8R | -10.2R | -170.8R | -27.4R |
| +4d expectancy | -0.29R | -0.17R | -0.39R | -0.46R |
| +4d avg MFE | +2.71R | +2.34R | +2.76R | +2.14R |
| +4d median R | -1.00R | -1.00R | -1.00R | -1.00R |
| +4d best R | +19.13R | +9.27R | +19.13R | +9.24R |
| +4d worst R | -21.34R | -3.60R | -21.34R | -3.60R |
| +4d median % | -0.73% | -1.19% | -0.70% | -1.19% |
| +4d best % | +18.61% | +14.93% | +15.40% | +12.89% |
| +4d worst % | -20.06% | -3.96% | -20.06% | -3.96% |
| +4d vs QQQ | -0.64% | -0.38% | -0.80% | -0.99% |
| +4d vs 10:30 first | -0.46R | -0.32R | -0.54R | -0.62R |
| +5d days | 59 | 59 | 59 | 59 |
| +5d fills | 568 | 59 | 434 | 59 |
| +5d avg % | +0.01% | +0.50% | -0.19% | -0.33% |
| +5d avg R | -0.17R | -0.06R | -0.29R | -0.46R |
| +5d win | 11.4% | 18.6% | 10.1% | 13.6% |
| +5d stop | 88.4% | 79.7% | 89.9% | 86.4% |
| +5d gaps | 70 | 11 | 57 | 11 |
| +5d total R | -93.5R | -3.3R | -131.7R | -27.1R |
| +5d expectancy | -0.16R | -0.06R | -0.30R | -0.46R |
| +5d avg MFE | +2.71R | +2.34R | +2.76R | +2.14R |
| +5d median R | -1.00R | -1.00R | -1.00R | -1.00R |
| +5d best R | +24.46R | +15.01R | +20.50R | +11.34R |
| +5d worst R | -21.34R | -3.60R | -21.34R | -3.60R |
| +5d median % | -0.73% | -1.19% | -0.70% | -1.19% |
| +5d best % | +25.68% | +22.10% | +19.29% | +13.85% |
| +5d worst % | -20.06% | -3.96% | -20.06% | -3.96% |
| +5d vs QQQ | -0.61% | -0.08% | -0.84% | -1.02% |
| +5d vs 10:30 first | -0.49R | -0.38R | -0.61R | -0.79R |

## RMA cross trigger

Every top-10 leader is bought at the close of the first 5-minute bar, from 9:45 on, that closes strictly above its 20-period average. Earlier sessions warm the average. Nothing before 9:45 is an entry. A name that opens above the average is included: the open of the first bar (the 9:30 print) is compared with the average from the prior session, and those fills are counted. The stop is that entry bar's low. One R is that distance. The same rule runs on the Wilder RMA, the 20 SMA, and the 20 EMA.

Opened above means the open of the first regular-session bar, the 9:30 print, is strictly above the average carried in from the prior session, before today's bars update it. Those names are still bought at the first bar at or after 9:45 that closes above the average. They are counted below. A name that never closes above the average is not bought.

The stop is the low of that entry bar, which is final once the bar has closed. The entry bar is not a stop. A later 5-minute bar at or below the stop exits at the stop. A bar that opens below the stop exits at the open and can book worse than −1R. A bar whose low is not strictly under its close has no risk, so it is skipped and the scan keeps looking for a later bar that day. Trades per day includes tape sessions where nobody triggered.

**RMA** is the best of these books by day 3 at -0.54R per morning (n = 58 mornings / 564 fills). The 10:30 first-name RMA book, the benchmark, is +0.29R by day 3. On the mornings both books have a day-3 result, this book is -0.84R versus that one.

Average % and average R give each morning one vote. Expectancy, win rate, the stop-hit rate, and best, median, and worst are per fill. vs QQQ is that morning's stop-aware percent minus QQQ held from the same minute, with no stop on QQQ. vs 10:30 first is the paired excess in R against the 10:30 first-name RMA book.

**RMA** enters at 10:35 on average (median 9:45) with an average stop 0.55% under the entry (300 of 584 opened above the average; 9.7 trades per tape day); **SMA** enters at 10:18 on average (median 9:45) with an average stop 0.55% under the entry (298 of 599 opened above the average; 10.0 trades per tape day); **EMA** enters at 10:22 on average (median 9:45) with an average stop 0.56% under the entry (292 of 598 opened above the average; 10.0 trades per tape day).

| | RMA | SMA | EMA |
| --- | ---: | ---: | ---: |
| EOD days | 60 | 60 | 60 |
| EOD fills | 584 | 599 | 598 |
| EOD avg % | -0.08% | -0.07% | -0.08% |
| EOD avg R | -0.27R | -0.32R | -0.24R |
| EOD win | 16.6% | 15.9% | 16.4% |
| EOD stop | 80.7% | 81.6% | 81.1% |
| EOD gaps | 18 | 16 | 14 |
| EOD total R | -151.7R | -192.2R | -140.1R |
| EOD expectancy | -0.26R | -0.32R | -0.23R |
| EOD avg MFE | +2.90R | +2.90R | +2.85R |
| EOD median R | -1.00R | -1.00R | -1.00R |
| EOD best R | +46.10R | +46.10R | +46.10R |
| EOD worst R | -36.52R | -42.02R | -36.52R |
| EOD median % | -0.32% | -0.32% | -0.34% |
| EOD best % | +10.38% | +10.38% | +10.38% |
| EOD worst % | -2.42% | -2.42% | -2.42% |
| EOD vs QQQ | -0.05% | -0.06% | -0.07% |
| EOD vs 10:30 first | -0.38R | -0.43R | -0.34R |
| +1d days | 59 | 60 | 60 |
| +1d fills | 574 | 599 | 598 |
| +1d avg % | -0.12% | -0.11% | -0.12% |
| +1d avg R | -0.37R | -0.52R | -0.47R |
| +1d win | 10.4% | 10.3% | 10.2% |
| +1d stop | 89.2% | 89.3% | 89.5% |
| +1d gaps | 33 | 28 | 29 |
| +1d total R | -208.7R | -308.4R | -280.1R |
| +1d expectancy | -0.36R | -0.51R | -0.47R |
| +1d avg MFE | +2.93R | +2.90R | +2.85R |
| +1d median R | -1.00R | -1.00R | -1.00R |
| +1d best R | +57.80R | +41.97R | +29.49R |
| +1d worst R | -36.52R | -42.02R | -36.52R |
| +1d median % | -0.36% | -0.37% | -0.38% |
| +1d best % | +14.96% | +14.96% | +14.96% |
| +1d worst % | -6.88% | -6.88% | -6.88% |
| +1d vs QQQ | -0.19% | -0.19% | -0.21% |
| +1d vs 10:30 first | -0.29R | -0.42R | -0.38R |
| +2d days | 58 | 59 | 59 |
| +2d fills | 564 | 589 | 588 |
| +2d avg % | -0.11% | -0.13% | -0.14% |
| +2d avg R | -0.57R | -0.74R | -0.67R |
| +2d win | 8.2% | 8.0% | 8.0% |
| +2d stop | 91.8% | 92.0% | 92.0% |
| +2d gaps | 38 | 33 | 34 |
| +2d total R | -325.1R | -433.1R | -392.6R |
| +2d expectancy | -0.58R | -0.74R | -0.67R |
| +2d avg MFE | +2.91R | +2.89R | +2.85R |
| +2d median R | -1.00R | -1.00R | -1.00R |
| +2d best R | +48.10R | +53.35R | +37.61R |
| +2d worst R | -97.08R | -97.08R | -97.08R |
| +2d median % | -0.38% | -0.39% | -0.40% |
| +2d best % | +19.42% | +19.42% | +19.42% |
| +2d worst % | -18.45% | -18.45% | -18.45% |
| +2d vs QQQ | -0.29% | -0.31% | -0.33% |
| +2d vs 10:30 first | -0.66R | -0.80R | -0.73R |
| +3d days | 58 | 59 | 59 |
| +3d fills | 564 | 589 | 588 |
| +3d avg % | -0.07% | -0.07% | -0.09% |
| +3d avg R | -0.54R | -0.76R | -0.68R |
| +3d win | 7.3% | 7.0% | 7.0% |
| +3d stop | 92.7% | 93.0% | 93.0% |
| +3d gaps | 38 | 34 | 35 |
| +3d total R | -300.6R | -445.1R | -401.3R |
| +3d expectancy | -0.53R | -0.76R | -0.68R |
| +3d avg MFE | +2.91R | +2.89R | +2.85R |
| +3d median R | -1.00R | -1.00R | -1.00R |
| +3d best R | +69.30R | +41.13R | +28.90R |
| +3d worst R | -97.08R | -97.08R | -97.08R |
| +3d median % | -0.39% | -0.39% | -0.40% |
| +3d best % | +18.31% | +18.31% | +18.31% |
| +3d worst % | -18.45% | -18.45% | -18.45% |
| +3d vs QQQ | -0.40% | -0.41% | -0.43% |
| +3d vs 10:30 first | -0.84R | -1.04R | -0.97R |
| +4d days | 58 | 59 | 59 |
| +4d fills | 564 | 589 | 588 |
| +4d avg % | -0.13% | -0.14% | -0.15% |
| +4d avg R | -0.53R | -0.78R | -0.71R |
| +4d win | 6.6% | 5.9% | 5.9% |
| +4d stop | 93.3% | 93.9% | 93.9% |
| +4d gaps | 38 | 35 | 36 |
| +4d total R | -298.9R | -458.2R | -416.3R |
| +4d expectancy | -0.53R | -0.78R | -0.71R |
| +4d avg MFE | +2.91R | +2.89R | +2.85R |
| +4d median R | -1.00R | -1.00R | -1.00R |
| +4d best R | +85.40R | +48.87R | +34.42R |
| +4d worst R | -97.08R | -97.08R | -97.08R |
| +4d median % | -0.40% | -0.40% | -0.41% |
| +4d best % | +20.77% | +20.77% | +20.77% |
| +4d worst % | -18.45% | -18.45% | -18.45% |
| +4d vs QQQ | -0.67% | -0.69% | -0.70% |
| +4d vs 10:30 first | -0.70R | -0.93R | -0.86R |
| +5d days | 58 | 59 | 59 |
| +5d fills | 564 | 589 | 588 |
| +5d avg % | -0.14% | -0.11% | -0.12% |
| +5d avg R | -0.54R | -0.68R | -0.64R |
| +5d win | 5.7% | 5.4% | 5.4% |
| +5d stop | 94.3% | 94.6% | 94.6% |
| +5d gaps | 40 | 36 | 37 |
| +5d total R | -304.3R | -398.5R | -373.5R |
| +5d expectancy | -0.54R | -0.68R | -0.64R |
| +5d avg MFE | +2.91R | +2.89R | +2.85R |
| +5d median R | -1.00R | -1.00R | -1.00R |
| +5d best R | +74.50R | +100.96R | +71.58R |
| +5d worst R | -97.08R | -97.08R | -97.08R |
| +5d median % | -0.40% | -0.40% | -0.42% |
| +5d best % | +19.80% | +20.63% | +20.63% |
| +5d worst % | -18.45% | -18.45% | -18.45% |
| +5d vs QQQ | -0.85% | -0.83% | -0.84% |
| +5d vs 10:30 first | -0.88R | -1.00R | -0.96R |

## EMA pullback reclaim

Every top-10 leader is bought at the close of the first 5-minute bar, from 9:45 on, that closes back above the 20 EMA after a bar in today's session closed below it. Earlier sessions warm the average. A close back above before 9:45 does not fill, and the name has to close below the EMA again. A name that never closes below it, including one that opened above and stayed there, is not bought. One trade per name. The same entry is stopped three ways: the reclaim bar's low, the lowest low from the first close below through that bar, and the session low from 9:30 through the entry. Each stop is shown for the first name, the first two, the first three, and every name. The order is the reclaim time, then the leader-list rank, with rank 1 ahead of rank 2.

A pullback is a 5-minute bar in today's session whose close is strictly below the 20 EMA. The reclaim is the next bar whose close is strictly back above it. Close equal to the EMA is neither. The pullback can start before 9:45, including on the 9:35 bar. The reclaim bar itself has to end at 9:45 or later. A reclaim before 9:45 is not stored for later: that episode is over, and a name that stays above the EMA after it is not bought.

The pullback stop is the lowest low from the first close-below bar of that episode through the reclaim bar, including the reclaim bar. The low-of-day stop is the lowest low from 9:30 through the entry bar, so a low from before the pullback counts. The entry bar is not a stop. A later 5-minute bar at or below the stop exits at the stop. A bar that opens below the stop exits at the open and can book worse than −1R. A stop that is not strictly under the entry is dropped for that variant only, and a later name does not move up to fill the cap. Trades per day includes tape sessions where nobody reclaimed.

First, first 2, and first 3 are the earliest reclaims that day. A tie on the reclaim bar goes to the better leader-list rank, rank 1 ahead of rank 2, because that rank is the prior-close leadership score. The symbol breaks a remaining tie. The same order picks the single first name.

**Low of day, first** is the best of these books by day 3 at 0.00R per morning (n = 60 mornings / 60 fills). The 10:30 first-name RMA book, the benchmark, is +0.29R by day 3. On the mornings both books have a day-3 result, this book is -0.26R versus that one.

Average % and average R give each morning one vote. Expectancy, win rate, the stop-hit rate, and best, median, and worst are per fill. vs QQQ is that morning's stop-aware percent minus QQQ held from the same minute, with no stop on QQQ. vs 10:30 first is the paired excess in R against the 10:30 first-name RMA book.

### Stop at the reclaim bar's low

**First** enters at 9:55 on average (median 9:50) with an average stop 0.84% under the entry (1.0 trades per tape day); **First 2** enters at 10:01 on average (median 9:55) with an average stop 0.72% under the entry (2.0 trades per tape day); **First 3** enters at 10:07 on average (median 10:00) with an average stop 0.69% under the entry (3.0 trades per tape day); **All** enters at 11:13 on average (median 10:55) with an average stop 0.49% under the entry (9.9 trades per tape day).

| | First | First 2 | First 3 | All |
| --- | ---: | ---: | ---: | ---: |
| EOD days | 60 | 60 | 60 | 60 |
| EOD fills | 60 | 120 | 180 | 594 |
| EOD avg % | -0.09% | -0.01% | -0.06% | -0.06% |
| EOD avg R | -0.05R | -0.13R | -0.13R | -0.13R |
| EOD win | 20.0% | 21.7% | 20.6% | 17.5% |
| EOD stop | 70.0% | 73.3% | 75.6% | 80.1% |
| EOD gaps | 1 | 3 | 4 | 9 |
| EOD total R | -3.2R | -15.1R | -23.4R | -84.4R |
| EOD expectancy | -0.05R | -0.13R | -0.13R | -0.14R |
| EOD avg MFE | +2.59R | +2.52R | +2.79R | +2.93R |
| EOD median R | -1.00R | -1.00R | -1.00R | -1.00R |
| EOD best R | +18.23R | +18.23R | +18.23R | +21.51R |
| EOD worst R | -1.11R | -6.20R | -6.20R | -7.37R |
| EOD median % | -0.56% | -0.50% | -0.46% | -0.31% |
| EOD best % | +5.43% | +6.84% | +6.84% | +6.84% |
| EOD worst % | -2.06% | -2.06% | -2.06% | -2.06% |
| EOD vs QQQ | -0.11% | -0.04% | -0.09% | -0.06% |
| EOD vs 10:30 first | -0.15R | -0.23R | -0.23R | -0.24R |
| +1d days | 60 | 59 | 59 | 59 |
| +1d fills | 60 | 118 | 177 | 584 |
| +1d avg % | -0.10% | -0.22% | -0.21% | -0.09% |
| +1d avg R | -0.20R | -0.47R | -0.30R | -0.32R |
| +1d win | 15.0% | 11.9% | 10.7% | 9.6% |
| +1d stop | 85.0% | 88.1% | 88.7% | 90.2% |
| +1d gaps | 6 | 11 | 12 | 29 |
| +1d total R | -11.8R | -55.7R | -53.8R | -189.2R |
| +1d expectancy | -0.20R | -0.47R | -0.30R | -0.32R |
| +1d avg MFE | +2.59R | +2.54R | +2.83R | +2.98R |
| +1d median R | -1.00R | -1.00R | -1.00R | -1.00R |
| +1d best R | +16.45R | +16.45R | +21.44R | +29.49R |
| +1d worst R | -5.17R | -6.20R | -6.20R | -14.06R |
| +1d median % | -0.63% | -0.60% | -0.56% | -0.36% |
| +1d best % | +14.33% | +14.33% | +14.33% | +14.33% |
| +1d worst % | -4.28% | -4.28% | -4.28% | -7.83% |
| +1d vs QQQ | -0.22% | -0.35% | -0.34% | -0.19% |
| +1d vs 10:30 first | -0.10R | -0.40R | -0.23R | -0.24R |
| +2d days | 60 | 58 | 58 | 58 |
| +2d fills | 60 | 116 | 174 | 574 |
| +2d avg % | -0.11% | -0.20% | -0.23% | -0.11% |
| +2d avg R | -0.30R | -0.58R | -0.43R | -0.42R |
| +2d win | 11.7% | 7.8% | 7.5% | 6.8% |
| +2d stop | 88.3% | 92.2% | 92.5% | 93.0% |
| +2d gaps | 7 | 12 | 14 | 35 |
| +2d total R | -17.8R | -67.1R | -74.0R | -239.6R |
| +2d expectancy | -0.30R | -0.58R | -0.43R | -0.42R |
| +2d avg MFE | +2.59R | +2.46R | +2.79R | +3.00R |
| +2d median R | -1.00R | -1.00R | -1.00R | -1.00R |
| +2d best R | +13.92R | +13.92R | +23.18R | +37.61R |
| +2d worst R | -5.17R | -6.20R | -6.20R | -19.71R |
| +2d median % | -0.67% | -0.62% | -0.58% | -0.37% |
| +2d best % | +12.13% | +12.13% | +12.13% | +13.52% |
| +2d worst % | -4.28% | -4.28% | -4.28% | -7.83% |
| +2d vs QQQ | -0.32% | -0.44% | -0.46% | -0.31% |
| +2d vs 10:30 first | -0.35R | -0.66R | -0.51R | -0.50R |
| +3d days | 60 | 58 | 58 | 58 |
| +3d fills | 60 | 116 | 174 | 574 |
| +3d avg % | -0.02% | -0.13% | -0.17% | -0.09% |
| +3d avg R | -0.14R | -0.48R | -0.40R | -0.48R |
| +3d win | 11.7% | 7.8% | 6.9% | 6.1% |
| +3d stop | 88.3% | 92.2% | 93.1% | 93.9% |
| +3d gaps | 7 | 12 | 15 | 38 |
| +3d total R | -8.4R | -55.6R | -70.2R | -274.7R |
| +3d expectancy | -0.14R | -0.48R | -0.40R | -0.48R |
| +3d avg MFE | +2.59R | +2.46R | +2.79R | +3.00R |
| +3d median R | -1.00R | -1.00R | -1.00R | -1.00R |
| +3d best R | +18.11R | +18.11R | +20.27R | +28.90R |
| +3d worst R | -5.17R | -6.20R | -6.20R | -19.71R |
| +3d median % | -0.67% | -0.62% | -0.58% | -0.38% |
| +3d best % | +15.78% | +15.78% | +15.78% | +16.20% |
| +3d worst % | -4.28% | -4.28% | -4.28% | -7.83% |
| +3d vs QQQ | -0.38% | -0.52% | -0.56% | -0.45% |
| +3d vs 10:30 first | -0.40R | -0.79R | -0.71R | -0.79R |
| +4d days | 60 | 58 | 58 | 58 |
| +4d fills | 60 | 116 | 174 | 574 |
| +4d avg % | -0.15% | -0.21% | -0.20% | -0.13% |
| +4d avg R | -0.28R | -0.56R | -0.31R | -0.52R |
| +4d win | 8.3% | 6.0% | 5.8% | 5.1% |
| +4d stop | 88.3% | 92.2% | 93.1% | 94.6% |
| +4d gaps | 7 | 12 | 15 | 40 |
| +4d total R | -16.9R | -65.2R | -54.5R | -296.9R |
| +4d expectancy | -0.28R | -0.56R | -0.31R | -0.52R |
| +4d avg MFE | +2.59R | +2.46R | +2.79R | +3.00R |
| +4d median R | -1.00R | -1.00R | -1.00R | -1.00R |
| +4d best R | +16.85R | +16.85R | +48.27R | +48.27R |
| +4d worst R | -5.17R | -6.20R | -6.20R | -34.25R |
| +4d median % | -0.67% | -0.62% | -0.58% | -0.38% |
| +4d best % | +13.16% | +13.44% | +13.44% | +17.11% |
| +4d worst % | -4.28% | -4.28% | -4.28% | -15.20% |
| +4d vs QQQ | -0.73% | -0.82% | -0.80% | -0.69% |
| +4d vs 10:30 first | -0.42R | -0.73R | -0.48R | -0.69R |
| +5d days | 60 | 58 | 58 | 58 |
| +5d fills | 60 | 116 | 174 | 574 |
| +5d avg % | -0.06% | -0.13% | -0.20% | -0.07% |
| +5d avg R | -0.14R | -0.46R | -0.38R | -0.39R |
| +5d win | 8.3% | 6.0% | 5.8% | 4.9% |
| +5d stop | 91.7% | 94.0% | 94.2% | 95.1% |
| +5d gaps | 8 | 13 | 16 | 41 |
| +5d total R | -8.7R | -53.2R | -65.6R | -225.2R |
| +5d expectancy | -0.14R | -0.46R | -0.38R | -0.39R |
| +5d avg MFE | +2.59R | +2.46R | +2.79R | +3.00R |
| +5d median R | -1.00R | -1.00R | -1.00R | -1.00R |
| +5d best R | +23.55R | +23.55R | +35.00R | +71.58R |
| +5d worst R | -5.17R | -6.20R | -6.20R | -34.25R |
| +5d median % | -0.72% | -0.63% | -0.59% | -0.39% |
| +5d best % | +13.76% | +16.99% | +16.99% | +20.63% |
| +5d worst % | -4.28% | -4.28% | -4.28% | -15.20% |
| +5d vs QQQ | -0.80% | -0.89% | -0.97% | -0.80% |
| +5d vs 10:30 first | -0.45R | -0.80R | -0.72R | -0.73R |

### Stop at the pullback low

**First** enters at 9:55 on average (median 9:50) with an average stop 1.65% under the entry (1.0 trades per tape day); **First 2** enters at 10:01 on average (median 9:55) with an average stop 1.47% under the entry (2.0 trades per tape day); **First 3** enters at 10:07 on average (median 10:00) with an average stop 1.45% under the entry (3.0 trades per tape day); **All** enters at 11:13 on average (median 10:55) with an average stop 1.21% under the entry (9.9 trades per tape day).

| | First | First 2 | First 3 | All |
| --- | ---: | ---: | ---: | ---: |
| EOD days | 60 | 60 | 60 | 60 |
| EOD fills | 60 | 120 | 180 | 594 |
| EOD avg % | -0.08% | +0.05% | +0.02% | -0.02% |
| EOD avg R | -0.13R | -0.03R | +0.02R | -0.03R |
| EOD win | 35.0% | 38.3% | 37.8% | 34.8% |
| EOD stop | 48.3% | 51.7% | 48.9% | 49.8% |
| EOD gaps | 1 | 2 | 2 | 8 |
| EOD total R | -7.6R | -3.5R | +3.8R | -19.9R |
| EOD expectancy | -0.13R | -0.03R | +0.02R | -0.03R |
| EOD avg MFE | +2.06R | +2.13R | +2.42R | +2.47R |
| EOD median R | -0.80R | -1.00R | -0.78R | -0.98R |
| EOD best R | +9.55R | +9.55R | +9.55R | +11.73R |
| EOD worst R | -1.03R | -1.03R | -1.03R | -1.19R |
| EOD median % | -0.59% | -0.50% | -0.49% | -0.33% |
| EOD best % | +5.43% | +6.84% | +6.84% | +7.84% |
| EOD worst % | -2.28% | -3.07% | -3.07% | -5.10% |
| EOD vs QQQ | -0.10% | +0.02% | -0.01% | -0.02% |
| EOD vs 10:30 first | -0.23R | -0.13R | -0.08R | -0.13R |
| +1d days | 60 | 59 | 59 | 59 |
| +1d fills | 60 | 118 | 177 | 584 |
| +1d avg % | +0.08% | -0.15% | -0.10% | -0.06% |
| +1d avg R | -0.09R | -0.26R | -0.08R | -0.21R |
| +1d win | 25.0% | 23.7% | 25.4% | 23.6% |
| +1d stop | 68.3% | 70.3% | 69.5% | 71.9% |
| +1d gaps | 4 | 8 | 11 | 50 |
| +1d total R | -5.3R | -30.6R | -15.0R | -124.3R |
| +1d expectancy | -0.09R | -0.26R | -0.08R | -0.21R |
| +1d avg MFE | +2.06R | +2.16R | +2.45R | +2.50R |
| +1d median R | -1.00R | -1.00R | -1.00R | -1.00R |
| +1d best R | +8.58R | +8.58R | +21.44R | +21.58R |
| +1d worst R | -4.50R | -4.50R | -4.50R | -14.06R |
| +1d median % | -0.85% | -0.75% | -0.71% | -0.58% |
| +1d best % | +14.75% | +14.75% | +14.75% | +14.75% |
| +1d worst % | -4.28% | -4.38% | -4.38% | -7.83% |
| +1d vs QQQ | -0.03% | -0.28% | -0.23% | -0.16% |
| +1d vs 10:30 first | +0.01R | -0.18R | 0.00R | -0.13R |
| +2d days | 60 | 58 | 58 | 58 |
| +2d fills | 60 | 116 | 174 | 574 |
| +2d avg % | +0.21% | -0.09% | -0.11% | +0.01% |
| +2d avg R | -0.09R | -0.35R | -0.19R | -0.26R |
| +2d win | 28.3% | 20.7% | 20.1% | 20.0% |
| +2d stop | 71.7% | 79.3% | 79.9% | 78.6% |
| +2d gaps | 4 | 10 | 15 | 59 |
| +2d total R | -5.5R | -40.1R | -33.3R | -149.0R |
| +2d expectancy | -0.09R | -0.35R | -0.19R | -0.26R |
| +2d avg MFE | +2.06R | +2.13R | +2.45R | +2.53R |
| +2d median R | -1.00R | -1.00R | -1.00R | -1.00R |
| +2d best R | +7.16R | +7.16R | +22.53R | +29.30R |
| +2d worst R | -4.50R | -4.50R | -4.50R | -18.58R |
| +2d median % | -0.85% | -0.86% | -0.88% | -0.67% |
| +2d best % | +12.13% | +12.13% | +18.92% | +18.92% |
| +2d worst % | -4.28% | -4.38% | -4.92% | -7.83% |
| +2d vs QQQ | +0.05% | -0.33% | -0.33% | -0.19% |
| +2d vs 10:30 first | -0.14R | -0.43R | -0.27R | -0.34R |
| +3d days | 60 | 58 | 58 | 58 |
| +3d fills | 60 | 116 | 174 | 574 |
| +3d avg % | +0.31% | +0.04% | -0.08% | -0.03% |
| +3d avg R | -0.05R | -0.26R | -0.20R | -0.32R |
| +3d win | 25.0% | 19.0% | 17.8% | 16.6% |
| +3d stop | 73.3% | 80.2% | 81.6% | 82.4% |
| +3d gaps | 4 | 10 | 16 | 63 |
| +3d total R | -3.2R | -30.4R | -35.6R | -178.3R |
| +3d expectancy | -0.05R | -0.26R | -0.20R | -0.31R |
| +3d avg MFE | +2.06R | +2.13R | +2.45R | +2.53R |
| +3d median R | -1.00R | -1.00R | -1.00R | -1.00R |
| +3d best R | +9.32R | +9.32R | +17.56R | +17.56R |
| +3d worst R | -4.50R | -4.50R | -4.50R | -18.58R |
| +3d median % | -0.90% | -0.87% | -0.93% | -0.71% |
| +3d best % | +15.78% | +15.78% | +15.78% | +16.20% |
| +3d worst % | -4.28% | -4.38% | -4.92% | -7.83% |
| +3d vs QQQ | +0.04% | -0.32% | -0.44% | -0.34% |
| +3d vs 10:30 first | -0.31R | -0.57R | -0.51R | -0.62R |
| +4d days | 59 | 57 | 57 | 57 |
| +4d fills | 59 | 114 | 171 | 564 |
| +4d avg % | -0.03% | -0.07% | -0.05% | +0.02% |
| +4d avg R | -0.20R | -0.29R | -0.09R | -0.24R |
| +4d win | 15.2% | 14.0% | 14.0% | 14.7% |
| +4d stop | 79.7% | 83.3% | 84.2% | 84.6% |
| +4d gaps | 6 | 12 | 18 | 67 |
| +4d total R | -11.6R | -33.4R | -15.1R | -135.2R |
| +4d expectancy | -0.20R | -0.29R | -0.09R | -0.24R |
| +4d avg MFE | +2.03R | +2.13R | +2.47R | +2.56R |
| +4d median R | -1.00R | -1.00R | -1.00R | -1.00R |
| +4d best R | +8.97R | +11.28R | +37.93R | +37.93R |
| +4d worst R | -4.50R | -4.50R | -4.50R | -18.58R |
| +4d median % | -1.03% | -0.94% | -0.98% | -0.74% |
| +4d best % | +15.41% | +15.41% | +15.41% | +20.44% |
| +4d worst % | -4.28% | -4.38% | -4.92% | -15.20% |
| +4d vs QQQ | -0.54% | -0.65% | -0.63% | -0.51% |
| +4d vs 10:30 first | -0.36R | -0.50R | -0.29R | -0.45R |
| +5d days | 59 | 57 | 57 | 57 |
| +5d fills | 59 | 114 | 171 | 564 |
| +5d avg % | +0.17% | +0.01% | -0.03% | +0.16% |
| +5d avg R | -0.07R | -0.26R | -0.18R | -0.18R |
| +5d win | 17.0% | 14.0% | 14.0% | 14.2% |
| +5d stop | 81.4% | 85.1% | 85.4% | 85.5% |
| +5d gaps | 7 | 13 | 19 | 69 |
| +5d total R | -4.3R | -29.8R | -30.8R | -100.6R |
| +5d expectancy | -0.07R | -0.26R | -0.18R | -0.18R |
| +5d avg MFE | +2.03R | +2.13R | +2.47R | +2.56R |
| +5d median R | -1.00R | -1.00R | -1.00R | -1.00R |
| +5d best R | +12.34R | +12.34R | +27.50R | +30.35R |
| +5d worst R | -4.50R | -4.50R | -4.50R | -18.58R |
| +5d median % | -1.13% | -0.98% | -0.99% | -0.76% |
| +5d best % | +20.61% | +20.61% | +20.61% | +27.14% |
| +5d worst % | -4.28% | -4.38% | -4.92% | -15.41% |
| +5d vs QQQ | -0.48% | -0.72% | -0.77% | -0.52% |
| +5d vs 10:30 first | -0.41R | -0.64R | -0.56R | -0.56R |

### Stop at the low of day

**First** enters at 9:55 on average (median 9:50) with an average stop 1.82% under the entry (1.0 trades per tape day); **First 2** enters at 10:01 on average (median 9:55) with an average stop 1.72% under the entry (2.0 trades per tape day); **First 3** enters at 10:07 on average (median 10:00) with an average stop 1.74% under the entry (3.0 trades per tape day); **All** enters at 11:13 on average (median 10:55) with an average stop 1.89% under the entry (9.9 trades per tape day).

| | First | First 2 | First 3 | All |
| --- | ---: | ---: | ---: | ---: |
| EOD days | 60 | 60 | 60 | 60 |
| EOD fills | 60 | 120 | 180 | 594 |
| EOD avg % | +0.08% | +0.10% | +0.06% | -0.03% |
| EOD avg R | -0.01R | -0.04R | -0.03R | -0.06R |
| EOD win | 40.0% | 41.7% | 41.1% | 40.6% |
| EOD stop | 40.0% | 45.0% | 42.2% | 33.7% |
| EOD gaps | 1 | 1 | 1 | 4 |
| EOD total R | -0.4R | -4.7R | -6.3R | -36.6R |
| EOD expectancy | -0.01R | -0.04R | -0.03R | -0.06R |
| EOD avg MFE | +2.11R | +1.83R | +1.83R | +2.01R |
| EOD median R | -0.27R | -0.32R | -0.29R | -0.16R |
| EOD best R | +9.55R | +9.55R | +9.55R | +9.55R |
| EOD worst R | -1.03R | -1.03R | -1.03R | -1.09R |
| EOD median % | -0.30% | -0.46% | -0.46% | -0.30% |
| EOD best % | +6.01% | +6.84% | +6.84% | +7.84% |
| EOD worst % | -3.19% | -3.19% | -3.19% | -5.10% |
| EOD vs QQQ | +0.05% | +0.07% | +0.03% | -0.03% |
| EOD vs 10:30 first | -0.12R | -0.15R | -0.14R | -0.17R |
| +1d days | 60 | 59 | 59 | 59 |
| +1d fills | 60 | 118 | 177 | 584 |
| +1d avg % | +0.23% | -0.11% | -0.12% | -0.07% |
| +1d avg R | +0.01R | -0.19R | -0.18R | -0.14R |
| +1d win | 30.0% | 28.0% | 29.4% | 31.2% |
| +1d stop | 63.3% | 65.2% | 64.4% | 58.1% |
| +1d gaps | 4 | 5 | 9 | 48 |
| +1d total R | +0.5R | -22.5R | -31.2R | -83.4R |
| +1d expectancy | +0.01R | -0.19R | -0.18R | -0.14R |
| +1d avg MFE | +2.11R | +1.85R | +1.85R | +2.04R |
| +1d median R | -1.00R | -1.00R | -1.00R | -1.00R |
| +1d best R | +8.58R | +8.58R | +8.58R | +8.58R |
| +1d worst R | -3.77R | -3.77R | -3.77R | -6.53R |
| +1d median % | -0.98% | -0.94% | -0.92% | -0.76% |
| +1d best % | +14.75% | +14.75% | +14.75% | +14.75% |
| +1d worst % | -4.28% | -4.38% | -5.18% | -7.92% |
| +1d vs QQQ | +0.12% | -0.25% | -0.25% | -0.16% |
| +1d vs 10:30 first | +0.11R | -0.11R | -0.10R | -0.06R |
| +2d days | 60 | 58 | 58 | 58 |
| +2d fills | 60 | 116 | 174 | 574 |
| +2d avg % | +0.24% | -0.18% | -0.26% | -0.02% |
| +2d avg R | -0.06R | -0.33R | -0.34R | -0.16R |
| +2d win | 30.0% | 22.4% | 21.3% | 27.2% |
| +2d stop | 70.0% | 76.7% | 78.2% | 67.4% |
| +2d gaps | 4 | 8 | 14 | 59 |
| +2d total R | -3.7R | -38.3R | -58.4R | -90.3R |
| +2d expectancy | -0.06R | -0.33R | -0.34R | -0.16R |
| +2d avg MFE | +2.11R | +1.82R | +1.83R | +2.05R |
| +2d median R | -1.00R | -1.00R | -1.00R | -1.00R |
| +2d best R | +7.16R | +7.16R | +7.89R | +9.76R |
| +2d worst R | -3.77R | -3.77R | -3.77R | -6.53R |
| +2d median % | -1.02% | -1.10% | -1.14% | -0.96% |
| +2d best % | +12.13% | +12.13% | +18.92% | +19.13% |
| +2d worst % | -4.28% | -4.38% | -5.18% | -7.92% |
| +2d vs QQQ | +0.09% | -0.42% | -0.49% | -0.22% |
| +2d vs 10:30 first | -0.10R | -0.41R | -0.42R | -0.24R |
| +3d days | 60 | 58 | 58 | 58 |
| +3d fills | 60 | 116 | 174 | 574 |
| +3d avg % | +0.41% | -0.05% | -0.24% | -0.07% |
| +3d avg R | 0.00R | -0.26R | -0.33R | -0.21R |
| +3d win | 26.7% | 19.8% | 18.4% | 23.3% |
| +3d stop | 71.7% | 78.5% | 80.5% | 73.5% |
| +3d gaps | 4 | 8 | 15 | 66 |
| +3d total R | -0.2R | -29.8R | -57.6R | -118.9R |
| +3d expectancy | 0.00R | -0.26R | -0.33R | -0.21R |
| +3d avg MFE | +2.11R | +1.82R | +1.83R | +2.05R |
| +3d median R | -1.00R | -1.00R | -1.00R | -1.00R |
| +3d best R | +9.32R | +9.32R | +9.32R | +11.73R |
| +3d worst R | -3.77R | -3.77R | -3.77R | -6.63R |
| +3d median % | -1.05% | -1.15% | -1.20% | -1.09% |
| +3d best % | +15.78% | +15.78% | +15.78% | +16.20% |
| +3d worst % | -4.28% | -4.38% | -5.18% | -17.17% |
| +3d vs QQQ | +0.14% | -0.41% | -0.60% | -0.39% |
| +3d vs 10:30 first | -0.26R | -0.56R | -0.64R | -0.51R |
| +4d days | 59 | 57 | 57 | 57 |
| +4d fills | 59 | 114 | 171 | 564 |
| +4d avg % | -0.03% | -0.22% | -0.23% | -0.02% |
| +4d avg R | -0.17R | -0.31R | -0.30R | -0.17R |
| +4d win | 17.0% | 14.9% | 14.6% | 20.7% |
| +4d stop | 78.0% | 82.5% | 83.6% | 76.8% |
| +4d gaps | 6 | 10 | 16 | 67 |
| +4d total R | -10.1R | -35.6R | -50.5R | -96.3R |
| +4d expectancy | -0.17R | -0.31R | -0.30R | -0.17R |
| +4d avg MFE | +2.09R | +1.82R | +1.84R | +2.07R |
| +4d median R | -1.00R | -1.00R | -1.00R | -1.00R |
| +4d best R | +8.97R | +10.91R | +16.43R | +16.43R |
| +4d worst R | -3.77R | -3.77R | -3.77R | -9.20R |
| +4d median % | -1.15% | -1.18% | -1.20% | -1.13% |
| +4d best % | +15.41% | +15.41% | +15.41% | +20.44% |
| +4d worst % | -4.28% | -4.38% | -4.92% | -17.17% |
| +4d vs QQQ | -0.54% | -0.80% | -0.81% | -0.55% |
| +4d vs 10:30 first | -0.34R | -0.52R | -0.50R | -0.37R |
| +5d days | 59 | 57 | 57 | 57 |
| +5d fills | 59 | 114 | 171 | 564 |
| +5d avg % | +0.13% | -0.18% | -0.23% | +0.09% |
| +5d avg R | -0.04R | -0.27R | -0.30R | -0.13R |
| +5d win | 18.6% | 14.9% | 14.6% | 19.7% |
| +5d stop | 79.7% | 84.2% | 84.8% | 78.5% |
| +5d gaps | 7 | 11 | 17 | 70 |
| +5d total R | -2.5R | -30.6R | -52.1R | -71.7R |
| +5d expectancy | -0.04R | -0.27R | -0.30R | -0.13R |
| +5d avg MFE | +2.09R | +1.82R | +1.84R | +2.07R |
| +5d median R | -1.00R | -1.00R | -1.00R | -1.00R |
| +5d best R | +12.34R | +12.34R | +12.34R | +16.04R |
| +5d worst R | -3.77R | -3.77R | -3.77R | -9.20R |
| +5d median % | -1.15% | -1.21% | -1.22% | -1.17% |
| +5d best % | +20.61% | +20.61% | +20.61% | +27.14% |
| +5d worst % | -4.28% | -4.38% | -4.92% | -17.17% |
| +5d vs QQQ | -0.52% | -0.91% | -0.97% | -0.59% |
| +5d vs 10:30 first | -0.38R | -0.65R | -0.69R | -0.51R |
