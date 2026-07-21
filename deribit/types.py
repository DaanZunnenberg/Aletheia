from __future__ import annotations

from typing import TypedDict


class OrderBookSnapshot(TypedDict):
    instrument_name: str
    bids: list[tuple[float, float]]  # (price, qty), descending by price
    asks: list[tuple[float, float]]  # (price, qty), ascending by price
    timestamp: float                  # unix ms


class Trade(TypedDict):
    instrument_name: str
    price: float
    amount: float
    direction: str       # 'buy' | 'sell'
    timestamp: float     # unix ms
    trade_id: str
    index_price: float


class Ticker(TypedDict):
    """Unified ticker for futures. Perpetual-only fields are None for dated futures."""
    instrument_name: str
    timestamp: float
    mark_price: float
    index_price: float
    best_bid_price: float
    best_ask_price: float
    best_bid_amount: float
    best_ask_amount: float
    last_price: float | None
    open_interest: float
    current_funding: float | None
    funding_8h: float | None


class IndexPrice(TypedDict):
    index_name: str   # e.g. 'btc_usd', 'eth_usd'
    price: float
    timestamp: float  # unix ms


class FundingRate(TypedDict):
    """Perpetual funding data from the perpetual.{instrument}.{interval} channel."""
    instrument_name: str
    timestamp: float
    current_funding: float  # current 8h period rate (fraction, not %)
    funding_8h: float       # estimated next 8h rate
    interest_rate: float    # annualised interest rate component


class Instrument(TypedDict):
    instrument_name: str
    kind: str               # 'future' | 'spot'
    currency: str
    base_currency: str
    quote_currency: str
    expiration_timestamp: int   # unix ms; 0 for perpetuals
    tick_size: float
    min_trade_amount: float
    contract_size: float
    taker_commission: float
    maker_commission: float
    is_active: bool
