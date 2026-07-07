from __future__ import annotations

import asyncio
from typing import Callable

from exchange.base import BaseConnector, OrderBookSnapshot, Trade
from utils.logger import get_logger

log = get_logger(__name__)


class MarketDataFeed:
    def __init__(self, connector: BaseConnector) -> None:
        self._connector = connector
        self._ob_handlers: list[Callable[[OrderBookSnapshot], None]] = []
        self._trade_handlers: list[Callable[[Trade], None]] = []

    def on_order_book(self, handler: Callable[[OrderBookSnapshot], None]) -> None:
        self._ob_handlers.append(handler)

    def on_trade(self, handler: Callable[[Trade], None]) -> None:
        self._trade_handlers.append(handler)

    async def run(self, symbol: str, depth: int = 20) -> None:
        await asyncio.gather(
            self._stream_order_book(symbol, depth),
            self._stream_trades(symbol),
        )

    async def _stream_order_book(self, symbol: str, depth: int) -> None:
        async for snapshot in self._connector.watch_order_book(symbol, depth):
            for handler in self._ob_handlers:
                handler(snapshot)

    async def _stream_trades(self, symbol: str) -> None:
        async for trade in self._connector.watch_trades(symbol):
            for handler in self._trade_handlers:
                handler(trade)
