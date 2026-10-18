# Morning leaders

Which of the five morning check-ins is the best time to buy the leaders that have qualified.
Leaders are the scanner's top 10 stocks as of the **prior close**. A name is bought only after a
5-minute bar has closed above its 20-period RMA. Nothing here looks ahead.

A name is bought at a check-in only after a 5-minute bar has closed above its 20-period RMA (Wilder smoothing, the same average as TradingView ta.rma). Earlier sessions warm that average so it is valid at the open; they do not count as the cross. The earliest cross is bought first. The entry is the close of the 5-minute bar that ends at the check-in. The stop is the low of the session from 9:30 through that bar.

## What was collected

- Leader sessions stored: 251 (2510 rows).
- 5-minute bars stored: 247806 (2026-07-24T09:35:00 → 2026-10-16T16:00:00).
- 15-minute bars stored: 199653 (2026-07-24T09:45:00 → 2026-10-16T16:00:00).
- Bar sources: {'yahoo': 128}.
- Sessions with entry results: 59.
- Yahoo 5-minute and 15-minute history is about the last 59 calendar days (`period=60d`, 60 sessions). Older sessions keep their leader snapshot.

Sample-size caveat: the names bought in one morning move together, so 40 mornings are not 400 independent bets.
The win rate and expectancy below are the equal-weight basket of the names that qualified, one number per morning.
Mornings when nobody had crossed are left out of the return columns and included in the qualified average.
A split inside the hold is adjusted out; it is not a loss.

## By check-in

Qualified is the average number of the top 10 that had closed above the 20 RMA by that check-in, including mornings when the count was zero.
EOD through +5d are close-to-close holds of the names that were bought. Expectancy replaces the close with the low-of-day stop once a later bar has traded below it.
The stop is the session low from 9:30 through the entry bar. 9:45 is the earliest buy. QQQ is the same clock-time hold, without a stop. vs QQQ is the basket minus that hold.

| Window | Days | Qualified | EOD | +1d | +3d | +5d | Win +3d | Stop hit | Expectancy +3d | vs QQQ +3d |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 09:45 | 56 | 6.3 | +0.08% | +0.21% | +0.59% | +1.05% | 66.1% | 78.4% | -0.01% | +0.15% |
| 10:00 | 56 | 6.9 | +0.01% | +0.01% | +0.26% | +0.67% | 62.5% | 75.3% | -0.13% | -0.16% |
| 10:15 | 56 | 7.2 | +0.12% | +0.15% | +0.39% | +0.72% | 64.3% | 75.1% | -0.09% | -0.11% |
| 10:30 | 56 | 7.5 | +0.10% | +0.12% | +0.37% | +0.68% | 58.9% | 73.7% | -0.01% | -0.08% |
| 10:45 | 56 | 7.7 | +0.07% | +0.12% | +0.37% | +0.67% | 60.7% | 73.4% | -0.04% | -0.09% |

## Best time to buy leaders

**09:45** has the highest average +3d close return: +0.59% per morning (66.1% of mornings positive, n = 56 mornings / 366 fills).

On average 6.3 of the ten leaders had closed above the 20 RMA by 09:45.

A stop at the low of day through that bar was hit 78.4% of the time by +3d. The stop-aware expectancy is -0.01%.

Against holding QQQ from the same minute: +0.15%.

That is a description of this sample, not a promise. Overlapping holds, a short window, and today's index membership (survivorship) all apply.
