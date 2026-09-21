from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RestingOrder:
    """A quote we're resting in the book, with an estimated queue position."""
    price: float
    side: str  # 'bid' | 'ask'
    size: float
    remaining_ahead: float  # size that must trade at this price before we start filling


@dataclass(frozen=True)
class QueueFillResult:
    filled_size: float
    remaining_ahead: float
    fully_consumed: bool  # once True, any further trade at this price fills us immediately


def process_trade_against_order(order: RestingOrder, trade_price: float, trade_amount: float) -> QueueFillResult:
    """
    FIFO queue-position approximation (documented simplification, not full
    L3 message-level precision -- we don't observe individual cancels ahead
    of us, only aggregate resting size at the price when we joined):

    - A trade that doesn't reach our price at all: no effect.
    - A trade that prints *through* our price (deeper than where we rest --
      below our bid, or above our ask): the market necessarily consumed
      everything resting at our level first, so we're fully filled.
    - A trade that prints *exactly* at our price: consumes remaining_ahead
      first (FIFO -- orders placed before us get filled first); once
      remaining_ahead is exhausted, further volume from the same or later
      trades at this price fills us, up to our own order size.

    This replaces the earlier crossing-based approximation (any book update
    where the market's top-of-book merely touched our price = instant full
    fill), which didn't distinguish "we're 50th in line" from "we're next."
    """
    if order.side == "bid":
        crosses = trade_price <= order.price
        walked_through = trade_price < order.price
    else:
        crosses = trade_price >= order.price
        walked_through = trade_price > order.price

    if not crosses:
        return QueueFillResult(filled_size=0.0, remaining_ahead=order.remaining_ahead, fully_consumed=order.remaining_ahead <= 0.0)

    if walked_through:
        return QueueFillResult(filled_size=order.size, remaining_ahead=0.0, fully_consumed=True)

    if order.remaining_ahead > 0.0:
        consumed = min(trade_amount, order.remaining_ahead)
        new_ahead = order.remaining_ahead - consumed
        leftover = trade_amount - consumed
        filled = min(order.size, leftover) if new_ahead <= 0.0 else 0.0
        return QueueFillResult(filled_size=filled, remaining_ahead=max(new_ahead, 0.0), fully_consumed=new_ahead <= 0.0)

    filled = min(order.size, trade_amount)
    return QueueFillResult(filled_size=filled, remaining_ahead=0.0, fully_consumed=True)


class QueueTracker:
    """
    Stateful wrapper: one RestingOrder per (instrument, side, level) key --
    level defaults to 0 for single-level (option) quoting, and is 0..N-1 for
    a multi-level ladder (see core/models/ladder.py), tightest first.
    place_order() resets queue position whenever we requote a given level (a
    new price means a new position at the back of a new queue).

    Multiple levels of the same side are always at *distinct* prices (the
    ladder's kappa-derived gap is > 0), so a single trade can be checked
    against every level independently with the exact same (trade_price,
    trade_amount) -- no leftover-volume bookkeeping needs to cascade between
    levels. A trade that walks through a deep level necessarily also walks
    through every shallower level at the *same* price comparison, and a
    trade printing exactly at one level's price can't simultaneously match
    a different level's (distinct) price, so there's no double-counting.
    """

    def __init__(self) -> None:
        self._orders: dict[tuple[str, str, int], RestingOrder] = {}

    def place_order(self, instrument: str, side: str, price: float, size: float, size_ahead: float, level: int = 0) -> None:
        self._orders[(instrument, side, level)] = RestingOrder(price=price, side=side, size=size, remaining_ahead=size_ahead)

    def clear_order(self, instrument: str, side: str, level: int = 0) -> None:
        self._orders.pop((instrument, side, level), None)

    def clear_side(self, instrument: str, side: str) -> None:
        """Remove every level resting on `side` -- used before requoting a ladder to a fresh level count/prices."""
        for key in [k for k in self._orders if k[0] == instrument and k[1] == side]:
            del self._orders[key]

    def on_trade(self, instrument: str, trade_price: float, trade_amount: float) -> list[tuple[str, int, float]]:
        """
        Feed a real trade to every resting level (both sides) for `instrument`.
        Returns [(side, level, filled_size), ...] for any level that filled
        (partially or fully) on this trade. A filled level is cleared
        (assumes full consumption at our quoted size, not partial resting
        after a fill -- matches this project's convention elsewhere of
        "small resting size vs. real trade size").
        """
        fills = []
        for key in [k for k in self._orders if k[0] == instrument]:
            _, side, level = key
            order = self._orders[key]
            result = process_trade_against_order(order, trade_price, trade_amount)
            if result.filled_size > 0.0:
                fills.append((side, level, result.filled_size))
                del self._orders[key]
            else:
                self._orders[key] = RestingOrder(
                    price=order.price, side=order.side, size=order.size, remaining_ahead=result.remaining_ahead
                )
        return fills
