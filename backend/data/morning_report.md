# Morning leaders

Which of the five morning check-ins is the best time to buy that day's leaders.
Leaders are the scanner's top 10 stocks as of the **prior close**. The check-in rank uses only
the 15-minute bars that have closed by that time. Nothing here looks ahead.

Best at a check-in is the leader with the highest score from information known when that 15-minute candle closes: 1 × the percent move from the session open, 1 × that move minus QQQ's move, and 1 × where the close sits in the opening range so far (+1 at the high, −1 at the low). The entry is that candle's close. The stop is that candle's low.

## What was collected

- Leader sessions stored: 251 (2510 rows).
- 15-minute bars stored: 199653 (2026-07-24T09:45:00 → 2026-10-16T16:00:00).
- Bar sources: {'yahoo': 128}.
- Sessions with entry results: 60.
- Yahoo 15-minute history is about the last 59 calendar days. Older sessions keep their leader snapshot and, once a backfill provider has filled them, their bars.

Sample-size caveat: each morning's ten names move together, so 40 mornings are not 400 independent bets.
The win rate and expectancy below are computed on the equal-weight basket of the day's top 10, one number per morning.
A split inside the hold is adjusted out; it is not a loss.

## By check-in

EOD through +5d are close-to-close holds (no stop). Expectancy replaces the close with the candle-low stop once that low has been hit.
The open row buys every leader at the session open. QQQ is the same clock-time hold. vs QQQ is the basket minus that hold.

| Window | Days | EOD | +1d | +3d | +5d | Win +3d | Stop hit | Expectancy +3d | vs open +3d | vs QQQ +3d |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Open | 247 | +0.03% | +0.27% | +1.08% | +1.88% | 59.9% | — | +1.08% | — | +0.83% |
| 09:45 | 57 | -0.14% | -0.06% | +0.38% | +1.04% | 63.2% | 81.1% | -0.08% | -0.33% | +0.02% |
| 10:00 | 57 | -0.12% | -0.07% | +0.37% | +1.03% | 59.7% | 90.9% | -0.16% | -0.34% | +0.02% |
| 10:15 | 57 | +0.02% | +0.08% | +0.53% | +1.18% | 63.2% | 93.1% | -0.02% | -0.18% | +0.10% |
| 10:30 | 57 | +0.00% | +0.05% | +0.49% | +1.14% | 59.7% | 94.5% | -0.00% | -0.22% | +0.11% |
| 10:45 | 57 | +0.02% | +0.07% | +0.52% | +1.16% | 61.4% | 95.2% | -0.03% | -0.20% | +0.12% |

The open row is 247 mornings of daily data. The five check-ins are 57 mornings, which is as far as the 15-minute bars go. "vs open" and "vs QQQ" use only the mornings both sides have.


## Best time to buy leaders

**10:15** has the highest average +3d close return: +0.53% per morning (63.2% of mornings positive, n = 57 mornings / 570 fills).

A stop at that candle's low was hit 93.1% of the time by +3d. The stop-aware expectancy is -0.02%. The stop is one 15-minute wick, so it sits close to the fill.

Against buying the same names at the open: -0.18%. Against holding QQQ from the same minute: +0.10%.

That is a description of this sample, not a promise. Overlapping holds, a short window, and today's index membership (survivorship) all apply.

## Weights

- Move from the open: 1.0
- Excess versus QQQ: 1.0
- Opening-range position: 1.0

Change them with `STRAT_MORNING_W_MOVE`, `STRAT_MORNING_W_QQQ` and `STRAT_MORNING_W_OR`, then `npm run morning:backfill` to rebuild ranks and outcomes from the stored bars.
