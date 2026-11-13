# Local order app: stop moves and trims

What the local order app needs to change to follow strat-scanner's crossback trades after the buy:
the intraday stop move and the thirds-ladder sells. strat-scanner only announces; the app places and
manages every order. The broker's fills are the truth. strat-scanner's prices are its own estimate.

## What strat-scanner now does

| Event | When | What to do |
|---|---|---|
| Buy | As before (alert triggers, before 12:00 ET) | Buy, `clientOrderId` = alert id. Place the protective stop at `stop_price`. |
| Stop move | Once, after the 3 15-minute bars that follow the trigger candle complete (about 45-60 min after the fill) | Replace the working stop with the new `stop_price` for the shares left. |
| Trim 1/3 | 15:59 ET on the entry day, every time | Sell a third. |
| Trim 1/3 | 15:59 ET on a later day, when price is under the daily 6 EMA | Sell a third. |
| Trim last 1/3 | 15:59 ET, when price is under the daily 20 EMA | Sell everything left (`close_all: true`). |

- Several thirds can come in the same 15:59 check (for example step 2 and step 3 together). Place each one.
- Positions are held **overnight**. There is no 16:00 exit any more. The stop has to survive the night,
  so make it GTC, or place it again before each open.
- strat-scanner does not alert a new buy on a symbol while it still holds a position there from an earlier day.
- Stop-outs are **not** announced. The app's own stop order handles them. When the broker says the
  position is flat, ignore any later trim or stop move for that alert.

## Order ids (idempotency)

| Order | `clientOrderId` |
|---|---|
| Buy | `<alert id>` |
| Stop move n | `<alert id>-s<n>` (n = 1, 2, …) |
| Trim step n | `<alert id>-t<n>` (n = 1, 2, 3) |

Use these ids on the broker orders. The broker rejects a duplicate, so a retry or a replayed message
never places the same order twice. Also keep a local set of ids already handled.

## Where to read it

### 1. Socket push (fast path)

On the `/ws` socket, the `alerts` message now has two lists next to `new` and `triggered`:

```json
{
  "type": "alerts",
  "new": [],
  "triggered": [],
  "trimmed": [
    {"id": 812, "symbol": "AMD", "setup": "6", "step": 1, "client_order_id": "812-t1"}
  ],
  "stop_moved": [
    {"id": 812, "symbol": "AMD", "setup": "6", "step": 1, "stop_price": 583.1, "client_order_id": "812-s1"}
  ]
}
```

The socket entries are notices. Before placing anything, read the full row (`trims[]` / `stops[]`
below) or the orders feed: the socket has no `frac`, `close_all` or price.

### 2. Orders feed (source of truth, poll it)

`GET /api/alerts/orders?session=YYYY-MM-DD` (default: today, Eastern). It lists one Eastern day's orders,
oldest first. A position held overnight shows its later trims on the day they happen.

```json
{"session": "2026-11-13", "orders": [
  {"kind": "buy",  "client_order_id": "812",    "alert_id": 812, "symbol": "AMD", "session": "2026-11-13",
   "side": "buy", "filled": true, "price": 580.51, "stop_price": 578.2, "status": "triggered", "at": "..."},
  {"kind": "stop", "client_order_id": "812-s1", "alert_id": 812, "symbol": "AMD", "side": "sell",
   "stop_price": 583.1, "previous_stop": 578.2, "reason": "low_of_3_bars", "step": 1, "at": "..."},
  {"kind": "trim", "client_order_id": "812-t1", "alert_id": 812, "symbol": "AMD", "side": "sell",
   "step": 1, "frac": 0.3333, "remaining_frac": 0.6667, "close_all": false, "price": 585.3,
   "reason": "trim_day_close", "ema": null, "late": false, "at": "..."}
]}
```

`/api/alerts` rows carry the same lists as `stops[]` and `trims[]`. A position held from an earlier
session appears in today's `/api/alerts` with `carried: true`.

`underlying` is set on inverse-ETF alerts. Trade the alert's `symbol` (the ETF), not the underlying.

## Changes to make in the app

1. **Track the original size per alert.** Store the filled share count of the buy (`<alert id>`).
   Trims are fractions of that original size.

2. **Handle `kind: "stop"`** (or `stop_moved` on the socket):
   - Skip it if the `client_order_id` was already handled, or the position is flat.
   - Skip it if `stop_price` is not above the stop that is working now (stops only move up).
   - Cancel or replace the working stop: new stop at `stop_price`, quantity = shares held now,
     `clientOrderId` = the stop move's id. Keep it GTC.
   - If the price is already under the new stop when the move arrives, sell what is left at market.

3. **Handle `kind: "trim"`** (or `trimmed` on the socket):
   - Skip it if already handled, or the position is flat.
   - Quantity: when `close_all` is true, every share left. Otherwise `round(original_shares * frac)`,
     capped at the shares held (and at least 1 while shares remain).
   - Send a **market** sell at once, `clientOrderId` = the trim's id. Trims arrive between 15:59:00 and
     about 15:59:30 ET. That is after the 15:50 market-on-close cutoff, so MOC/LOC orders are too late.
   - After the fill, resize the working stop to the shares left (cancel or replace at the same stop
     price). When nothing is left, cancel the stop.
   - `late: true` means the 15:59 pass was missed and the sell was decided after the close. Sell in
     extended hours with a limit near `price`, or at the next open. Pick one; strat-scanner treats it as
     filled at `price`.

4. **Poll at 15:59 ET.** Don't rely on the socket alone. From 15:59:00 to 16:00:00 ET, poll the orders
   feed every 5-10 s and act on any id not handled yet.

5. **Keep stops overnight.** Stops must be GTC, or re-placed before 09:30 ET every day, for every
   position still open. A gap through the stop fills at the open (strat-scanner assumes the same).

6. **Reconcile on start and each morning.** Read today's feed and any earlier day that still has an
   open position (its buy day and every day since; today's `/api/alerts` rows with `carried: true` name
   them). Place any id not handled yet. Use the broker's positions as the truth for share counts.

## Quick check

- After a buy, about 45-60 minutes later, expect one `<id>-s1` stop move, unless the 3-bar low is
  under the entry stop.
- At 15:59 on the buy day, expect `<id>-t1`: a third sold, two thirds held overnight with the stop.
- On a later day, `<id>-t2` comes on the first 15:59 under the daily 6 EMA and `<id>-t3` (`close_all`)
  on the first 15:59 under the daily 20 EMA.
