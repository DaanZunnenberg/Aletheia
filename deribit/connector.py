from __future__ import annotations

import asyncio
from typing import AsyncIterator, Any  # Any kept for _sub_stream return type

import aiohttp
import orjson

from .types import (
    FundingRate, IndexPrice, OptionMarkPrice, OrderBookSnapshot,
    Ticker, Trade, VolatilityIndex,
)
from utils.logger import get_logger

log = get_logger(__name__)

_WS_LIVE = "wss://www.deribit.com/ws/api/v2"
_WS_TEST = "wss://test.deribit.com/ws/api/v2"

_HB_REPLY = orjson.dumps(
    {"jsonrpc": "2.0", "method": "public/test", "params": {}, "id": 0}
).decode()


async def _sub_stream(
    session: aiohttp.ClientSession,
    url: str,
    channels: list[str],
) -> AsyncIterator[tuple[str, Any]]:
    """
    Connect, subscribe to channels, yield (channel, data) pairs.
    Handles Deribit application-level heartbeats and auto-reconnects on drop.
    The caller is responsible for creating and closing the ClientSession.
    """
    sub = orjson.dumps({
        "jsonrpc": "2.0", "method": "public/subscribe",
        "params": {"channels": channels}, "id": 1,
    }).decode()

    while True:
        try:
            async with session.ws_connect(url, heartbeat=30) as ws:
                await ws.send_str(sub)
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = orjson.loads(msg.data)
                        if data.get("method") == "heartbeat":
                            if data.get("params", {}).get("type") == "test_request":
                                await ws.send_str(_HB_REPLY)
                            continue
                        if data.get("method") == "subscription":
                            yield data["params"]["channel"], data["params"]["data"]
                    elif msg.type in (
                        aiohttp.WSMsgType.CLOSE,
                        aiohttp.WSMsgType.ERROR,
                        aiohttp.WSMsgType.CLOSED,
                    ):
                        exc = ws.exception()
                        log.warning("WS closed (%s) — reconnecting in 1 s", exc or msg.type)
                        break
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
            log.warning("WS dropped (%s) — reconnecting in 1 s", exc)
            await asyncio.sleep(1)


class DeribitConnector:
    """
    WebSocket connector for all public Deribit data streams.

    Each watch_* method is an independent async generator backed by a dedicated
    aiohttp ClientSession. Run multiple streams concurrently with asyncio.gather().

    Supported streams
    -----------------
    watch_order_book       — L2 book with incremental updates (futures & options)
    watch_trades           — public trade tape
    watch_ticker           — full ticker incl. greeks and IV for options
    watch_index            — spot index price (btc_usd, eth_usd, …)
    watch_volatility_index — DVOL index (btc_dvol, eth_dvol)
    watch_mark_prices      — mark prices + IV for ALL options on an index at once
    watch_funding          — perpetual funding rate
    """

    def __init__(self, api_key: str = "", api_secret: str = "", testnet: bool = False) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._url = _WS_TEST if testnet else _WS_LIVE

    # ------------------------------------------------------------------
    # Order book — stateful (snapshot + incremental deltas)
    # ------------------------------------------------------------------

    async def watch_order_book(
        self, instrument: str, depth: int = 20
    ) -> AsyncIterator[OrderBookSnapshot]:
        async with aiohttp.ClientSession() as session:
            while True:
                async for snap in self._book_stream(session, instrument, depth):
                    yield snap

    async def _book_stream(
        self,
        session: aiohttp.ClientSession,
        instrument: str,
        depth: int,
    ) -> AsyncIterator[OrderBookSnapshot]:
        # Full raw book channel — Deribit sends [action, price, qty] entries.
        # Depth-filtered channels (e.g. book.X.none.5.100ms) silently return [].
        channel = f"book.{instrument}.100ms"

        bids: dict[float, float] = {}
        asks: dict[float, float] = {}
        last_change_id: int | None = None

        sub = orjson.dumps({
            "jsonrpc": "2.0", "method": "public/subscribe",
            "params": {"channels": [channel]}, "id": 1,
        }).decode()

        try:
            async with session.ws_connect(self._url, heartbeat=30) as ws:
                await ws.send_str(sub)
                async for msg in ws:
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        if msg.type in (
                            aiohttp.WSMsgType.CLOSE,
                            aiohttp.WSMsgType.ERROR,
                            aiohttp.WSMsgType.CLOSED,
                        ):
                            log.warning("book WS closed (%s) — reconnecting in 1 s", ws.exception())
                            break
                        continue

                    envelope = orjson.loads(msg.data)

                    if envelope.get("method") == "heartbeat":
                        if envelope.get("params", {}).get("type") == "test_request":
                            await ws.send_str(_HB_REPLY)
                        continue

                    if envelope.get("method") != "subscription":
                        continue

                    data = envelope["params"]["data"]

                    if "type" not in data:
                        log.debug("book: ignoring message without 'type': %s", data)
                        continue

                    if data["type"] == "snapshot":
                        # Snapshot entries: [action, price, qty]; action is always "new".
                        bids = {float(p): float(q) for _, p, q in data["bids"]}
                        asks = {float(p): float(q) for _, p, q in data["asks"]}
                        last_change_id = data["change_id"]

                    elif data["type"] == "change":
                        if last_change_id is None or data["prev_change_id"] != last_change_id:
                            bids.clear()
                            asks.clear()
                            last_change_id = None
                            continue

                        for action, price, qty in data["bids"]:
                            p = float(price)
                            if action == "delete":
                                bids.pop(p, None)
                            else:
                                bids[p] = float(qty)

                        for action, price, qty in data["asks"]:
                            p = float(price)
                            if action == "delete":
                                asks.pop(p, None)
                            else:
                                asks[p] = float(qty)

                        last_change_id = data["change_id"]
                    else:
                        continue

                    if bids and asks:
                        yield OrderBookSnapshot(
                            instrument_name=instrument,
                            bids=sorted(bids.items(), reverse=True)[:depth],
                            asks=sorted(asks.items())[:depth],
                            timestamp=float(data["timestamp"]),
                        )

        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
            log.warning("book stream dropped (%s) — reconnecting in 1 s", exc)
            await asyncio.sleep(1)

    # ------------------------------------------------------------------
    # Trades
    # ------------------------------------------------------------------

    async def watch_trades(self, instrument: str) -> AsyncIterator[Trade]:
        channel = f"trades.{instrument}.100ms"
        async with aiohttp.ClientSession() as session:
            async for _, data in _sub_stream(session, self._url, [channel]):
                for t in data:
                    yield Trade(
                        instrument_name=instrument,
                        price=float(t["price"]),
                        amount=float(t["amount"]),
                        direction=t["direction"],
                        timestamp=float(t["timestamp"]),
                        trade_id=t["trade_id"],
                        iv=float(t["iv"]) if t.get("iv") is not None else None,
                        index_price=float(t.get("index_price") or 0.0),
                    )

    # ------------------------------------------------------------------
    # Ticker (futures + options; options include greeks and IV)
    # ------------------------------------------------------------------

    async def watch_ticker(self, instrument: str) -> AsyncIterator[Ticker]:
        channel = f"ticker.{instrument}.100ms"
        async with aiohttp.ClientSession() as session:
            async for _, t in _sub_stream(session, self._url, [channel]):
                yield Ticker(
                    instrument_name=instrument,
                    timestamp=float(t["timestamp"]),
                    mark_price=float(t["mark_price"]),
                    index_price=float(t["index_price"]),
                    best_bid_price=float(t.get("best_bid_price") or 0.0),
                    best_ask_price=float(t.get("best_ask_price") or 0.0),
                    best_bid_amount=float(t.get("best_bid_amount") or 0.0),
                    best_ask_amount=float(t.get("best_ask_amount") or 0.0),
                    last_price=float(t["last_price"]) if t.get("last_price") is not None else None,
                    open_interest=float(t.get("open_interest") or 0.0),
                    mark_iv=float(t["mark_iv"]) if t.get("mark_iv") is not None else None,
                    bid_iv=float(t["bid_iv"]) if t.get("bid_iv") is not None else None,
                    ask_iv=float(t["ask_iv"]) if t.get("ask_iv") is not None else None,
                    delta=float(t["delta"]) if t.get("delta") is not None else None,
                    gamma=float(t["gamma"]) if t.get("gamma") is not None else None,
                    vega=float(t["vega"]) if t.get("vega") is not None else None,
                    theta=float(t["theta"]) if t.get("theta") is not None else None,
                    rho=float(t["rho"]) if t.get("rho") is not None else None,
                    underlying_index=t.get("underlying_index"),
                    underlying_price=float(t["underlying_price"]) if t.get("underlying_price") is not None else None,
                    current_funding=float(t["current_funding"]) if t.get("current_funding") is not None else None,
                    funding_8h=float(t["funding_8h"]) if t.get("funding_8h") is not None else None,
                )

    # ------------------------------------------------------------------
    # Index price  (e.g. index_name='btc_usd', 'eth_usd', 'sol_usd')
    # ------------------------------------------------------------------

    async def watch_index(self, index_name: str) -> AsyncIterator[IndexPrice]:
        channel = f"deribit_price_index.{index_name}"
        async with aiohttp.ClientSession() as session:
            async for _, data in _sub_stream(session, self._url, [channel]):
                yield IndexPrice(
                    index_name=data["index_name"],
                    price=float(data["price"]),
                    timestamp=float(data["timestamp"]),
                )

    # ------------------------------------------------------------------
    # Deribit Volatility Index — DVOL  (e.g. 'btc_dvol', 'eth_dvol')
    # ------------------------------------------------------------------

    async def watch_volatility_index(self, index_name: str) -> AsyncIterator[VolatilityIndex]:
        # Deribit uses the price index name as the channel param (btc_usd, eth_usd),
        # not a dedicated dvol name (btc_dvol does not work).
        channel = f"deribit_volatility_index.{index_name}"
        async with aiohttp.ClientSession() as session:
            async for _, data in _sub_stream(session, self._url, [channel]):
                yield VolatilityIndex(
                    index_name=data["index_name"],
                    timestamp=float(data["timestamp"]),
                    volatility=float(data["volatility"]),
                )

    # ------------------------------------------------------------------
    # All-options mark prices  (e.g. index_name='btc_usd', 'eth_usd')
    # ------------------------------------------------------------------

    async def watch_mark_prices(self, index_name: str) -> AsyncIterator[list[OptionMarkPrice]]:
        # markprice.options is a differential channel: each message contains only
        # the options whose mark price changed since the last message, not the full
        # chain. Merge into a cache so every yield returns the complete option set.
        channel = f"markprice.options.{index_name}"
        cache: dict[str, OptionMarkPrice] = {}
        async with aiohttp.ClientSession() as session:
            async for _, data in _sub_stream(session, self._url, [channel]):
                for entry in data:
                    cache[entry["instrument_name"]] = OptionMarkPrice(
                        instrument_name=entry["instrument_name"],
                        mark_price=float(entry["mark_price"]),
                        mark_iv=float(entry["iv"]),
                    )
                yield list(cache.values())

    # ------------------------------------------------------------------
    # Perpetual funding rate
    # ------------------------------------------------------------------

    async def watch_funding(self, instrument: str) -> AsyncIterator[FundingRate]:
        channel = f"perpetual.{instrument}.100ms"
        async with aiohttp.ClientSession() as session:
            async for _, data in _sub_stream(session, self._url, [channel]):
                yield FundingRate(
                    instrument_name=instrument,
                    timestamp=float(data["timestamp"]),
                    current_funding=float(data.get("current_funding") or 0.0),
                    funding_8h=float(data.get("funding_8h") or 0.0),
                    interest_rate=float(data.get("interest_rate") or 0.0),
                )
