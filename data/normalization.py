from __future__ import annotations

from deribit.types import OrderBookSnapshot, Ticker
from core.market_state import MarketState


def build_market_state(ticker: Ticker, book: OrderBookSnapshot) -> MarketState:
    best_bid_price, best_bid_size = book["bids"][0] if book["bids"] else (ticker["best_bid_price"], 0.0)
    best_ask_price, best_ask_size = book["asks"][0] if book["asks"] else (ticker["best_ask_price"], 0.0)
    return MarketState(
        instrument_name=ticker["instrument_name"],
        best_bid_price=best_bid_price,
        best_ask_price=best_ask_price,
        best_bid_size=best_bid_size,
        best_ask_size=best_ask_size,
        mark_price=ticker["mark_price"],
        index_price=ticker["index_price"],
        current_funding=ticker["current_funding"],
        timestamp=ticker["timestamp"],
    )
