"""
Record real L2 order books + real trades to disk, for later replay through
core/backtest/l2_replay.py.

Deribit (and every venue here) has no free historical L2 endpoint -- only a
trade tape (see research/data/fetch_historical_day.py's docstring). The only
way to get genuine order-book depth for backtesting is to record the live
stream going forward, the same stream examples/paper_trading_bot.py already
consumes. This script does exactly that and nothing else: no quoting, no
positions, no P&L -- pure recording, so it can run unattended for as long as
you want a dataset for.

Run: python examples/record_live_streams.py [seconds]
Defaults to running for 3600 seconds (Ctrl-C also works).
Writes: runtime/recordings/<UTC timestamp>.jsonl
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from data.recorder import StreamRecorder
from exchanges.binance_connector import BinanceOrderBookConnector
from exchanges.deribit_connector import DeribitOrderBookConnector
from exchanges.deribit_trades import DeribitTradeStreamConnector
from exchanges.stream_manager import MultiExchangeStreamManager, StreamSpec
from utils.logger import get_logger

log = get_logger(__name__)

_DERIBIT_PERPS = ["BTC-PERPETUAL", "ETH-PERPETUAL"]
_BINANCE_SYMBOLS = ["BTCUSDT", "ETHUSDT"]


async def main(run_seconds: float) -> None:
    out_dir = _REPO_ROOT / "runtime" / "recordings"
    out_path = out_dir / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S}.jsonl"
    log.info("recording to %s", out_path)
    recorder = StreamRecorder(out_path)

    manager = MultiExchangeStreamManager(
        [
            StreamSpec(DeribitOrderBookConnector(), _DERIBIT_PERPS),
            StreamSpec(BinanceOrderBookConnector("spot"), _BINANCE_SYMBOLS),
            StreamSpec(BinanceOrderBookConnector("perpetual"), _BINANCE_SYMBOLS),
        ]
    )
    trade_connector = DeribitTradeStreamConnector()

    n_book, n_trade = 0, 0

    async def consume_books() -> None:
        nonlocal n_book
        async for update in manager.stream():
            recorder.record_book_update(update)
            n_book += 1

    async def consume_trades() -> None:
        nonlocal n_trade
        async for trade in trade_connector.stream_trades(_DERIBIT_PERPS):
            recorder.record_trade(trade)
            n_trade += 1

    tasks = [asyncio.create_task(consume_books()), asyncio.create_task(consume_trades())]
    try:
        await asyncio.sleep(run_seconds)
    finally:
        for t in tasks:
            t.cancel()
        await manager.stop()
        for t in tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass
        recorder.close()

    log.info("done -- %d book updates, %d trades recorded to %s", n_book, n_trade, out_path)


if __name__ == "__main__":
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 3600.0
    asyncio.run(main(seconds))
