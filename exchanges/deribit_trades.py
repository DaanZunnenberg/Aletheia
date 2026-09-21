from __future__ import annotations

import asyncio
from typing import AsyncIterator

import aiohttp
import orjson

from deribit.types import Trade
from utils.logger import get_logger

log = get_logger(__name__)

_WS_LIVE = "wss://www.deribit.com/ws/api/v2"
_WS_TEST = "wss://test.deribit.com/ws/api/v2"

_HB_REPLY = orjson.dumps({"jsonrpc": "2.0", "method": "public/test", "params": {}, "id": 0}).decode()


class DeribitTradeStreamConnector:
    """
    Multi-instrument live trade stream over a single WebSocket connection
    (same public/subscribe multi-channel pattern as
    exchanges.deribit_connector.DeribitOrderBookConnector).

    Exists to replace crossing-based paper fills (a resting quote "fills"
    whenever the market's top-of-book merely touches it) with fills matched
    against real trade prints -- see paper/queue_tracker.py and the rewired
    paper/fill_simulator.py. Reuses deribit.types.Trade, the same type
    deribit/rest.py's historical trade fetch already produces, so live and
    historical trades are structurally identical.
    """

    def __init__(self, testnet: bool = False) -> None:
        self._url = _WS_TEST if testnet else _WS_LIVE

    async def stream_trades(self, symbols: list[str]) -> AsyncIterator[Trade]:
        channels = [f"trades.{s}.100ms" for s in symbols]
        sub = orjson.dumps(
            {"jsonrpc": "2.0", "method": "public/subscribe", "params": {"channels": channels}, "id": 1}
        ).decode()

        while True:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(self._url, heartbeat=30) as ws:
                        await ws.send_str(sub)
                        log.info("deribit: subscribed to %d trade channels", len(channels))
                        async for msg in ws:
                            if msg.type != aiohttp.WSMsgType.TEXT:
                                if msg.type in (
                                    aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED,
                                ):
                                    log.warning("deribit: trade WS closed (%s) — reconnecting in 1s", ws.exception())
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
                            instrument = channel.split(".")[1]
                            for t in envelope["params"]["data"]:
                                yield Trade(
                                    instrument_name=instrument,
                                    price=float(t["price"]),
                                    amount=float(t["amount"]),
                                    direction=t["direction"],
                                    timestamp=float(t["timestamp"]),
                                    trade_id=t["trade_id"],
                                    index_price=float(t.get("index_price") or 0.0),
                                    mark_price=float(t.get("mark_price") or 0.0),
                                )
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
                log.warning("deribit: trade WS dropped (%s) — reconnecting in 1s", exc)
                await asyncio.sleep(1)
