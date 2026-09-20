from __future__ import annotations

from paper.bar_builder import LiveBarAggregator


def test_ticks_within_the_same_bar_update_its_close():
    agg = LiveBarAggregator(bar_seconds=1.0)
    agg.update(0.1, 100.0)
    agg.update(0.5, 101.0)
    agg.update(0.9, 102.0)
    assert agg.closed_series() == [102.0]


def test_a_new_bar_closes_the_previous_one():
    agg = LiveBarAggregator(bar_seconds=1.0)
    agg.update(0.1, 100.0)
    agg.update(1.1, 101.0)
    assert agg.closed_series(include_current=False) == [100.0]
    assert agg.closed_series() == [100.0, 101.0]


def test_empty_bars_are_forward_filled():
    agg = LiveBarAggregator(bar_seconds=1.0)
    agg.update(0.1, 100.0)
    agg.update(3.5, 105.0)
    # bars [0-1)=100, [1-2)=100 (ffill), [2-3)=100 (ffill), [3-4)=105 (current)
    assert agg.closed_series() == [100.0, 100.0, 100.0, 105.0]


def test_bar_boundaries_use_floor_division_not_rounding():
    agg = LiveBarAggregator(bar_seconds=1.0)
    agg.update(0.999, 100.0)
    agg.update(1.001, 101.0)
    assert agg.closed_series(include_current=False) == [100.0]


def test_sub_second_bar_width_works():
    agg = LiveBarAggregator(bar_seconds=0.1)
    agg.update(0.02, 100.0)
    agg.update(0.15, 101.0)
    agg.update(0.31, 102.0)
    assert agg.closed_series() == [100.0, 101.0, 101.0, 102.0]


def test_no_ticks_yet_returns_empty_series():
    agg = LiveBarAggregator(bar_seconds=1.0)
    assert agg.closed_series() == []
