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
    Stateful wrapper: one RestingOrder per (instrument, side) key, updated as
    real trades arrive. place_order() resets queue position whenever we
    requote (a new price means a new position at the back of a new queue).
    """

    def __init__(self) -> None:
        self._orders: dict[tuple[str, str], RestingOrder] = {}

    def place_order(self, instrument: str, side: str, price: float, size: float, size_ahead: float) -> None:
        self._orders[(instrument, side)] = RestingOrder(price=price, side=side, size=size, remaining_ahead=size_ahead)

    def clear_order(self, instrument: str, side: str) -> None:
        self._orders.pop((instrument, side), None)

    def on_trade(self, instrument: str, trade_price: float, trade_amount: float) -> list[tuple[str, float]]:
        """
        Feed a real trade to both sides' resting orders for `instrument`.
        Returns [(side, filled_size), ...] for any side that filled (partially
        or fully) on this trade. A filled order is cleared (assumes full
        consumption at our quoted size, not partial resting after a fill --
        matches this project's convention elsewhere of "small resting size
        vs. real trade size").
        """
        fills = []
        for side in ("bid", "ask"):
            order = self._orders.get((instrument, side))
            if order is None:
                continue
            result = process_trade_against_order(order, trade_price, trade_amount)
            if result.filled_size > 0.0:
                fills.append((side, result.filled_size))
                self.clear_order(instrument, side)
            else:
                self._orders[(instrument, side)] = RestingOrder(
                    price=order.price, side=order.side, size=order.size, remaining_ahead=result.remaining_ahead
                )
        return fills
