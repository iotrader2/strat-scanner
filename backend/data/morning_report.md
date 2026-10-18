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
