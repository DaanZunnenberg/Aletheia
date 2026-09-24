"""
Live L2 recorder using ccxt.pro instead of the hand-rolled exchanges/
connectors (see ccxt_stream/connector.py's docstring for why -- exchange-
agnostic by construction, one class covers every venue).

Records 25-level depth for Binance USDT-M perpetuals AND spot (BTC, ETH --
spot is the second reference/hedge leg per CLAUDE.md's strategy context,
not previously streamed here) plus a cross-section of Deribit calls
(n_strikes nearest spot) at the nearest-to-1-day-to-expiry expiry per coin.

Binance discontinued its options market in 2024 -- ccxt confirms zero
option markets currently listed there (verified live, not from memory) so
"Binance options" is not a real data source; Deribit (already this
project's actual options venue per CLAUDE.md) is substituted instead, at
whatever depth the exchange actually rests (thin option books often have
fewer than 25 real levels; this records what's really there, not a padded
25).

Multiple strikes (not one) are streamed per coin because
core.models.options.surface_quoting.fit_smile() needs a cross-section to
fit an SVI smile -- a single strike's book (the original convention here)
can only ever support flat-vol quoting.

Runs *indefinitely* in rotating sessions rather than one long-lived
connection: each session runs for session_seconds, writes to its own file,
then the whole thing restarts -- which (a) re-selects the option universe,
since 1DTE options expire daily and a stale symbol would silently stop
producing data with no error, (b) bounds each file's size, and (c) gives a
natural recovery point if a session dies from something the individual
connectors' own internal retry (ccxt_stream/connector.py,
ccxt_stream/trades.py both retry forever on transient WS errors already)
doesn't catch -- an uncaught exception in one session just ends that
session; the outer loop logs it and starts the next one rather than taking
the whole recorder down. Run this under nohup/caffeinate (see module-level
run instructions below) for real overnight/multi-day unattended capture.

Output is the exact same data.recorder.StreamRecorder JSONL schema
examples/record_live_streams.py writes, so core/backtest/l2_replay.py
replays a ccxt_stream recording with zero changes.

Run: python ccxt_stream/record.py [session_seconds] [n_strikes]
Defaults: session_seconds=3600 (rotate hourly), n_strikes=5.
Ctrl-C stops after the current session finishes flushing.
Writes: runtime/ccxt_recordings/<UTC timestamp>.jsonl (one per session)

For unattended overnight/multi-day capture on macOS (prevents App Nap /
sleep from stalling the WS connections):
    caffeinate -i nohup python ccxt_stream/record.py > runtime/ccxt_recordings/recorder.log 2>&1 &
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
from ccxt_stream.select_option import select_strikes_near_expiry
from ccxt_stream.trades import CCXTTradeStreamConnector
from data.recorder import StreamRecorder
from utils.logger import get_logger

log = get_logger(__name__)

_BINANCE_PERP_SYMBOLS = ["BTC/USDT:USDT", "ETH/USDT:USDT"]
_BINANCE_SPOT_SYMBOLS = ["BTC/USDT", "ETH/USDT"]
_DEPTH = 25
_RECONNECT_BACKOFF_SECONDS = 10.0


def _select_deribit_option_symbols(n_strikes: int) -> list[str]:
    """REST (not ccxt.pro) is enough here -- run once per session, not streamed."""
    ex = ccxt.deribit()
    symbols: list[str] = []
    for currency in ("BTC", "ETH"):
        spot = ex.fetch_ticker(f"{currency}/USD:{currency}")["last"]
        chosen = select_strikes_near_expiry(ex, currency, spot, n_strikes=n_strikes)
        log.info(
            "selected %d %s strikes near %.1fh to expiry: %s",
            len(chosen), currency, chosen[0].hours_to_expiry, [o.symbol for o in chosen],
        )
        symbols.extend(o.symbol for o in chosen)
    return symbols


async def _run_session(session_seconds: float, n_strikes: int) -> None:
    option_symbols = _select_deribit_option_symbols(n_strikes)

    out_dir = _REPO_ROOT / "runtime" / "ccxt_recordings"
    out_path = out_dir / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S}.jsonl"
    log.info("recording session to %s (%.0fs)", out_path, session_seconds)
    recorder = StreamRecorder(out_path)

    binance_perp_books = CCXTOrderBookConnector("binanceusdm", "perpetual", depth=_DEPTH)
    binance_spot_books = CCXTOrderBookConnector("binance", "spot", depth=_DEPTH)
    deribit_option_books = CCXTOrderBookConnector("deribit", "option", depth=_DEPTH)
    binance_perp_trades = CCXTTradeStreamConnector("binanceusdm")
    binance_spot_trades = CCXTTradeStreamConnector("binance")
    deribit_trades = CCXTTradeStreamConnector("deribit")

    connectors = [
        binance_perp_books, binance_spot_books, deribit_option_books,
        binance_perp_trades, binance_spot_trades, deribit_trades,
    ]

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
        asyncio.create_task(consume_books(binance_perp_books, _BINANCE_PERP_SYMBOLS)),
        asyncio.create_task(consume_books(binance_spot_books, _BINANCE_SPOT_SYMBOLS)),
        asyncio.create_task(consume_books(deribit_option_books, option_symbols)),
        asyncio.create_task(consume_trades(binance_perp_trades, _BINANCE_PERP_SYMBOLS)),
        asyncio.create_task(consume_trades(binance_spot_trades, _BINANCE_SPOT_SYMBOLS)),
        asyncio.create_task(consume_trades(deribit_trades, option_symbols)),
    ]
    try:
        await asyncio.sleep(session_seconds)
    finally:
        for t in tasks:
            t.cancel()
        for t in tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass
        for c in connectors:
            await c.close()
        recorder.close()

    log.info("session done -- %d book updates, %d trades recorded to %s", n_book, n_trade, out_path)


async def main(session_seconds: float, n_strikes: int) -> None:
    while True:
        try:
            await _run_session(session_seconds, n_strikes)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("recording session crashed -- restarting in %.0fs", _RECONNECT_BACKOFF_SECONDS)
            await asyncio.sleep(_RECONNECT_BACKOFF_SECONDS)


if __name__ == "__main__":
    session_seconds_arg = float(sys.argv[1]) if len(sys.argv) > 1 else 3600.0
    n_strikes_arg = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    try:
        asyncio.run(main(session_seconds_arg, n_strikes_arg))
    except KeyboardInterrupt:
        log.info("stopped by user")
