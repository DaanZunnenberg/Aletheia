from __future__ import annotations

import asyncio
from typing import AsyncIterator

import aiohttp
import orjson

from data.orderbook import OrderBookUpdate
from utils.logger import get_logger

log = get_logger(__name__)

_WS_LIVE = "wss://www.deribit.com/ws/api/v2"
_WS_TEST = "wss://test.deribit.com/ws/api/v2"

_HB_REPLY = orjson.dumps({"jsonrpc": "2.0", "method": "public/test", "params": {}, "id": 0}).decode()


class DeribitOrderBookConnector:
    """
    Multi-instrument L2 order-book streaming over a single WebSocket
    connection: Deribit's public/subscribe accepts a list of channels, so
    N instruments cost one connection, not N.

    Deribit's book.{instrument}.100ms channel sends a full snapshot once,
    then incremental [action, price, qty] deltas keyed by a monotonic
    change_id. This maintains one local book per instrument and detects
    change_id gaps (dropped messages) explicitly -- a gap invalidates that
    instrument's book, which is cleared and rebuilt from the next snapshot
    rather than silently drifting out of sync with the real book.

    Deribit's book.* channel is generic across instrument kinds -- the same
    subscription mechanics work for a perpetual, a dated future, or an
    option. market_type is a constructor parameter purely for tagging the
    resulting OrderBookUpdate (data/orderbook.py's MarketType), it doesn't
    change how this connector talks to Deribit at all. Passing "option"
    instrument names (e.g. "BTC-26SEP26-80000-C") streams their L2 books
    exactly the same way; option premiums arrive BTC/ETH-denominated
    (Deribit's inverse quoting), not USD -- this connector does not convert
    that, same caveat as core.models.options.black76.
    """

    def __init__(self, testnet: bool = False, market_type: str = "perpetual") -> None:
        self._url = _WS_TEST if testnet else _WS_LIVE
        self.market_type = market_type

    async def stream_order_books(self, symbols: list[str], depth: int = 20) -> AsyncIterator[OrderBookUpdate]:
        channels = [f"book.{s}.100ms" for s in symbols]
        sub = orjson.dumps(
            {"jsonrpc": "2.0", "method": "public/subscribe", "params": {"channels": channels}, "id": 1}
        ).decode()

        books: dict[str, dict[str, dict[float, float]]] = {s: {"bids": {}, "asks": {}} for s in symbols}
        change_ids: dict[str, int | None] = {s: None for s in symbols}

        while True:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(self._url, heartbeat=30) as ws:
                        await ws.send_str(sub)
                        log.info("deribit: subscribed to %d book channels", len(channels))
                        async for msg in ws:
                            if msg.type != aiohttp.WSMsgType.TEXT:
                                if msg.type in (
                                    aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED,
                                ):
                                    log.warning("deribit: WS closed (%s) — reconnecting in 1s", ws.exception())
                                    break
                                continue

                            envelope = orjson.loads(msg.data)
                            if envelope.get("method") == "heartbeat":
                                if envelope.get("params", {}).get("type") == "test_request":
                                    await ws.send_str(_HB_REPLY)
                                continue
                            if envelope.get("method") != "subscription":
                                continue

                            channel = envelope["params"]["channel"]
                            data = envelope["params"]["data"]
                            instrument = channel.split(".")[1]
                            if "type" not in data:
                                continue

                            book = books[instrument]
                            if data["type"] == "snapshot":
                                book["bids"] = {float(p): float(q) for _, p, q in data["bids"]}
                                book["asks"] = {float(p): float(q) for _, p, q in data["asks"]}
                                change_ids[instrument] = data["change_id"]
                            elif data["type"] == "change":
                                if change_ids[instrument] is None or data["prev_change_id"] != change_ids[instrument]:
                                    log.warning(
                                        "deribit: change_id gap for %s — clearing book, awaiting snapshot",
                                        instrument,
                                    )
                                    book["bids"].clear()
                                    book["asks"].clear()
                                    change_ids[instrument] = None
                                    continue
                                for action, price, qty in data["bids"]:
                                    p = float(price)
                                    if action == "delete":
                                        book["bids"].pop(p, None)
                                    else:
                                        book["bids"][p] = float(qty)
                                for action, price, qty in data["asks"]:
                                    p = float(price)
                                    if action == "delete":
                                        book["asks"].pop(p, None)
                                    else:
                                        book["asks"][p] = float(qty)
                                change_ids[instrument] = data["change_id"]
                            else:
                                continue

                            if book["bids"] and book["asks"]:
                                yield OrderBookUpdate(
                                    exchange="deribit",
                                    market_type=self.market_type,
                                    symbol=instrument,
                                    bids=tuple(sorted(book["bids"].items(), reverse=True)[:depth]),
                                    asks=tuple(sorted(book["asks"].items())[:depth]),
                                    timestamp=float(data["timestamp"]),
                                )
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
                log.warning("deribit: WS dropped (%s) — reconnecting in 1s", exc)
                for s in symbols:
                    books[s] = {"bids": {}, "asks": {}}
                    change_ids[s] = None
                await asyncio.sleep(1)
