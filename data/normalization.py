from __future__ import annotations

import time

from deribit.types import Instrument, Ticker
from core.market_state import FutureQuote, MarketState, OptionQuote


def ticker_to_option_quote(ticker: Ticker, instrument: Instrument) -> OptionQuote:
    return OptionQuote(
        instrument_name=ticker["instrument_name"],
        expiry_ts=instrument["expiration_timestamp"],
        strike=instrument["strike"],
        option_type=instrument["option_type"],
        mark_price=ticker["mark_price"],
        mark_iv=(ticker["mark_iv"] or 0.0) / 100.0,   # Deribit sends %; store as fraction
        bid_price=ticker["best_bid_price"],
        ask_price=ticker["best_ask_price"],
        bid_iv=(ticker["bid_iv"] / 100.0) if ticker["bid_iv"] is not None else None,
        ask_iv=(ticker["ask_iv"] / 100.0) if ticker["ask_iv"] is not None else None,
        delta=ticker["delta"],
        gamma=ticker["gamma"],
        vega=ticker["vega"],
        theta=ticker["theta"],
        open_interest=ticker["open_interest"],
    )


def ticker_to_future_quote(ticker: Ticker, instrument: Instrument) -> FutureQuote:
    return FutureQuote(
        instrument_name=ticker["instrument_name"],
        expiry_ts=instrument["expiration_timestamp"],
        mark_price=ticker["mark_price"],
        index_price=ticker["index_price"],
        open_interest=ticker["open_interest"],
        current_funding=ticker["current_funding"],
        funding_8h=ticker["funding_8h"],
    )


def build_market_state(
    currency: str,
    spot_price: float,
    option_quotes: list[OptionQuote],
    future_quotes: list[FutureQuote],
    dvol: float | None = None,
    timestamp: float | None = None,
) -> MarketState:
    return MarketState(
        currency=currency,
        spot_price=spot_price,
        dvol=dvol,
        option_chain=option_quotes,
        futures_curve=future_quotes,
        timestamp=timestamp if timestamp is not None else time.time() * 1000,
    )
