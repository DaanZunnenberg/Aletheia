from __future__ import annotations

import asyncio
from typing import AsyncIterator, Any

import orjson
import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from .types import (
    FundingRate, IndexPrice, OptionMarkPrice, OrderBookSnapshot,
    Ticker, Trade, VolatilityIndex,
)
from utils.logger import get_logger

log = get_logger(__name__)

_WS_LIVE = "wss://www.deribit.com/ws/api/v2"
_WS_TEST = "wss://test.deribit.com/ws/api/v2"

_VALID_DEPTHS = (1, 5, 10, 20)

_HB_REPLY = orjson.dumps({"jsonrpc": "2.0", "method": "public/test", "params": {}, "id": 0}).decode()


def _nearest_depth(n: int) -> int:
    for d in _VALID_DEPTHS:
        if d >= n:
            return d
    return 20


async def _sub_stream(url: str, channels: list[str]) -> AsyncIterator[tuple[str, Any]]:
    """
    Connect, subscribe to channels, yield (channel, data) pairs.
    Handles application-level heartbeats and auto-reconnects on drop.
    """
    sub = orjson.dumps({
        "jsonrpc": "2.0", "method": "public/subscribe",
        "params": {"channels": channels}, "id": 1,
    }).decode()
    while True:
        try:
            async with websockets.connect(url, ping_interval=None, open_timeout=20) as ws:
                await ws.send(sub)
                async for raw in ws:
                    msg = orjson.loads(raw)
                    if msg.get("method") == "heartbeat":
                        if msg["params"].get("type") == "test_request":
                            await ws.send(_HB_REPLY)
                        continue
                    if msg.get("method") == "subscription":
                        yield msg["params"]["channel"], msg["params"]["data"]
        except (WebSocketException, OSError, TimeoutError) as exc:
            log.warning("WS dropped (%s) — reconnecting in 1 s", exc)
            await asyncio.sleep(1)


class DeribitConnector:
    """
    WebSocket connector for all public Deribit data streams.

    Each watch_* method is an independent async generator that opens its own
    WS connection and reconnects automatically on drop. Run multiple streams
    concurrently with asyncio.gather().

    Supported streams
    -----------------
    watch_order_book   — L2 book with incremental updates (futures & options)
    watch_trades       — public trade tape
    watch_ticker       — full ticker incl. greeks and IV for options
    watch_index        — spot index price (btc_usd, eth_usd, …)
    watch_volatility_index — DVOL index (btc_dvol, eth_dvol)
    watch_mark_prices  — mark prices + IV for ALL options on an index at once
    watch_funding      — perpetual funding rate
    """

    def __init__(self, api_key: str = "", api_secret: str = "", testnet: bool = False) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._url = _WS_TEST if testnet else _WS_LIVE

    # ------------------------------------------------------------------
    # Order book — stateful (snapshot + incremental deltas)
    # ------------------------------------------------------------------

    async def watch_order_book(self, instrument: str, depth: int = 20) -> AsyncIterator[OrderBookSnapshot]:
        while True:
            async for snap in self._book_stream(instrument, depth):
                yield snap

    async def _book_stream(self, instrument: str, depth: int) -> AsyncIterator[OrderBookSnapshot]:
        slot = _nearest_depth(depth)
        channel = f"book.{instrument}.none.{slot}.100ms"

        bids: dict[float, float] = {}
        asks: dict[float, float] = {}
        last_change_id: int | None = None

        sub = orjson.dumps({
            "jsonrpc": "2.0", "method": "public/subscribe",
            "params": {"channels": [channel]}, "id": 1,
        }).decode()

        try:
            async with websockets.connect(self._url, ping_interval=None, open_timeout=20) as ws:
                await ws.send(sub)
                async for raw in ws:
                    msg = orjson.loads(raw)
                    if msg.get("method") == "heartbeat":
                        if msg["params"].get("type") == "test_request":
                            await ws.send(_HB_REPLY)
                        continue
                    if msg.get("method") != "subscription":
                        continue

                    data = msg["params"]["data"]

                    if data["type"] == "snapshot":
                        bids = {float(p): float(q) for p, q in data["bids"]}
                        asks = {float(p): float(q) for p, q in data["asks"]}
                        last_change_id = data["change_id"]

                    elif data["type"] == "change":
                        if last_change_id is None or data["prev_change_id"] != last_change_id:
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

                    if bids and asks:
                        yield OrderBookSnapshot(
                            instrument_name=instrument,
                            bids=sorted(bids.items(), reverse=True)[:depth],
                            asks=sorted(asks.items())[:depth],
                            timestamp=float(data["timestamp"]),
                        )
        except (WebSocketException, OSError, TimeoutError) as exc:
            log.warning("book stream dropped (%s) — reconnecting in 1 s", exc)
            await asyncio.sleep(1)

    # ------------------------------------------------------------------
    # Trades
    # ------------------------------------------------------------------

    async def watch_trades(self, instrument: str) -> AsyncIterator[Trade]:
        channel = f"trades.{instrument}.100ms"
        async for _, data in _sub_stream(self._url, [channel]):
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
        async for _, t in _sub_stream(self._url, [channel]):
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
        async for _, data in _sub_stream(self._url, [channel]):
            yield IndexPrice(
                index_name=data["index_name"],
                price=float(data["price"]),
                timestamp=float(data["timestamp"]),
            )

    # ------------------------------------------------------------------
    # Deribit Volatility Index — DVOL  (e.g. 'btc_dvol', 'eth_dvol')
    # ------------------------------------------------------------------

    async def watch_volatility_index(self, index_name: str) -> AsyncIterator[VolatilityIndex]:
        channel = f"deribit_volatility_index.{index_name}"
        async for _, data in _sub_stream(self._url, [channel]):
            yield VolatilityIndex(
                index_name=data["index_name"],
                timestamp=float(data["timestamp"]),
                volatility=float(data["volatility"]),
                open=float(data["open"]),
                high=float(data["high"]),
                low=float(data["low"]),
                close=float(data["close"]),
            )

    # ------------------------------------------------------------------
    # All-options mark prices  (e.g. index_name='btc_usd', 'eth_usd')
    # One update covers every listed option on that index simultaneously.
    # ------------------------------------------------------------------

    async def watch_mark_prices(self, index_name: str) -> AsyncIterator[list[OptionMarkPrice]]:
        channel = f"markprice.options.{index_name}"
        async for _, data in _sub_stream(self._url, [channel]):
            yield [
                OptionMarkPrice(
                    instrument_name=entry["instrument_name"],
                    mark_price=float(entry["mark_price"]),
                    mark_iv=float(entry["iv"]),
                )
                for entry in data
            ]

    # ------------------------------------------------------------------
    # Perpetual funding rate
    # ------------------------------------------------------------------

    async def watch_funding(self, instrument: str) -> AsyncIterator[FundingRate]:
        channel = f"perpetual.{instrument}.100ms"
        async for _, data in _sub_stream(self._url, [channel]):
            yield FundingRate(
                instrument_name=instrument,
                timestamp=float(data["timestamp"]),
                current_funding=float(data.get("current_funding") or 0.0),
                funding_8h=float(data.get("funding_8h") or 0.0),
                interest_rate=float(data.get("interest_rate") or 0.0),
            )
