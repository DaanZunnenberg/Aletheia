from __future__ import annotations

import numpy as np
import pytest

from paper.execution_latency import LatencyModel, is_quote_live, taker_slippage_price


def test_sampled_latency_is_never_below_the_base():
    model = LatencyModel(base_ms=50.0, jitter_ms=30.0)
    rng = np.random.default_rng(0)
    for _ in range(100):
        assert model.sample_latency_ms(rng) >= 50.0


def test_quote_live_at_is_after_decision_time():
    model = LatencyModel(base_ms=50.0, jitter_ms=10.0)
    rng = np.random.default_rng(1)
    live_at = model.quote_live_at(decision_timestamp_ms=1000.0, rng=rng)
    assert live_at > 1000.0


def test_is_quote_live_false_before_the_latency_elapses():
    assert not is_quote_live(quote_live_at_ms=1100.0, now_ms=1050.0)


def test_is_quote_live_true_once_the_latency_elapses():
    assert is_quote_live(quote_live_at_ms=1100.0, now_ms=1100.0)
    assert is_quote_live(quote_live_at_ms=1100.0, now_ms=1200.0)


def test_taker_buy_slippage_costs_more_than_mid():
    price = taker_slippage_price(mid_price=100.0, side="buy", size=1.0, depth_estimate=10.0)
    assert price > 100.0


def test_taker_sell_slippage_receives_less_than_mid():
    price = taker_slippage_price(mid_price=100.0, side="sell", size=1.0, depth_estimate=10.0)
    assert price < 100.0


def test_larger_size_relative_to_depth_costs_more():
    small = taker_slippage_price(mid_price=100.0, side="buy", size=1.0, depth_estimate=10.0)
    large = taker_slippage_price(mid_price=100.0, side="buy", size=8.0, depth_estimate=10.0)
    assert (large - 100.0) > (small - 100.0)


def test_zero_depth_estimate_does_not_crash():
    price = taker_slippage_price(mid_price=100.0, side="buy", size=1.0, depth_estimate=0.0)
    assert price > 100.0  # falls back to maximal-impact assumption, not a ZeroDivisionError


def test_invalid_side_raises():
    with pytest.raises(ValueError):
        taker_slippage_price(mid_price=100.0, side="hold", size=1.0, depth_estimate=10.0)
