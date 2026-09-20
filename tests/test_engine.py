from __future__ import annotations

import numpy as np

from core.models.options.black76 import OptionType
from data.orderbook import OrderBookUpdate
from paper.engine import PaperTradingEngine, QuotedOption, QuotedPerp

_PERP_KEY = ("deribit", "perpetual", "BTC-PERPETUAL")
_OPTION_KEY = ("deribit", "option", "BTC-21SEP26-81000-C")
_REF_KEY = ("binance", "spot", "BTCUSDT")


def _perp_update(mid: float, t: float, spread: float = 2.0) -> OrderBookUpdate:
    return OrderBookUpdate(
        exchange="deribit", market_type="perpetual", symbol="BTC-PERPETUAL",
        bids=((mid - spread / 2, 5.0),), asks=((mid + spread / 2, 5.0),), timestamp=t * 1000.0,
    )


def _option_update(bid: float, ask: float, t: float) -> OrderBookUpdate:
    return OrderBookUpdate(
        exchange="deribit", market_type="option", symbol="BTC-21SEP26-81000-C",
        bids=((bid, 5.0),), asks=((ask, 5.0),), timestamp=t * 1000.0,
    )


def _ref_update(mid: float, t: float) -> OrderBookUpdate:
    return OrderBookUpdate(
        exchange="binance", market_type="spot", symbol="BTCUSDT",
        bids=((mid - 0.5, 5.0),), asks=((mid + 0.5, 5.0),), timestamp=t * 1000.0,
    )


def _new_engine() -> PaperTradingEngine:
    return PaperTradingEngine(
        quoted_perps=[QuotedPerp(key=_PERP_KEY, underlying_ccy="BTC")],
        quoted_options=[
            QuotedOption(
                key=_OPTION_KEY, underlying_ccy="BTC", underlying_key=_PERP_KEY,
                strike=81_000.0, option_type=OptionType.CALL, expiration_timestamp_ms=1e15,  # far future
            )
        ],
        reference_keys=[_REF_KEY],
    )


def test_no_quote_before_volatility_warmup():
    engine = _new_engine()
    engine.on_book_update(_perp_update(81_000.0, t=0.0))
    assert _PERP_KEY not in engine.resting_quotes


def test_perp_quote_appears_after_warmup():
    engine = _new_engine()
    rng = np.random.default_rng(0)
    mid = 81_000.0
    for i in range(30):
        mid += rng.normal(0, 1.0)
        engine.on_book_update(_perp_update(mid, t=float(i)))
    assert _PERP_KEY in engine.resting_quotes
    quote = engine.resting_quotes[_PERP_KEY]
    assert quote.bid_price < quote.ask_price


def test_reference_stream_is_never_quoted():
    engine = _new_engine()
    for i in range(30):
        engine.on_book_update(_ref_update(81_000.0 + i, t=float(i)))
    assert _REF_KEY not in engine.resting_quotes


def test_perp_fill_updates_position():
    engine = _new_engine()
    rng = np.random.default_rng(1)
    mid = 81_000.0
    for i in range(30):
        mid += rng.normal(0, 0.5)
        engine.on_book_update(_perp_update(mid, t=float(i)))

    quote = engine.resting_quotes[_PERP_KEY]
    # force a crossing update: market ask drops to/below our bid
    engine.on_book_update(OrderBookUpdate(
        exchange="deribit", market_type="perpetual", symbol="BTC-PERPETUAL",
        bids=((quote.bid_price - 5.0, 5.0),), asks=((quote.bid_price - 1.0, 5.0),), timestamp=31_000.0,
    ))
    assert engine.position_book.position_for("deribit:perpetual:BTC-PERPETUAL").quantity > 0.0
    assert engine.n_fills >= 1


def test_option_quote_requires_underlying_and_volatility():
    engine = _new_engine()
    # option book arrives before any perp (underlying) data -- must not crash, must not quote yet
    engine.on_book_update(_option_update(0.01, 0.011, t=0.0))
    assert _OPTION_KEY not in engine.resting_quotes


def test_option_quote_appears_once_underlying_and_vol_are_available():
    engine = _new_engine()
    rng = np.random.default_rng(2)
    mid = 81_000.0
    for i in range(30):
        mid += rng.normal(0, 1.0)
        engine.on_book_update(_perp_update(mid, t=float(i)))

    engine.on_book_update(_option_update(0.01, 0.011, t=31.0))
    assert _OPTION_KEY in engine.resting_quotes
    quote = engine.resting_quotes[_OPTION_KEY]
    assert quote.bid_price < quote.ask_price
    assert quote.bid_price < 1.0  # coin-denominated, not USD


def test_snapshot_reflects_all_seen_instruments():
    engine = _new_engine()
    engine.on_book_update(_perp_update(81_000.0, t=0.0))
    engine.on_book_update(_ref_update(81_000.0, t=0.0))
    symbols = {row.instrument for row in engine.snapshot()}
    assert symbols == {"BTC-PERPETUAL", "BTCUSDT"}


def test_snapshot_marks_reference_rows_correctly():
    engine = _new_engine()
    engine.on_book_update(_ref_update(81_000.0, t=0.0))
    row = engine.snapshot()[0]
    assert row.kind == "reference-spot"
    assert row.our_bid is None and row.our_ask is None


def test_spot_and_perp_sharing_a_symbol_get_separate_positions():
    """Regression: Binance spot and perpetual both use the literal symbol
    'BTCUSDT' -- positions must be keyed by (exchange, market_type, symbol),
    not bare symbol, or one would silently absorb the other's fills."""
    from paper.fill_simulator import PaperFill

    engine = _new_engine()
    engine.position_book.apply_fill("binance:spot:BTCUSDT", 0.0, PaperFill(side="bid", price=81_000.0, size=1.0))
    engine.position_book.apply_fill("binance:perpetual:BTCUSDT", 0.0, PaperFill(side="ask", price=81_000.0, size=2.0))

    assert engine.position_book.position_for("binance:spot:BTCUSDT").quantity == 1.0
    assert engine.position_book.position_for("binance:perpetual:BTCUSDT").quantity == -2.0
