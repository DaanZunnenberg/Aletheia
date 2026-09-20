from __future__ import annotations

from core.strategies.market_maker import QuoteDecision
from data.orderbook import OrderBookUpdate
from paper.fill_simulator import check_fill


def _book(best_bid: float, best_ask: float) -> OrderBookUpdate:
    return OrderBookUpdate(
        exchange="deribit", market_type="perpetual", symbol="BTC-PERPETUAL",
        bids=((best_bid, 1.0),), asks=((best_ask, 1.0),), timestamp=0.0,
    )


def _quote(bid_price=100.0, ask_price=102.0, bid_size=0.1, ask_size=0.1, skip_bid=False, skip_ask=False) -> QuoteDecision:
    return QuoteDecision(
        bid_price=bid_price, ask_price=ask_price, bid_size=bid_size, ask_size=ask_size,
        skip_bid=skip_bid, skip_ask=skip_ask, breaches=(),
    )


def test_no_fill_when_market_has_not_crossed():
    quote = _quote()
    fills = check_fill(quote, _book(best_bid=100.5, best_ask=101.5))
    assert fills == []


def test_bid_fills_when_market_ask_drops_to_or_below_our_bid():
    quote = _quote(bid_price=100.0)
    fills = check_fill(quote, _book(best_bid=99.0, best_ask=100.0))
    assert len(fills) == 1
    assert fills[0].side == "bid"
    assert fills[0].price == 100.0
    assert fills[0].size == 0.1


def test_ask_fills_when_market_bid_rises_to_or_above_our_ask():
    quote = _quote(ask_price=102.0)
    fills = check_fill(quote, _book(best_bid=102.0, best_ask=103.0))
    assert len(fills) == 1
    assert fills[0].side == "ask"
    assert fills[0].price == 102.0


def test_both_sides_can_fill_in_a_wide_market_move():
    quote = _quote(bid_price=100.0, ask_price=102.0)
    fills = check_fill(quote, _book(best_bid=103.0, best_ask=99.0))
    sides = {f.side for f in fills}
    assert sides == {"bid", "ask"}


def test_skipped_bid_never_fills_even_if_crossed():
    quote = _quote(bid_price=100.0, skip_bid=True)
    fills = check_fill(quote, _book(best_bid=99.0, best_ask=99.5))
    assert all(f.side != "bid" for f in fills)


def test_skipped_ask_never_fills_even_if_crossed():
    quote = _quote(ask_price=102.0, skip_ask=True)
    fills = check_fill(quote, _book(best_bid=103.0, best_ask=104.0))
    assert all(f.side != "ask" for f in fills)


def test_zero_size_side_never_fills():
    quote = _quote(bid_price=100.0, bid_size=0.0)
    fills = check_fill(quote, _book(best_bid=99.0, best_ask=99.5))
    assert fills == []
