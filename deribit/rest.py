from __future__ import annotations

from typing import Any

import aiohttp
import orjson

from .types import (
    IndexPrice, Instrument, OrderBookSnapshot, Ticker, Trade,
)
from utils.logger import get_logger

log = get_logger(__name__)

_BASE = "https://www.deribit.com/api/v2"
_TEST_BASE = "https://test.deribit.com/api/v2"


class DeribitREST:
    """
    Async REST client for Deribit.

    Covers instrument discovery, snapshots, and historical data — everything
    that either doesn't exist as a WS channel or is more efficient to poll once.

    Methods
    -------
    get_instruments       — list all active instruments for a currency + kind
    get_order_book        — single order book snapshot
    get_ticker            — single ticker (incl. greeks/IV for options)
    get_index_price       — current spot index price
    get_last_trades       — recent trades (up to 1000)
    """

    def __init__(self, api_key: str = "", api_secret: str = "", testnet: bool = False) -> None:
        self._base = _TEST_BASE if testnet else _BASE
        self._api_key = api_key
        self._api_secret = api_secret
        self._session: aiohttp.ClientSession | None = None

    async def _get(self, method: str, params: dict[str, Any] | None = None) -> Any:
        if self._session is None:
            self._session = aiohttp.ClientSession()
        url = f"{self._base}/{method}"
        async with self._session.get(url, params=params or {}) as resp:
            raw = await resp.read()
        data = orjson.loads(raw)
        if "error" in data:
            raise RuntimeError(
                f"Deribit {method} error {data['error']['code']}: {data['error']['message']}"
            )
        return data["result"]

    # ------------------------------------------------------------------
    # Instrument discovery
    # ------------------------------------------------------------------

    async def get_instruments(
        self,
        currency: str,
        kind: str,
        expired: bool = False,
    ) -> list[Instrument]:
        """
        List instruments.

        Parameters
        ----------
        currency : 'BTC' | 'ETH' | 'SOL' | 'USDC' | …
        kind     : 'future' | 'option' | 'spot' | 'future_combo' | 'option_combo'
        expired  : include expired instruments
        """
        raw = await self._get("public/get_instruments", {
            "currency": currency,
            "kind": kind,
            "expired": str(expired).lower(),
        })
        return [
            Instrument(
                instrument_name=r["instrument_name"],
                kind=r["kind"],
                currency=r["base_currency"],
                base_currency=r["base_currency"],
                quote_currency=r["quote_currency"],
                expiration_timestamp=r.get("expiration_timestamp", 0),
                tick_size=float(r["tick_size"]),
                min_trade_amount=float(r["min_trade_amount"]),
                contract_size=float(r["contract_size"]),
                taker_commission=float(r["taker_commission"]),
                maker_commission=float(r["maker_commission"]),
                is_active=r["is_active"],
            )
            for r in raw
        ]

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    async def get_order_book(self, instrument_name: str, depth: int = 20) -> OrderBookSnapshot:
        r = await self._get("public/get_order_book", {
            "instrument_name": instrument_name,
            "depth": depth,
        })
        return OrderBookSnapshot(
            instrument_name=instrument_name,
            bids=[(float(p), float(q)) for p, q in r["bids"]],
            asks=[(float(p), float(q)) for p, q in r["asks"]],
            timestamp=float(r["timestamp"]),
        )

    async def get_ticker(self, instrument_name: str) -> Ticker:
        t = await self._get("public/ticker", {"instrument_name": instrument_name})
        return Ticker(
            instrument_name=instrument_name,
            timestamp=float(t["timestamp"]),
            mark_price=float(t["mark_price"]),
            index_price=float(t["index_price"]),
            best_bid_price=float(t.get("best_bid_price") or 0.0),
            best_ask_price=float(t.get("best_ask_price") or 0.0),
            best_bid_amount=float(t.get("best_bid_amount") or 0.0),
            best_ask_amount=float(t.get("best_ask_amount") or 0.0),
            last_price=float(t["last_price"]) if t.get("last_price") is not None else None,
            open_interest=float(t.get("open_interest") or 0.0),
            current_funding=float(t["current_funding"]) if t.get("current_funding") is not None else None,
            funding_8h=float(t["funding_8h"]) if t.get("funding_8h") is not None else None,
        )

    async def get_index_price(self, index_name: str) -> IndexPrice:
        r = await self._get("public/get_index_price", {"index_name": index_name})
        return IndexPrice(
            index_name=index_name,
            price=float(r["index_price"]),
            timestamp=0.0,  # REST endpoint does not return a server timestamp
        )

    # ------------------------------------------------------------------
    # Trades
    # ------------------------------------------------------------------

    async def get_last_trades(
        self,
        instrument_name: str,
        count: int = 100,
        include_old: bool = True,
    ) -> list[Trade]:
        """Fetch up to `count` most recent public trades (max 1000)."""
        r = await self._get("public/get_last_trades_by_instrument", {
            "instrument_name": instrument_name,
            "count": min(count, 1000),
            "include_old": str(include_old).lower(),
        })
        return [
            Trade(
                instrument_name=instrument_name,
                price=float(t["price"]),
                amount=float(t["amount"]),
                direction=t["direction"],
                timestamp=float(t["timestamp"]),
                trade_id=t["trade_id"],
                index_price=float(t.get("index_price") or 0.0),
            )
            for t in r["trades"]
        ]

    # ------------------------------------------------------------------

    async def close(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None
