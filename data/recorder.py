from __future__ import annotations

from pathlib import Path
from typing import Any

import orjson

from data.orderbook import OrderBookUpdate
from deribit.types import Trade


class StreamRecorder:
    """
    Append-only JSONL writer for raw live market data -- every OrderBookUpdate
    and Trade exactly as received from exchanges/, before any strategy or
    fill logic touches it.

    Deribit has no free historical L2 endpoint (see
    research/data/fetch_historical_day.py), so real order-book depth for
    backtesting can only be accumulated going forward, by recording the same
    live stream examples/paper_trading_bot.py already consumes. This is that
    recorder: point it at the same MultiExchangeStreamManager + trade
    connector and it persists exactly what a live paper session would have
    seen, for later replay through core/backtest/l2_replay.py.

    One line per event: {"type": "book", "exchange":..., "market_type":...,
    "symbol":..., "bids": [[price, size], ...], "asks": [...], "timestamp":...}
    or {"type": "trade", ...Trade fields...}. Flushed on every write, same
    convention as paper/session_log.py -- a recorder that crashes mid-run
    should still leave a usable file up to the crash point.
    """

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(path, "ab")

    def record_book_update(self, update: OrderBookUpdate) -> None:
        self._write({
            "type": "book",
            "exchange": update.exchange, "market_type": update.market_type, "symbol": update.symbol,
            "bids": update.bids, "asks": update.asks, "timestamp": update.timestamp,
        })

    def record_trade(self, trade: Trade) -> None:
        payload: dict[str, Any] = {"type": "trade"}
        payload.update(trade)
        self._write(payload)

    def _write(self, payload: dict[str, Any]) -> None:
        self._file.write(orjson.dumps(payload))
        self._file.write(b"\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()
