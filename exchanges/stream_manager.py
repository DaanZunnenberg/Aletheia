from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import AsyncIterator

from data.orderbook import OrderBookUpdate
from exchanges.base import OrderBookConnector
from utils.logger import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class StreamSpec:
    """One connector's worth of symbols, fanned out as one asyncio task."""
    connector: OrderBookConnector
    symbols: list[str]
    depth: int = 20


class MultiExchangeStreamManager:
    """
    Runs an arbitrary number of exchange connectors concurrently -- any mix
    of exchanges, market types, and coins -- and merges their updates into a
    single async stream, tagged by (exchange, market_type, symbol) so a
    consumer can tell them apart.

    Each StreamSpec becomes one asyncio task feeding a shared queue; a
    connector dying (it shouldn't -- connectors handle their own reconnects)
    doesn't take down the others, since each pump task catches and logs
    rather than propagating.

    Usage:
        manager = MultiExchangeStreamManager([
            StreamSpec(DeribitOrderBookConnector(), ["BTC-PERPETUAL", "ETH-PERPETUAL"]),
            StreamSpec(BinanceOrderBookConnector("perpetual"), ["BTCUSDT", "ETHUSDT"]),
            StreamSpec(BinanceOrderBookConnector("spot"), ["BTCUSDT", "ETHUSDT"]),
        ])
        async for update in manager.stream():
            ...
    """

    def __init__(self, specs: list[StreamSpec], queue_maxsize: int = 10_000) -> None:
        self._specs = specs
        self._queue: asyncio.Queue[OrderBookUpdate] = asyncio.Queue(maxsize=queue_maxsize)
        self._tasks: list[asyncio.Task] = []

    async def _pump(self, spec: StreamSpec) -> None:
        try:
            async for update in spec.connector.stream_order_books(spec.symbols, spec.depth):
                await self._queue.put(update)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception(
                "stream manager: pump task for %s %s died unexpectedly (connector should have retried internally)",
                type(spec.connector).__name__, spec.symbols,
            )

    async def stream(self) -> AsyncIterator[OrderBookUpdate]:
        self._tasks = [asyncio.create_task(self._pump(spec)) for spec in self._specs]
        log.info("stream manager: started %d concurrent connector task(s)", len(self._tasks))
        try:
            while True:
                yield await self._queue.get()
        finally:
            for t in self._tasks:
                t.cancel()
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
