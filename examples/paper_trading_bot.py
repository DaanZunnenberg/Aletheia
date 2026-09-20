"""
Live paper trading bot: streams real L2 order books (Deribit perpetuals and
options, Binance spot and perpetual) and quotes against them in real time --
perps via the existing Avellaneda-Stoikov engine, a nearest-expiry ATM-ish
option per coin via Black-76 off realized vol (paper/option_quoting.py).
Binance spot/perp are reference-only (cross-venue display, future hedge
legs) -- not quoted.

Fills are simulated by crossing (paper/fill_simulator.py) against the live
book -- **no real orders are ever sent anywhere.** Positions, fills, and
unrealized P&L are tracked per instrument (paper/position_book.py) and
rendered to a refreshing terminal dashboard.

Run: python examples/paper_trading_bot.py [seconds]
Defaults to running for 120 seconds (Ctrl-C also works).
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.models.options.black76 import OptionType
from deribit.rest import DeribitREST
from exchanges.binance_connector import BinanceOrderBookConnector
from exchanges.deribit_connector import DeribitOrderBookConnector
from exchanges.stream_manager import MultiExchangeStreamManager, StreamSpec
from paper.dashboard import render_dashboard
from paper.engine import PaperTradingEngine, QuotedOption, QuotedPerp
from paper.instruments import find_near_the_money_option
from utils.logger import get_logger

log = get_logger(__name__)

_DASHBOARD_REFRESH_SECONDS = 1.0

_DERIBIT_PERP = {"BTC": "BTC-PERPETUAL", "ETH": "ETH-PERPETUAL"}
_BINANCE_SYMBOL = {"BTC": "BTCUSDT", "ETH": "ETHUSDT"}
_APPROX_SPOT = {"BTC": 80_000.0, "ETH": 3_000.0}  # only used to pick a near-the-money strike at startup


async def _discover_options() -> list[QuotedOption]:
    client = DeribitREST()
    quoted_options = []
    try:
        for currency in ("BTC", "ETH"):
            opt = await find_near_the_money_option(client, currency, _APPROX_SPOT[currency], "call")
            log.info("selected option for %s: %s (strike=%.0f)", currency, opt.instrument_name, opt.strike)
            quoted_options.append(
                QuotedOption(
                    key=("deribit", "option", opt.instrument_name),
                    underlying_ccy=currency,
                    underlying_key=("deribit", "perpetual", _DERIBIT_PERP[currency]),
                    strike=opt.strike,
                    option_type=OptionType.CALL,
                    expiration_timestamp_ms=opt.expiration_timestamp_ms,
                )
            )
    finally:
        await client.close()
    return quoted_options


async def main(run_seconds: float) -> None:
    quoted_options = await _discover_options()
    option_symbols_by_currency = {
        opt.underlying_ccy: opt.key[2] for opt in quoted_options
    }

    quoted_perps = [QuotedPerp(key=("deribit", "perpetual", name), underlying_ccy=ccy) for ccy, name in _DERIBIT_PERP.items()]
    reference_keys = [
        ("binance", "spot", sym) for sym in _BINANCE_SYMBOL.values()
    ] + [
        ("binance", "perpetual", sym) for sym in _BINANCE_SYMBOL.values()
    ]

    engine = PaperTradingEngine(quoted_perps=quoted_perps, quoted_options=quoted_options, reference_keys=reference_keys)

    manager = MultiExchangeStreamManager(
        [
            StreamSpec(DeribitOrderBookConnector(), list(_DERIBIT_PERP.values())),
            StreamSpec(DeribitOrderBookConnector(market_type="option"), list(option_symbols_by_currency.values()), depth=5),
            StreamSpec(BinanceOrderBookConnector("spot"), list(_BINANCE_SYMBOL.values())),
            StreamSpec(BinanceOrderBookConnector("perpetual"), list(_BINANCE_SYMBOL.values())),
        ]
    )

    async def consume() -> None:
        async for update in manager.stream():
            engine.on_book_update(update)

    async def render_loop() -> None:
        while True:
            await asyncio.sleep(_DASHBOARD_REFRESH_SECONDS)
            elapsed = time.time() - engine.start_time
            print(render_dashboard(engine.snapshot(), elapsed, engine.n_fills))

    consume_task = asyncio.create_task(consume())
    render_task = asyncio.create_task(render_loop())
    try:
        await asyncio.sleep(run_seconds)
    finally:
        consume_task.cancel()
        render_task.cancel()
        await manager.stop()
        for t in (consume_task, render_task):
            try:
                await t
            except asyncio.CancelledError:
                pass

    print(render_dashboard(engine.snapshot(), time.time() - engine.start_time, engine.n_fills))
    log.info("done — %d total fills", engine.n_fills)


if __name__ == "__main__":
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 120.0
    asyncio.run(main(seconds))
