from __future__ import annotations

import asyncio
from typing import Callable

from deribit.connector import DeribitConnector
from deribit.types import (
    FundingRate, IndexPrice, OptionMarkPrice, OrderBookSnapshot,
    Ticker, Trade, VolatilityIndex,
)
from utils.logger import get_logger

log = get_logger(__name__)


class DeribitFeed:
    """
    Callback dispatcher over DeribitConnector streams.

    Register handlers with on_*() then await the relevant run_*() coroutines,
    combining them with asyncio.gather() to run multiple streams concurrently.

    Example
    -------
    feed = DeribitFeed(connector)
    feed.on_order_book(lambda snap: ...)
    feed.on_trade(lambda trade: ...)
    await asyncio.gather(
        feed.run_order_book("BTC-PERPETUAL"),
        feed.run_trades("BTC-PERPETUAL"),
    )
    """

    def __init__(self, connector: DeribitConnector) -> None:
        self._c = connector
        self._ob_handlers:     list[Callable[[OrderBookSnapshot], None]] = []
        self._trade_handlers:  list[Callable[[Trade], None]] = []
        self._ticker_handlers: list[Callable[[Ticker], None]] = []
        self._index_handlers:  list[Callable[[IndexPrice], None]] = []
        self._dvol_handlers:   list[Callable[[VolatilityIndex], None]] = []
        self._mark_handlers:   list[Callable[[list[OptionMarkPrice]], None]] = []
        self._fund_handlers:   list[Callable[[FundingRate], None]] = []

    def on_order_book(self, h: Callable[[OrderBookSnapshot], None]) -> None:
        self._ob_handlers.append(h)

    def on_trade(self, h: Callable[[Trade], None]) -> None:
        self._trade_handlers.append(h)

    def on_ticker(self, h: Callable[[Ticker], None]) -> None:
        self._ticker_handlers.append(h)

    def on_index(self, h: Callable[[IndexPrice], None]) -> None:
        self._index_handlers.append(h)

    def on_volatility_index(self, h: Callable[[VolatilityIndex], None]) -> None:
        self._dvol_handlers.append(h)

    def on_mark_prices(self, h: Callable[[list[OptionMarkPrice]], None]) -> None:
        self._mark_handlers.append(h)

    def on_funding(self, h: Callable[[FundingRate], None]) -> None:
        self._fund_handlers.append(h)

    # ------------------------------------------------------------------

    async def run_order_book(self, instrument: str, depth: int = 20) -> None:
        async for snap in self._c.watch_order_book(instrument, depth):
            for h in self._ob_handlers:
                h(snap)

    async def run_trades(self, instrument: str) -> None:
        async for trade in self._c.watch_trades(instrument):
            for h in self._trade_handlers:
                h(trade)

    async def run_ticker(self, instrument: str) -> None:
        async for ticker in self._c.watch_ticker(instrument):
            for h in self._ticker_handlers:
                h(ticker)

    async def run_index(self, index_name: str) -> None:
        """Stream spot index price. index_name examples: 'btc_usd', 'eth_usd', 'sol_usd'."""
        async for idx in self._c.watch_index(index_name):
            for h in self._index_handlers:
                h(idx)

    async def run_volatility_index(self, index_name: str) -> None:
        """Stream DVOL. index_name examples: 'btc_dvol', 'eth_dvol'."""
        async for dvol in self._c.watch_volatility_index(index_name):
            for h in self._dvol_handlers:
                h(dvol)

    async def run_mark_prices(self, index_name: str) -> None:
        """Stream mark prices for ALL options on an index. index_name: 'btc_usd', 'eth_usd'."""
        async for prices in self._c.watch_mark_prices(index_name):
            for h in self._mark_handlers:
                h(prices)

    async def run_funding(self, instrument: str) -> None:
        """Stream perpetual funding rate. instrument must be a PERPETUAL."""
        async for rate in self._c.watch_funding(instrument):
            for h in self._fund_handlers:
                h(rate)
