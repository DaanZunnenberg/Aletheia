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
    iv: float | None     # implied vol at trade price; options only
    index_price: float


class Ticker(TypedDict):
    """
    Unified ticker for futures and options.
    Options-only fields (mark_iv, bid_iv, ask_iv, greeks, underlying_*) are None for futures.
    Perpetual-only fields (current_funding, funding_8h) are None for dated futures and options.
    """
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
    # Options-only
    mark_iv: float | None
    bid_iv: float | None
    ask_iv: float | None
    delta: float | None
    gamma: float | None
    vega: float | None
    theta: float | None
    rho: float | None
    underlying_index: str | None
    underlying_price: float | None
    # Perpetual-only
    current_funding: float | None
    funding_8h: float | None


class IndexPrice(TypedDict):
    index_name: str   # e.g. 'btc_usd', 'eth_usd'
    price: float
    timestamp: float  # unix ms


class VolatilityIndex(TypedDict):
    """Deribit Volatility Index (DVOL) — 30-day forward-looking IV derived from option prices."""
    index_name: str   # e.g. 'btc_dvol', 'eth_dvol'
    timestamp: float
    volatility: float  # current DVOL value (annualised %)
    open: float
    high: float
    low: float
    close: float


class OptionMarkPrice(TypedDict):
    """Single option mark price entry from the markprice.options.{index} channel."""
    instrument_name: str
    mark_price: float
    mark_iv: float    # 'iv' in the raw Deribit payload


class FundingRate(TypedDict):
    """Perpetual funding data from the perpetual.{instrument}.{interval} channel."""
    instrument_name: str
    timestamp: float
    current_funding: float  # current 8h period rate (fraction, not %)
    funding_8h: float       # estimated next 8h rate
    interest_rate: float    # annualised interest rate component


class Instrument(TypedDict):
    instrument_name: str
    kind: str               # 'future' | 'option' | 'spot'
    currency: str
    base_currency: str
    quote_currency: str
    expiration_timestamp: int   # unix ms; 0 for perpetuals
    strike: float               # options only; 0.0 otherwise
    option_type: str            # 'call' | 'put' | ''
    tick_size: float
    min_trade_amount: float
    contract_size: float
    taker_commission: float
    maker_commission: float
    is_active: bool
