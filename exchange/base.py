from abc import ABC, abstractmethod
from typing import AsyncIterator, TypedDict


class OrderBookSnapshot(TypedDict):
    symbol: str
    bids: list[tuple[float, float]]  # (price, qty), descending by price
    asks: list[tuple[float, float]]  # (price, qty), ascending by price
    timestamp: float                  # unix ms


class Trade(TypedDict):
    symbol: str
    price: float
    qty: float
    side: str    # 'buy' | 'sell'
    timestamp: float


class BaseConnector(ABC):
    @abstractmethod
    def watch_order_book(self, symbol: str, depth: int) -> AsyncIterator[OrderBookSnapshot]: ...

    @abstractmethod
    def watch_trades(self, symbol: str) -> AsyncIterator[Trade]: ...

    @abstractmethod
    async def close(self) -> None: ...
