from __future__ import annotations

from paper.queue_tracker import QueueTracker, RestingOrder, process_trade_against_order


def _bid(price=100.0, size=0.1, remaining_ahead=0.0) -> RestingOrder:
    return RestingOrder(price=price, side="bid", size=size, remaining_ahead=remaining_ahead)


def _ask(price=101.0, size=0.1, remaining_ahead=0.0) -> RestingOrder:
    return RestingOrder(price=price, side="ask", size=size, remaining_ahead=remaining_ahead)


def test_trade_above_our_bid_does_not_affect_it():
    result = process_trade_against_order(_bid(price=100.0), trade_price=105.0, trade_amount=5.0)
    assert result.filled_size == 0.0


def test_trade_below_our_ask_does_not_affect_it():
    result = process_trade_against_order(_ask(price=101.0), trade_price=95.0, trade_amount=5.0)
    assert result.filled_size == 0.0


def test_trade_walking_through_our_bid_fills_us_fully():
    result = process_trade_against_order(_bid(price=100.0, size=0.2), trade_price=99.0, trade_amount=1.0)
    assert result.filled_size == 0.2
    assert result.fully_consumed


def test_trade_walking_through_our_ask_fills_us_fully():
    result = process_trade_against_order(_ask(price=101.0, size=0.2), trade_price=102.0, trade_amount=1.0)
    assert result.filled_size == 0.2
    assert result.fully_consumed


def test_trade_at_our_bid_price_consumes_the_queue_ahead_first():
    order = _bid(price=100.0, size=0.1, remaining_ahead=5.0)
    result = process_trade_against_order(order, trade_price=100.0, trade_amount=2.0)
    assert result.filled_size == 0.0  # not our turn yet
    assert result.remaining_ahead == 3.0
    assert not result.fully_consumed


def test_trade_at_our_price_exhausts_queue_and_fills_leftover():
    order = _bid(price=100.0, size=0.1, remaining_ahead=2.0)
    result = process_trade_against_order(order, trade_price=100.0, trade_amount=2.5)
    # 2.0 consumes the queue ahead, 0.5 left over -> fills our 0.1-size order
    assert result.filled_size == 0.1
    assert result.fully_consumed


def test_trade_at_our_price_once_already_at_front_fills_immediately():
    order = _bid(price=100.0, size=0.1, remaining_ahead=0.0)
    result = process_trade_against_order(order, trade_price=100.0, trade_amount=0.05)
    assert result.filled_size == 0.05  # capped by trade size, not our order size
    assert result.fully_consumed


def test_multiple_trades_progressively_drain_the_queue():
    order = _bid(price=100.0, size=0.1, remaining_ahead=3.0)
    r1 = process_trade_against_order(order, trade_price=100.0, trade_amount=1.0)
    assert r1.remaining_ahead == 2.0
    order2 = RestingOrder(price=100.0, side="bid", size=0.1, remaining_ahead=r1.remaining_ahead)
    r2 = process_trade_against_order(order2, trade_price=100.0, trade_amount=1.0)
    assert r2.remaining_ahead == 1.0
    order3 = RestingOrder(price=100.0, side="bid", size=0.1, remaining_ahead=r2.remaining_ahead)
    r3 = process_trade_against_order(order3, trade_price=100.0, trade_amount=1.5)
    assert r3.filled_size == 0.1  # 1.0 clears the remaining queue, 0.5 leftover fills us
    assert r3.fully_consumed


def test_queue_tracker_place_and_fill_via_walked_through_trade():
    tracker = QueueTracker()
    tracker.place_order("BTC-PERPETUAL", "bid", price=100.0, size=0.1, size_ahead=0.0)
    fills = tracker.on_trade("BTC-PERPETUAL", trade_price=99.0, trade_amount=1.0)
    assert fills == [("bid", 0, 0.1)]
    assert ("BTC-PERPETUAL", "bid", 0) not in tracker._orders  # cleared after fill


def test_queue_tracker_tracks_bid_and_ask_independently():
    tracker = QueueTracker()
    tracker.place_order("BTC-PERPETUAL", "bid", price=100.0, size=0.1, size_ahead=0.0)
    tracker.place_order("BTC-PERPETUAL", "ask", price=101.0, size=0.1, size_ahead=0.0)
    fills = tracker.on_trade("BTC-PERPETUAL", trade_price=99.0, trade_amount=1.0)
    assert fills == [("bid", 0, 0.1)]
    # ask should be untouched -- still present
    assert ("BTC-PERPETUAL", "ask", 0) in tracker._orders


def test_queue_tracker_ignores_trades_for_untracked_instruments():
    tracker = QueueTracker()
    fills = tracker.on_trade("ETH-PERPETUAL", trade_price=99.0, trade_amount=1.0)
    assert fills == []


def test_queue_tracker_requote_resets_queue_position():
    tracker = QueueTracker()
    tracker.place_order("BTC-PERPETUAL", "bid", price=100.0, size=0.1, size_ahead=5.0)
    tracker.on_trade("BTC-PERPETUAL", trade_price=100.0, trade_amount=2.0)
    # requote at a new price -- should discard the old partially-drained queue state
    tracker.place_order("BTC-PERPETUAL", "bid", price=99.5, size=0.1, size_ahead=10.0)
    order = tracker._orders[("BTC-PERPETUAL", "bid", 0)]
    assert order.price == 99.5
    assert order.remaining_ahead == 10.0


def test_queue_tracker_clear_order_removes_it():
    tracker = QueueTracker()
    tracker.place_order("BTC-PERPETUAL", "bid", price=100.0, size=0.1, size_ahead=0.0)
    tracker.clear_order("BTC-PERPETUAL", "bid")
    assert ("BTC-PERPETUAL", "bid", 0) not in tracker._orders


def test_queue_tracker_multi_level_places_and_tracks_independently():
    tracker = QueueTracker()
    tracker.place_order("BTC-PERPETUAL", "bid", price=100.0, size=0.1, size_ahead=0.0, level=0)
    tracker.place_order("BTC-PERPETUAL", "bid", price=99.5, size=0.06, size_ahead=0.0, level=1)
    tracker.place_order("BTC-PERPETUAL", "bid", price=99.0, size=0.036, size_ahead=0.0, level=2)
    assert len(tracker._orders) == 3


def test_queue_tracker_multi_level_trade_fills_only_the_crossed_level():
    tracker = QueueTracker()
    tracker.place_order("BTC-PERPETUAL", "bid", price=100.0, size=0.1, size_ahead=0.0, level=0)
    tracker.place_order("BTC-PERPETUAL", "bid", price=99.5, size=0.06, size_ahead=0.0, level=1)
    # trade at 99.7: walks through level 0 (100.0) but not level 1 (99.5)
    fills = tracker.on_trade("BTC-PERPETUAL", trade_price=99.7, trade_amount=1.0)
    assert fills == [("bid", 0, 0.1)]
    assert ("BTC-PERPETUAL", "bid", 1) in tracker._orders  # untouched


def test_queue_tracker_multi_level_deep_trade_fills_every_shallower_level():
    tracker = QueueTracker()
    tracker.place_order("BTC-PERPETUAL", "bid", price=100.0, size=0.1, size_ahead=0.0, level=0)
    tracker.place_order("BTC-PERPETUAL", "bid", price=99.5, size=0.06, size_ahead=0.0, level=1)
    tracker.place_order("BTC-PERPETUAL", "bid", price=99.0, size=0.036, size_ahead=0.0, level=2)
    # trade at 98.0 walks through all three levels
    fills = tracker.on_trade("BTC-PERPETUAL", trade_price=98.0, trade_amount=1.0)
    assert {(side, level) for side, level, _ in fills} == {("bid", 0), ("bid", 1), ("bid", 2)}


def test_queue_tracker_clear_side_removes_all_levels_for_that_side_only():
    tracker = QueueTracker()
    tracker.place_order("BTC-PERPETUAL", "bid", price=100.0, size=0.1, size_ahead=0.0, level=0)
    tracker.place_order("BTC-PERPETUAL", "bid", price=99.5, size=0.06, size_ahead=0.0, level=1)
    tracker.place_order("BTC-PERPETUAL", "ask", price=101.0, size=0.1, size_ahead=0.0, level=0)
    tracker.clear_side("BTC-PERPETUAL", "bid")
    assert ("BTC-PERPETUAL", "bid", 0) not in tracker._orders
    assert ("BTC-PERPETUAL", "bid", 1) not in tracker._orders
    assert ("BTC-PERPETUAL", "ask", 0) in tracker._orders
