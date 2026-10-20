"""Cost basis after partial sells.

break_even = (initial_shares * initial_buy_price - sum(trim_shares * trim_price)) / remaining_shares

Trim proceeds reduce the cost left on the shares still held. That can be zero
(the trims paid for the position) or negative (they paid more than it cost).

realized P/L = sum(trim_shares * (trim_price - initial_buy_price))
"""

from __future__ import annotations


def remaining_shares(initial_shares: float, trims: list[dict]) -> float:
    return initial_shares - sum(t["shares"] for t in trims)


def break_even(initial_shares: float, buy_price: float, trims: list[dict]) -> float:
    """Trim-adjusted cost basis of the shares still held. Equals buy_price when trims is empty."""
    remaining = remaining_shares(initial_shares, trims)
    proceeds = sum(t["shares"] * t["price"] for t in trims)
    return (initial_shares * buy_price - proceeds) / remaining


def realized_pnl(buy_price: float, trims: list[dict]) -> float:
    """Dollars booked by trims, versus the original buy price."""
    return sum(t["shares"] * (t["price"] - buy_price) for t in trims)


def annotate(position: dict, trims: list[dict]) -> dict:
    """Add remaining shares, break-even and realized P/L. Does not mutate the stored share count.

    ``shares`` stays the initial size. With no share count, break-even is the buy price
    (a trim cannot be recorded until shares are set).
    """
    trims = list(trims)
    initial = position.get("shares")
    buy = position["entry_price"]
    if initial is None:
        return {**position, "remaining_shares": None, "break_even": buy, "realized_pnl": 0.0, "trims": trims}
    remaining = remaining_shares(initial, trims)
    # A fully sold position is a close, not a row we keep. If bad data lands here, don't divide by zero.
    basis = buy if remaining <= 0 else break_even(initial, buy, trims)
    return {
        **position,
        "remaining_shares": remaining,
        "break_even": basis,
        "realized_pnl": realized_pnl(buy, trims),
        "trims": trims,
    }
