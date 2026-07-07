from __future__ import annotations

import asyncio
from typing import AsyncIterator

import orjson
import websockets
from websockets.exceptions import ConnectionClosed

from exchange.base import BaseConnector, OrderBookSnapshot, Trade
from utils.logger import get_logger

log = get_logger(__name__)

# Deribit only accepts these depth values in the channel name.
_VALID_DEPTHS = (1, 5, 10, 20)


def _nearest_depth(requested: int) -> int:
    """Return the smallest valid depth that is >= requested, or 20 if none qualifies."""
    for d in _VALID_DEPTHS:
        if d >= requested:
            return d
    return 20


class DeribitConnector(BaseConnector):
    _WS_URL = "wss://www.deribit.com/ws/api/v2"
    _WS_TEST_URL = "wss://test.deribit.com/ws/api/v2"

    def __init__(self, api_key: str = "", api_secret: str = "", testnet: bool = False) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._url = self._WS_TEST_URL if testnet else self._WS_URL

    # ------------------------------------------------------------------
    # Order book
    # ------------------------------------------------------------------

    async def watch_order_book(self, symbol: str, depth: int = 20) -> AsyncIterator[OrderBookSnapshot]:
        while True:
            try:
                async for snap in self._book_stream(symbol, depth):
                    yield snap
            except (ConnectionClosed, OSError) as exc:
                log.warning("book stream dropped (%s) — reconnecting in 1 s", exc)
                await asyncio.sleep(1)

    async def _book_stream(self, symbol: str, depth: int) -> AsyncIterator[OrderBookSnapshot]:
        slot = _nearest_depth(depth)
        channel = f"book.{symbol}.none.{slot}.100ms"

        bids: dict[float, float] = {}
        asks: dict[float, float] = {}
        last_change_id: int | None = None

        async with websockets.connect(self._url, ping_interval=None) as ws:
            await ws.send(orjson.dumps({
                "jsonrpc": "2.0",
                "method": "public/subscribe",
                "params": {"channels": [channel]},
                "id": 1,
            }))

            async for raw in ws:
                msg = orjson.loads(raw)

                # Respond to application-level heartbeat pings.
                if msg.get("method") == "heartbeat":
                    if msg["params"].get("type") == "test_request":
                        await ws.send(orjson.dumps({
                            "jsonrpc": "2.0",
                            "method": "public/test",
                            "params": {},
                            "id": 0,
                        }))
                    continue

                if msg.get("method") != "subscription":
                    continue  # subscribe confirmation, errors, etc.

                data = msg["params"]["data"]

                if data["type"] == "snapshot":
                    bids = {float(p): float(q) for p, q in data["bids"]}
                    asks = {float(p): float(q) for p, q in data["asks"]}
                    last_change_id = data["change_id"]

                elif data["type"] == "change":
                    if last_change_id is None or data["prev_change_id"] != last_change_id:
                        # Sequence gap — drop state and wait for the next snapshot.
                        bids.clear()
                        asks.clear()
                        last_change_id = None
                        continue

                    for action, price, qty in data["bids"]:
                        p = float(price)
                        if action == "delete" or qty == 0:
                            bids.pop(p, None)
                        else:
                            bids[p] = float(qty)

                    for action, price, qty in data["asks"]:
                        p = float(price)
                        if action == "delete" or qty == 0:
                            asks.pop(p, None)
                        else:
                            asks[p] = float(qty)

                    last_change_id = data["change_id"]

                else:
                    continue

                if not bids or not asks:
                    continue

                yield OrderBookSnapshot(
                    symbol=symbol,
                    bids=sorted(bids.items(), reverse=True)[:depth],
                    asks=sorted(asks.items())[:depth],
                    timestamp=float(data["timestamp"]),
                )

    # ------------------------------------------------------------------
    # Trades
    # ------------------------------------------------------------------

    async def watch_trades(self, symbol: str) -> AsyncIterator[Trade]:
        while True:
            try:
                async for trade in self._trade_stream(symbol):
                    yield trade
            except (ConnectionClosed, OSError) as exc:
                log.warning("trade stream dropped (%s) — reconnecting in 1 s", exc)
                await asyncio.sleep(1)

    async def _trade_stream(self, symbol: str) -> AsyncIterator[Trade]:
        channel = f"trades.{symbol}.100ms"

        async with websockets.connect(self._url, ping_interval=None) as ws:
            await ws.send(orjson.dumps({
                "jsonrpc": "2.0",
                "method": "public/subscribe",
                "params": {"channels": [channel]},
                "id": 2,
            }))

            async for raw in ws:
                msg = orjson.loads(raw)

                if msg.get("method") == "heartbeat":
                    if msg["params"].get("type") == "test_request":
                        await ws.send(orjson.dumps({
                            "jsonrpc": "2.0",
                            "method": "public/test",
                            "params": {},
                            "id": 0,
                        }))
                    continue

                if msg.get("method") != "subscription":
                    continue

                for t in msg["params"]["data"]:
                    yield Trade(
                        symbol=symbol,
                        price=float(t["price"]),
                        qty=float(t["amount"]),
                        side=t["direction"],   # Deribit uses 'direction', not 'side'
                        timestamp=float(t["timestamp"]),
                    )

    async def close(self) -> None:
        pass  # Connections are scoped to each stream task; nothing to tear down globally.
