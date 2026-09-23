from __future__ import annotations

from dataclasses import dataclass

from core.strategies.market_maker import QuoteDecision
from data.orderbook import OrderBookUpdate


@dataclass(frozen=True)
class PaperFill:
    side: str  # 'bid' | 'ask'
    price: float
    size: float
    liquidity: str = "maker"  # 'maker' | 'taker' -- resting quote hit vs. crossing the book ourselves


def check_fill(resting_quote: QuoteDecision, book: OrderBookUpdate) -> list[PaperFill]:
    """
    Crossing-based paper fill: no live trade tape is wired into this engine
    (only L2 top-of-book), so a resting bid is considered filled when the
    market's own best ask has moved to or below it -- real sell pressure has
    pushed the market through our level, the same conservative proxy
    core.backtest.historical uses for the (there, real) trade tape. Same
    logic, mirrored, for a resting ask against the market's best bid.

    This does not model queue position or partial fills: a crossed quote
    fills in full at the *quoted* price (price-improvement toward the
    counterparty isn't modelled either way). Optimistic in the same
    documented sense as the historical backtest engine.
    """
    fills: list[PaperFill] = []
    if not resting_quote.skip_bid and resting_quote.bid_size > 0.0 and book.best_ask <= resting_quote.bid_price:
        fills.append(PaperFill(side="bid", price=resting_quote.bid_price, size=resting_quote.bid_size))
    if not resting_quote.skip_ask and resting_quote.ask_size > 0.0 and book.best_bid >= resting_quote.ask_price:
        fills.append(PaperFill(side="ask", price=resting_quote.ask_price, size=resting_quote.ask_size))
    return fills
