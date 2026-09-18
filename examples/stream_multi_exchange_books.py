"""
Streams live L2 order books for BTC and ETH, on both Deribit (perpetual) and
Binance (perpetual + spot), concurrently, from a single process.

This is the deliverable for "stream multiple order books at once from
different coins, including spot/perp on two exchanges for hedging": six
concurrent book streams (2 coins x {deribit perp, binance perp, binance
spot}) merged into one feed via exchanges/stream_manager.py.

Run: python examples/stream_multi_exchange_books.py [seconds]
Defaults to running for 20 seconds then exiting (Ctrl-C also works).
"""
from __future__ import annotations

import asyncio
import sys
from collections import defaultdict
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from exchanges.binance_connector import BinanceOrderBookConnector
from exchanges.deribit_connector import DeribitOrderBookConnector
from exchanges.stream_manager import MultiExchangeStreamManager, StreamSpec
from utils.logger import get_logger

log = get_logger(__name__)


async def main(run_seconds: float) -> None:
    manager = MultiExchangeStreamManager(
        [
            StreamSpec(DeribitOrderBookConnector(), ["BTC-PERPETUAL", "ETH-PERPETUAL"]),
            StreamSpec(BinanceOrderBookConnector("perpetual"), ["BTCUSDT", "ETHUSDT"]),
            StreamSpec(BinanceOrderBookConnector("spot"), ["BTCUSDT", "ETHUSDT"]),
        ]
    )

    latest: dict[tuple[str, str, str], float] = {}
    n_updates = defaultdict(int)

    async def consume() -> None:
        async for update in manager.stream():
            latest[update.key] = update.mid_price
            n_updates[update.key] += 1

    task = asyncio.create_task(consume())
    try:
        await asyncio.sleep(run_seconds)
    finally:
        task.cancel()
        await manager.stop()

    log.info("streamed for %.0fs — final state:", run_seconds)
    for key in sorted(latest):
        exchange, market_type, symbol = key
        log.info(
            "  %-8s %-10s %-14s mid=%.2f  updates=%d",
            exchange, market_type, symbol, latest[key], n_updates[key],
        )


if __name__ == "__main__":
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 20.0
    asyncio.run(main(seconds))
