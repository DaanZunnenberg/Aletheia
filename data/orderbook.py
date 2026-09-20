from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

MarketType = Literal["perpetual", "spot", "option"]


@dataclass(frozen=True)
class OrderBookUpdate:
    """
    Exchange-agnostic L2 order-book snapshot. Every connector under
    exchanges/ (Deribit, Binance, ...) normalises its wire format into this
    before it ever reaches the stream manager or a consumer -- nothing
    downstream of this type should need to know which exchange or market
    type produced it.

    exchange     : 'deribit' | 'binance' | ...
    market_type  : 'perpetual' | 'spot' | 'option'.
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
    def microprice(self) -> float:
        """
        Size-weighted mid: leans toward the side with *less* resting size,
        since that side is statistically more likely to be consumed first
        and move next (Stoikov 2018, "The Micro-Price"). More robust than
        naive mid when the book is imbalanced -- naive mid is blind to
        depth entirely, so a book that's 10x deeper on the bid than the ask
        gets exactly the same "mid" as a perfectly symmetric one, despite
        being priced very differently by the market's own liquidity.
        """
        if not self.bids or not self.asks:
            return self.mid_price
        bid_size, ask_size = self.bids[0][1], self.asks[0][1]
        total = bid_size + ask_size
        if total <= 0.0:
            return self.mid_price
        return (self.best_bid * ask_size + self.best_ask * bid_size) / total

    @property
    def key(self) -> tuple[str, str, str]:
        """(exchange, market_type, symbol) -- the natural stream identity."""
        return (self.exchange, self.market_type, self.symbol)
