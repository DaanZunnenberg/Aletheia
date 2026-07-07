from __future__ import annotations

import time
from typing import AsyncIterator

import ccxt.pro as ccxtpro

from exchange.base import BaseConnector, OrderBookSnapshot, Trade


class BinanceConnector(BaseConnector):
    def __init__(self, api_key: str = "", api_secret: str = "") -> None:
        self._exchange = ccxtpro.binance({
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        })

    async def watch_order_book(self, symbol: str, depth: int = 20) -> AsyncIterator[OrderBookSnapshot]:
        while True:
            ob = await self._exchange.watch_order_book(symbol, depth)
            yield OrderBookSnapshot(
                symbol=symbol,
                bids=[(float(p), float(q)) for p, q in ob["bids"][:depth]],
                asks=[(float(p), float(q)) for p, q in ob["asks"][:depth]],
                timestamp=ob["timestamp"] or time.time() * 1000,
            )

    async def watch_trades(self, symbol: str) -> AsyncIterator[Trade]:
        while True:
            trades = await self._exchange.watch_trades(symbol)
            for t in trades:
                yield Trade(
                    symbol=symbol,
                    price=float(t["price"]),
                    qty=float(t["amount"]),
                    side=t["side"],
                    timestamp=float(t["timestamp"]),
                )

    async def close(self) -> None:
        await self._exchange.close()
