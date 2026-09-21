from __future__ import annotations

from core.models.options.black76 import OptionType
from paper.option_quoting import generate_option_quote


def test_bid_below_ask():
    q = generate_option_quote(81_000.0, 1 / 365, 0.5, 81_000.0, OptionType.CALL)
    assert q.bid_price < q.ask_price


def test_prices_are_coin_denominated_not_usd():
    """A BTC option worth a few hundred USD should be a small fraction of 1 BTC."""
    q = generate_option_quote(81_000.0, 1 / 365, 0.5, 81_000.0, OptionType.CALL)
    assert 0.0 < q.bid_price < 1.0
    assert 0.0 < q.ask_price < 1.0


def test_expired_option_skips_both_sides():
    q = generate_option_quote(81_000.0, 0.0, 0.5, 81_000.0, OptionType.CALL)
    assert q.skip_bid and q.skip_ask
    assert q.bid_size == 0.0 and q.ask_size == 0.0


def test_zero_underlying_price_skips_both_sides():
    q = generate_option_quote(0.0, 1 / 365, 0.5, 81_000.0, OptionType.CALL)
    assert q.skip_bid and q.skip_ask


def test_wider_half_spread_widens_the_quote():
    tight = generate_option_quote(81_000.0, 1 / 365, 0.5, 81_000.0, OptionType.CALL, half_spread_vol=0.02)
    wide = generate_option_quote(81_000.0, 1 / 365, 0.5, 81_000.0, OptionType.CALL, half_spread_vol=0.10)
    assert (wide.ask_price - wide.bid_price) > (tight.ask_price - tight.bid_price)


def test_higher_realized_vol_raises_both_prices():
    low = generate_option_quote(81_000.0, 1 / 365, 0.3, 81_000.0, OptionType.CALL)
    high = generate_option_quote(81_000.0, 1 / 365, 0.9, 81_000.0, OptionType.CALL)
    assert high.bid_price > low.bid_price
    assert high.ask_price > low.ask_price


def test_put_and_call_price_differently_away_from_the_money():
    call = generate_option_quote(81_000.0, 1 / 365, 0.5, 85_000.0, OptionType.CALL)
    put = generate_option_quote(81_000.0, 1 / 365, 0.5, 85_000.0, OptionType.PUT)
    assert call.bid_price != put.bid_price


def test_pin_risk_shrinks_size_near_expiry_at_the_strike():
    normal = generate_option_quote(81_000.0, 1 / 365, 0.5, 81_000.0, OptionType.CALL)
    pinned = generate_option_quote(81_000.0, 1e-7, 0.5, 81_000.0, OptionType.CALL)
    assert pinned.bid_size < normal.bid_size
    assert any("pin risk" in b for b in pinned.breaches)


def test_pin_risk_does_not_shrink_size_far_from_expiry():
    q = generate_option_quote(81_000.0, 30 / 365, 0.5, 81_000.0, OptionType.CALL)
    assert q.bid_size == 0.1
    assert q.breaches == ()
