from __future__ import annotations

import numpy as np

from exchange.base import OrderBookSnapshot


class OrderBook:
    __slots__ = ("_symbol", "_bids", "_asks", "_timestamp")

    def __init__(self) -> None:
        self._symbol: str = ""
        self._bids: np.ndarray = np.empty((0, 2), dtype=float)
        self._asks: np.ndarray = np.empty((0, 2), dtype=float)
        self._timestamp: float = 0.0

    def update(self, snapshot: OrderBookSnapshot) -> None:
        self._symbol = snapshot["symbol"]
        self._bids = np.array(snapshot["bids"], dtype=float)
        self._asks = np.array(snapshot["asks"], dtype=float)
        self._timestamp = snapshot["timestamp"]

    @property
    def ready(self) -> bool:
        return self._bids.shape[0] > 0 and self._asks.shape[0] > 0

    @property
    def bids(self) -> np.ndarray:
        """All bid levels as (price, qty) array, descending by price."""
        return self._bids

    @property
    def asks(self) -> np.ndarray:
        """All ask levels as (price, qty) array, ascending by price."""
        return self._asks

    @property
    def best_bid(self) -> float:
        return float(self._bids[0, 0])

    @property
    def best_ask(self) -> float:
        return float(self._asks[0, 0])

    @property
    def spread(self) -> float:
        return self.best_ask - self.best_bid

    @property
    def mid(self) -> float:
        return (self.best_bid + self.best_ask) / 2.0

    @property
    def microprice(self) -> float:
        """Volume-weighted mid at the touch: shifts toward the side with less depth."""
        bid_qty = self._bids[0, 1]
        ask_qty = self._asks[0, 1]
        total = bid_qty + ask_qty
        if total == 0.0:
            return self.mid
        return (self.best_bid * ask_qty + self.best_ask * bid_qty) / total

    @property
    def imbalance(self) -> float:
        """Signed book imbalance over all levels: ∈ [-1, 1]. Positive = bid-heavy."""
        bid_qty = float(self._bids[:, 1].sum())
        ask_qty = float(self._asks[:, 1].sum())
        total = bid_qty + ask_qty
        if total == 0.0:
            return 0.0
        return (bid_qty - ask_qty) / total
