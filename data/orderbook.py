from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

MarketType = Literal["perpetual", "spot"]


@dataclass(frozen=True)
class OrderBookUpdate:
    """
    Exchange-agnostic L2 order-book snapshot. Every connector under
    exchanges/ (Deribit, Binance, ...) normalises its wire format into this
    before it ever reaches the stream manager or a consumer -- nothing
    downstream of this type should need to know which exchange or market
    type produced it.

    exchange     : 'deribit' | 'binance' | ...
    market_type  : 'perpetual' | 'spot' -- the hedging-instrument distinction
                   that matters for this project (see core/MODEL.md); options
                   are out of scope for this data layer.
    symbol       : the exchange-native instrument/symbol name (e.g.
                   'BTC-PERPETUAL' on Deribit, 'BTCUSDT' on Binance) --
                   deliberately not normalised across exchanges, since the
                   whole point of streaming the same coin from two venues is
                   to compare them, not to pretend they're one instrument.
    bids/asks    : ((price, size), ...), bids descending, asks ascending.
    timestamp    : unix ms, exchange-reported where available.
    """
    exchange: str
    market_type: MarketType
    symbol: str
    bids: tuple[tuple[float, float], ...]
    asks: tuple[tuple[float, float], ...]
    timestamp: float

    @property
    def best_bid(self) -> float:
        return self.bids[0][0] if self.bids else float("nan")

    @property
    def best_ask(self) -> float:
        return self.asks[0][0] if self.asks else float("nan")

    @property
    def mid_price(self) -> float:
        return 0.5 * (self.best_bid + self.best_ask)

    @property
    def key(self) -> tuple[str, str, str]:
        """(exchange, market_type, symbol) -- the natural stream identity."""
        return (self.exchange, self.market_type, self.symbol)
