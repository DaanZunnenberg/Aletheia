from __future__ import annotations

import pytest

from paper.fill_simulator import PaperFill
from paper.position_book import PositionBook


def test_bid_fill_increases_position():
    book = PositionBook()
    book.apply_fill("BTC-PERPETUAL", 0.0, PaperFill(side="bid", price=100.0, size=0.5))
    assert book.position_for("BTC-PERPETUAL").quantity == pytest.approx(0.5)


def test_ask_fill_decreases_position():
    book = PositionBook()
    book.apply_fill("BTC-PERPETUAL", 0.0, PaperFill(side="ask", price=100.0, size=0.5))
    assert book.position_for("BTC-PERPETUAL").quantity == pytest.approx(-0.5)


def test_round_trip_realizes_pnl():
    book = PositionBook()
    book.apply_fill("BTC-PERPETUAL", 0.0, PaperFill(side="bid", price=100.0, size=0.5))
    book.apply_fill("BTC-PERPETUAL", 1.0, PaperFill(side="ask", price=101.0, size=0.5))
    position = book.position_for("BTC-PERPETUAL")
    assert position.quantity == pytest.approx(0.0)
    assert position.realized_pnl_usd == pytest.approx(0.5)


def test_unrealized_pnl_reflects_mark_move():
    book = PositionBook()
    book.apply_fill("BTC-PERPETUAL", 0.0, PaperFill(side="bid", price=100.0, size=1.0))
    assert book.unrealized_pnl("BTC-PERPETUAL", mark_price=105.0) == pytest.approx(5.0)


def test_fill_log_records_every_fill():
    book = PositionBook()
    book.apply_fill("BTC-PERPETUAL", 10.0, PaperFill(side="bid", price=100.0, size=0.1))
    book.apply_fill("ETH-PERPETUAL", 11.0, PaperFill(side="ask", price=3000.0, size=0.2))
    assert len(book.fill_log) == 2
    assert book.fill_log[0][1] == "BTC-PERPETUAL"
    assert book.fill_log[1][1] == "ETH-PERPETUAL"


def test_instruments_are_tracked_independently():
    book = PositionBook()
    book.apply_fill("BTC-PERPETUAL", 0.0, PaperFill(side="bid", price=100.0, size=1.0))
    book.apply_fill("ETH-PERPETUAL", 0.0, PaperFill(side="ask", price=3000.0, size=2.0))
    assert book.position_for("BTC-PERPETUAL").quantity == pytest.approx(1.0)
    assert book.position_for("ETH-PERPETUAL").quantity == pytest.approx(-2.0)


def test_total_net_pnl_sums_across_instruments():
    book = PositionBook()
    book.apply_fill("BTC-PERPETUAL", 0.0, PaperFill(side="bid", price=100.0, size=1.0))
    book.apply_fill("ETH-PERPETUAL", 0.0, PaperFill(side="bid", price=3000.0, size=1.0))
    total = book.total_net_pnl({"BTC-PERPETUAL": 110.0, "ETH-PERPETUAL": 2990.0})
    assert total == pytest.approx(10.0 - 10.0)


def test_querying_an_unseen_instrument_returns_a_flat_position():
    book = PositionBook()
    assert book.position_for("SOL-PERPETUAL").quantity == 0.0
