from __future__ import annotations

import asyncio
from typing import AsyncIterator, Literal

import aiohttp
import orjson

from data.orderbook import OrderBookUpdate
from utils.logger import get_logger

log = get_logger(__name__)

_SPOT_BASE = "wss://stream.binance.com:9443/stream"
_FUTURES_BASE = "wss://fstream.binance.com/stream"
_VALID_LEVELS = (5, 10, 20)


class BinanceOrderBookConnector:
    """
    Multi-symbol L2 order-book streaming over a single WebSocket connection,
    via Binance's combined-stream endpoint (N symbols -> one connection).

    Uses the partial book depth stream (<symbol>@depth<levels>@100ms), which
    pushes a ready top-N snapshot every update -- not the diff-depth stream,
    which would require seeding from a REST snapshot and maintaining local
    book state the way the Deribit connector does. This is a deliberate
    initial-version simplification: partial depth is exact for the top N
    levels it reports (Binance computes it server-side), it's just capped at
    N in {5, 10, 20}. Move to the diff-depth stream if the model ever needs
    book state beyond 20 levels or update-by-update granularity.

    market_type: 'spot' or 'perpetual' (Binance USDT-margined futures).
    Construct one connector per market_type -- spot and perp are genuinely
    different venues with different WS hosts, not a parameter of one feed.
    """

    def __init__(self, market_type: Literal["spot", "perpetual"]) -> None:
        if market_type not in ("spot", "perpetual"):
            raise ValueError(f"market_type must be 'spot' or 'perpetual', got {market_type!r}")
        self.market_type = market_type
        self._base = _SPOT_BASE if market_type == "spot" else _FUTURES_BASE

    async def stream_order_books(self, symbols: list[str], depth: int = 20) -> AsyncIterator[OrderBookUpdate]:
        levels = depth if depth in _VALID_LEVELS else min(_VALID_LEVELS, key=lambda l: abs(l - depth))
        if levels != depth:
            log.warning("binance: depth=%d not in %s, using %d", depth, _VALID_LEVELS, levels)

        streams = "/".join(f"{s.lower()}@depth{levels}@100ms" for s in symbols)
        url = f"{self._base}?streams={streams}"

        while True:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(url, heartbeat=30) as ws:
                        log.info("binance(%s): subscribed to %d depth streams", self.market_type, len(symbols))
                        async for msg in ws:
                            if msg.type != aiohttp.WSMsgType.TEXT:
                                if msg.type in (
                                    aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED,
                                ):
                                    log.warning("binance(%s): WS closed (%s) — reconnecting in 1s", self.market_type, ws.exception())
                                    break
                                continue

                            envelope = orjson.loads(msg.data)
                            stream_name = envelope.get("stream", "")
                            data = envelope.get("data")
                            if not stream_name or data is None:
                                continue

                            symbol = stream_name.split("@")[0].upper()
                            # Spot's partial-depth payload uses full key names (bids/asks);
                            # futures uses the diff-stream's short keys (b/a) even for the
                            # "partial" depth stream -- but per Binance's own docs, b/a there
                            # are still the complete top-N snapshot each update, not a delta.
                            raw_bids = data.get("bids", data.get("b"))
                            raw_asks = data.get("asks", data.get("a"))
                            yield OrderBookUpdate(
                                exchange="binance",
                                market_type=self.market_type,
                                symbol=symbol,
                                bids=tuple((float(p), float(q)) for p, q in raw_bids),
                                asks=tuple((float(p), float(q)) for p, q in raw_asks),
                                timestamp=float(data.get("E", 0.0)),
                            )
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
                log.warning("binance(%s): WS dropped (%s) — reconnecting in 1s", self.market_type, exc)
                await asyncio.sleep(1)
