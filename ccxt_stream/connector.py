from __future__ import annotations

import asyncio
from typing import AsyncIterator

import ccxt.pro as ccxtpro

from data.orderbook import MarketType, OrderBookUpdate
from utils.logger import get_logger

log = get_logger(__name__)


class CCXTOrderBookConnector:
    """
    L2 order-book connector backed by ccxt.pro instead of a hand-rolled
    per-exchange WS client (exchanges/deribit_connector.py,
    exchanges/binance_connector.py). ccxt.pro is exchange-agnostic by
    construction -- the same class streams Binance USDT-M futures or
    Deribit options just by passing a different ccxt exchange id -- so this
    single connector covers every venue ccxt.pro supports, at the cost of
    the venue-specific tuning the hand-rolled connectors have (e.g.
    Deribit's own change_id gap detection).

    Implements exchanges.base.OrderBookConnector's stream_order_books()
    protocol, so it's a drop-in StreamSpec.connector for
    exchanges.stream_manager.MultiExchangeStreamManager exactly like the
    existing connectors -- ccxt is an alternative source of the same
    data.orderbook.OrderBookUpdate type, not a parallel system.

    depth: requested book depth. Binance's REST/WS depth snapshots only
    accept specific limits (5/10/20/50/100/500/1000 for futures) -- ccxt
    handles that internally, but the *caller's* requested depth (e.g. 25)
    may not be one of those, so this connector requests the smallest valid
    ccxt depth >= the caller's request and truncates the result down to
    exactly `depth` levels, which is what every caller actually wants.
    """

    # Binance futures REST/WS depth snapshots only accept these limits (25
    # is *not* one of them, despite looking like a plausible round number --
    # confirmed live: Binance rejects it with "25 is not valid depth limit").
    _VALID_CCXT_DEPTHS = (5, 10, 20, 50, 100, 500, 1000)

    def __init__(self, exchange_id: str, market_type: MarketType, depth: int = 25) -> None:
        self.exchange_id = exchange_id
        self.market_type = market_type
        self.depth = depth
        self._request_depth = next((d for d in self._VALID_CCXT_DEPTHS if d >= depth), depth)
        self._exchange = getattr(ccxtpro, exchange_id)()

    async def close(self) -> None:
        await self._exchange.close()

    async def stream_order_books(self, symbols: list[str], depth: int | None = None) -> AsyncIterator[OrderBookUpdate]:
        """
        symbols are ccxt unified symbols (e.g. 'BTC/USDT:USDT' for Binance
        USDT-M perpetual, 'BTC/USD:BTC-260922-69000-C' for a Deribit
        option) -- not the exchange-native names deribit/exchanges/ use,
        since ccxt's whole point is normalising that away. One
        watch_order_book_for_symbols() call multiplexes every symbol over a
        single WS connection where the exchange supports it (Binance and
        Deribit both do), matching the "one WS connection per exchange"
        convention exchanges/ connectors already follow.
        """
        requested = depth or self.depth
        while True:
            try:
                ob = await self._exchange.watch_order_book_for_symbols(symbols, self._request_depth)
            except Exception:
                log.exception("ccxt_stream: %s watch_order_book_for_symbols failed, retrying in 2s", self.exchange_id)
                await asyncio.sleep(2.0)
                continue

            # Deribit's book levels carry a 3rd element (order count); take
            # only [price, size] -- data.orderbook.OrderBookUpdate's
            # exchange-agnostic contract is strictly (price, size) pairs.
            yield OrderBookUpdate(
                exchange=self.exchange_id,
                market_type=self.market_type,
                symbol=ob["symbol"],
                bids=tuple((level[0], level[1]) for level in ob["bids"][:requested]),
                asks=tuple((level[0], level[1]) for level in ob["asks"][:requested]),
                timestamp=float(ob["timestamp"]) if ob.get("timestamp") is not None else 0.0,
            )
