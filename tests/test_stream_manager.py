from __future__ import annotations

import asyncio

import pytest

from data.orderbook import OrderBookUpdate
from exchanges.stream_manager import MultiExchangeStreamManager, StreamSpec


class _FakeConnector:
    """Yields a fixed sequence of updates, then hangs -- no network involved."""

    def __init__(self, exchange: str, market_type: str, updates_per_symbol: int = 3) -> None:
        self.market_type = market_type
        self._exchange = exchange
        self._n = updates_per_symbol

    async def stream_order_books(self, symbols, depth=20):
        for i in range(self._n):
            for symbol in symbols:
                yield OrderBookUpdate(
                    exchange=self._exchange, market_type=self.market_type, symbol=symbol,
                    bids=((100.0 + i, 1.0),), asks=((101.0 + i, 1.0),), timestamp=float(i),
                )
        await asyncio.Event().wait()  # simulate a real connector that never terminates


@pytest.mark.asyncio
async def test_merges_updates_from_multiple_connectors():
    manager = MultiExchangeStreamManager(
        [
            StreamSpec(_FakeConnector("deribit", "perpetual"), ["BTC-PERPETUAL"]),
            StreamSpec(_FakeConnector("binance", "spot"), ["BTCUSDT", "ETHUSDT"]),
        ]
    )
    seen = []
    async for update in manager.stream():
        seen.append(update.key)
        if len(seen) >= 9:  # 3 from deribit + 3*2 from binance
            break
    await manager.stop()

    assert ("deribit", "perpetual", "BTC-PERPETUAL") in seen
    assert ("binance", "spot", "BTCUSDT") in seen
    assert ("binance", "spot", "ETHUSDT") in seen
    assert len(seen) == 9


@pytest.mark.asyncio
async def test_stream_stops_cleanly_and_cancels_tasks():
    manager = MultiExchangeStreamManager([StreamSpec(_FakeConnector("deribit", "perpetual"), ["BTC-PERPETUAL"])])
    gen = manager.stream()
    await gen.__anext__()
    await gen.aclose()
    for t in manager._tasks:
        assert t.cancelled() or t.done()


@pytest.mark.asyncio
async def test_single_connector_dying_does_not_crash_the_manager():
    class _DyingConnector:
        market_type = "perpetual"

        async def stream_order_books(self, symbols, depth=20):
            raise RuntimeError("simulated connector crash")
            yield  # pragma: no cover -- makes this an async generator

    manager = MultiExchangeStreamManager(
        [
            StreamSpec(_DyingConnector(), ["BTC-PERPETUAL"]),
            StreamSpec(_FakeConnector("binance", "spot"), ["BTCUSDT"]),
        ]
    )
    seen = []
    async for update in manager.stream():
        seen.append(update.key)
        if len(seen) >= 3:
            break
    await manager.stop()
    assert all(key[0] == "binance" for key in seen)
