from __future__ import annotations

from typing import AsyncIterator, Protocol

from data.orderbook import OrderBookUpdate


class OrderBookConnector(Protocol):
    """
    Interface every exchange connector implements. exchanges/stream_manager.py
    only depends on this -- it doesn't know or care whether a given stream is
    Deribit or Binance, spot or perpetual.
    """

    market_type: str

    def stream_order_books(self, symbols: list[str], depth: int = 20) -> AsyncIterator[OrderBookUpdate]:
        """
        Yield an OrderBookUpdate every time any of `symbols` updates.
        Must never raise on a transient connection drop -- reconnect and keep
        yielding. Only raise for a programming error (e.g. an unknown symbol).
        """
        ...
