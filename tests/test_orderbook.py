from __future__ import annotations

import math

from data.orderbook import OrderBookUpdate


def _update(bids=((100.0, 1.0), (99.0, 2.0)), asks=((101.0, 1.0), (102.0, 2.0))) -> OrderBookUpdate:
    return OrderBookUpdate(
        exchange="deribit", market_type="perpetual", symbol="BTC-PERPETUAL",
        bids=bids, asks=asks, timestamp=1_700_000_000_000.0,
    )


def test_best_bid_and_ask_are_the_top_of_book():
    u = _update()
    assert u.best_bid == 100.0
    assert u.best_ask == 101.0


def test_mid_price_averages_best_bid_and_ask():
    u = _update()
    assert u.mid_price == 100.5


def test_key_identifies_the_stream():
    u = _update()
    assert u.key == ("deribit", "perpetual", "BTC-PERPETUAL")


def test_empty_book_sides_yield_nan_not_a_crash():
    u = _update(bids=(), asks=())
    assert math.isnan(u.best_bid)
    assert math.isnan(u.best_ask)
    assert math.isnan(u.mid_price)


def test_microprice_equals_mid_when_sizes_are_symmetric():
    u = _update(bids=((100.0, 5.0),), asks=((101.0, 5.0),))
    assert u.microprice == u.mid_price


def test_microprice_leans_toward_the_thinner_side():
    """More size resting on the bid -> microprice pulled toward the ask
    (the bid side is less likely to be the one consumed next)."""
    u = _update(bids=((100.0, 9.0),), asks=((101.0, 1.0),))
    assert u.microprice > u.mid_price


def test_microprice_leans_toward_the_thinner_ask_side_symmetric_case():
    u = _update(bids=((100.0, 1.0),), asks=((101.0, 9.0),))
    assert u.microprice < u.mid_price


def test_microprice_falls_back_to_mid_on_empty_book():
    u = _update(bids=(), asks=())
    assert math.isnan(u.microprice)


def test_microprice_falls_back_to_mid_on_zero_total_size():
    u = _update(bids=((100.0, 0.0),), asks=((101.0, 0.0),))
    assert u.microprice == u.mid_price


def test_is_frozen():
    u = _update()
    try:
        u.symbol = "ETH-PERPETUAL"  # type: ignore[misc]
        assert False, "OrderBookUpdate should be immutable"
    except AttributeError:
        pass
