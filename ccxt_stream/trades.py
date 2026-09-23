from __future__ import annotations

import asyncio
from typing import AsyncIterator, TypedDict

import ccxt.pro as ccxtpro

from utils.logger import get_logger

log = get_logger(__name__)


class CCXTTrade(TypedDict):
    """
    Same field names as deribit.types.Trade (instrument_name/price/amount/
    direction/timestamp/trade_id/index_price/mark_price) so a recording made
    by this connector is byte-compatible with core.backtest.l2_replay's
    loader without any format-specific branching there. index_price/
    mark_price aren't part of ccxt's unified trade structure for every
    market, so they're None here rather than a real Deribit-only reference
    price -- callers relying on them (see core.backtest.historical's
    mark_price-as-mid convention) should prefer a recording made by
    data/recorder.py against the real Deribit trade stream instead.
    """
    instrument_name: str
    price: float
    amount: float
    direction: str
    timestamp: float
    trade_id: str | None
    index_price: float | None
    mark_price: float | None


class CCXTTradeStreamConnector:
    """ccxt.pro analogue of exchanges/deribit_trades.py's DeribitTradeStreamConnector, generalised to any ccxt.pro-supported venue."""

    def __init__(self, exchange_id: str) -> None:
        self.exchange_id = exchange_id
        self._exchange = getattr(ccxtpro, exchange_id)()

    async def close(self) -> None:
        await self._exchange.close()

    async def stream_trades(self, symbols: list[str]) -> AsyncIterator[CCXTTrade]:
        while True:
            try:
                trades = await self._exchange.watch_trades_for_symbols(symbols)
            except Exception:
                log.exception("ccxt_stream: %s watch_trades_for_symbols failed, retrying in 2s", self.exchange_id)
                await asyncio.sleep(2.0)
                continue

            for trade in trades:
                yield CCXTTrade(
                    instrument_name=trade["symbol"],
                    price=float(trade["price"]),
                    amount=float(trade["amount"]),
                    direction=trade["side"] or "buy",
                    timestamp=float(trade["timestamp"]) if trade.get("timestamp") is not None else 0.0,
                    trade_id=trade.get("id"),
                    index_price=None,
                    mark_price=None,
                )
