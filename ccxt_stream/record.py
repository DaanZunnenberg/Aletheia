"""
Live L2 recorder using ccxt.pro instead of the hand-rolled exchanges/
connectors (see ccxt_stream/connector.py's docstring for why -- exchange-
agnostic by construction, one class covers every venue).

Records 25-level depth for Binance USDT-M perpetuals (BTC, ETH) and the
nearest-to-1-day-to-expiry, nearest-the-money Deribit call option per coin.

Binance discontinued its options market in 2024 -- ccxt confirms zero
option markets currently listed there (verified live, not from memory) so
"Binance options" is not a real data source; Deribit (already this
project's actual options venue per CLAUDE.md) is substituted instead, at
whatever depth the exchange actually rests (thin option books often have
fewer than 25 real levels; this records what's really there, not a padded
25).

Output is the exact same data.recorder.StreamRecorder JSONL schema
examples/record_live_streams.py writes, so core/backtest/l2_replay.py
replays a ccxt_stream recording with zero changes.

Run: python ccxt_stream/record.py [seconds]
Defaults to running for 3600 seconds (Ctrl-C also works).
Writes: runtime/ccxt_recordings/<UTC timestamp>.jsonl
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import ccxt

from ccxt_stream.connector import CCXTOrderBookConnector
from ccxt_stream.select_option import select_near_1dte_option
from ccxt_stream.trades import CCXTTradeStreamConnector
from data.recorder import StreamRecorder
from utils.logger import get_logger

log = get_logger(__name__)

_BINANCE_PERP_SYMBOLS = ["BTC/USDT:USDT", "ETH/USDT:USDT"]
_DEPTH = 25


def _select_deribit_options() -> list[str]:
    """REST (not ccxt.pro) is enough here -- run once at startup, not streamed."""
    ex = ccxt.deribit()
    symbols = []
    for currency in ("BTC", "ETH"):
        spot = ex.fetch_ticker(f"{currency}/USD:{currency}")["last"]
        opt = select_near_1dte_option(ex, currency, spot)
        log.info("selected %s 1DTE option: %s (%.1fh to expiry)", currency, opt.symbol, opt.hours_to_expiry)
        symbols.append(opt.symbol)
    return symbols


async def main(run_seconds: float) -> None:
    option_symbols = _select_deribit_options()

    out_dir = _REPO_ROOT / "runtime" / "ccxt_recordings"
    out_path = out_dir / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S}.jsonl"
    log.info("recording to %s", out_path)
    recorder = StreamRecorder(out_path)

    binance_books = CCXTOrderBookConnector("binanceusdm", "perpetual", depth=_DEPTH)
    deribit_books = CCXTOrderBookConnector("deribit", "option", depth=_DEPTH)
    binance_trades = CCXTTradeStreamConnector("binanceusdm")
    deribit_trades = CCXTTradeStreamConnector("deribit")

    n_book, n_trade = 0, 0

    async def consume_books(connector: CCXTOrderBookConnector, symbols: list[str]) -> None:
        nonlocal n_book
        async for update in connector.stream_order_books(symbols):
            recorder.record_book_update(update)
            n_book += 1

    async def consume_trades(connector: CCXTTradeStreamConnector, symbols: list[str]) -> None:
        nonlocal n_trade
        async for trade in connector.stream_trades(symbols):
            recorder.record_trade(trade)
            n_trade += 1

    tasks = [
        asyncio.create_task(consume_books(binance_books, _BINANCE_PERP_SYMBOLS)),
        asyncio.create_task(consume_books(deribit_books, option_symbols)),
        asyncio.create_task(consume_trades(binance_trades, _BINANCE_PERP_SYMBOLS)),
        asyncio.create_task(consume_trades(deribit_trades, option_symbols)),
    ]
    try:
        await asyncio.sleep(run_seconds)
    finally:
        for t in tasks:
            t.cancel()
        for t in tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass
        await binance_books.close()
        await deribit_books.close()
        await binance_trades.close()
        await deribit_trades.close()
        recorder.close()

    log.info("done -- %d book updates, %d trades recorded to %s", n_book, n_trade, out_path)


if __name__ == "__main__":
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 3600.0
    asyncio.run(main(seconds))
