"""
Live paper trading bot: streams real L2 order books AND real trades (Deribit
perpetuals and options, Binance spot and perpetual reference-only) and
quotes against them in real time.

Perps: Avellaneda-Stoikov (core/), with a soft delta-hedge inventory
override from the option book's aggregated Black-76 Greeks
(core/models/greeks_aggregator.py, paper/hedger.py). Options: Black-76 off
realized vol (paper/option_quoting.py), size scaled down near expiry+strike
(pin risk, core/risk/pin_risk.py). A hard delta-band breach fires an
immediate (paper) taker hedge against the Deribit perp itself
(paper/hedger.py, paper/execution_latency.py for slippage).

Fills are matched against the real trade tape via a FIFO-queue-position
approximation (paper/queue_tracker.py), not L2 top-of-book crossing, and
gated on the quote having actually been live long enough
(paper/execution_latency.py) -- **no real orders are ever sent anywhere.**
Every quote, fill, Greeks snapshot, and hedge is persisted to
runtime/paper_sessions/*.jsonl (paper/session_log.py) for post-hoc replay
(paper/session_replay.py).

Run: python examples/paper_trading_bot.py [seconds]
Defaults to running for 120 seconds (Ctrl-C also works).
"""
from __future__ import annotations

import asyncio
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from rich.live import Live

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.models.options.black76 import OptionType
from deribit.rest import DeribitREST
from exchanges.binance_connector import BinanceOrderBookConnector
from exchanges.deribit_connector import DeribitOrderBookConnector
from exchanges.deribit_trades import DeribitTradeStreamConnector
from exchanges.stream_manager import MultiExchangeStreamManager, StreamSpec
from paper.dashboard import MarketDashboard
from paper.engine import PaperTradingEngine, QuotedOption, QuotedPerp
from paper.instruments import find_near_the_money_option
from utils.logger import get_logger

log = get_logger(__name__)

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
    quoted_option_symbols = [opt.key[2] for opt in quoted_options]
    all_deribit_symbols = list(_DERIBIT_PERP.values()) + quoted_option_symbols

    quoted_perps = [QuotedPerp(key=("deribit", "perpetual", name), underlying_ccy=ccy) for ccy, name in _DERIBIT_PERP.items()]
    reference_keys = [
        ("binance", "spot", sym) for sym in _BINANCE_SYMBOL.values()
    ] + [
        ("binance", "perpetual", sym) for sym in _BINANCE_SYMBOL.values()
    ]

    session_dir = _REPO_ROOT / "runtime" / "paper_sessions"
    session_path = session_dir / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S}.jsonl"
    log.info("session log: %s", session_path)

    engine = PaperTradingEngine(
        quoted_perps=quoted_perps, quoted_options=quoted_options, reference_keys=reference_keys,
        session_log_path=session_path,
    )

    manager = MultiExchangeStreamManager(
        [
            StreamSpec(DeribitOrderBookConnector(), list(_DERIBIT_PERP.values())),
            StreamSpec(DeribitOrderBookConnector(market_type="option"), quoted_option_symbols, depth=5),
            StreamSpec(BinanceOrderBookConnector("spot"), list(_BINANCE_SYMBOL.values())),
            StreamSpec(BinanceOrderBookConnector("perpetual"), list(_BINANCE_SYMBOL.values())),
        ]
    )
    trade_connector = DeribitTradeStreamConnector()

    async def consume_books() -> None:
        async for update in manager.stream():
            engine.on_book_update(update)

    async def consume_trades() -> None:
        async for trade in trade_connector.stream_trades(all_deribit_symbols):
            engine.on_trade(trade)

    dashboard = MarketDashboard()

    def _render():
        elapsed = time.time() - engine.start_time
        return dashboard.render(
            engine.snapshot(), elapsed, engine.n_fills,
            n_hard_hedges=engine.n_hard_hedges, portfolio_greeks=engine.portfolio_greeks,
            regimes=engine.regimes, warmup_statuses=engine.warmup_statuses(),
            recent_fills=list(engine.recent_fills), risk_snapshots=engine.risk_snapshots(),
        )

    async def render_loop(live: Live) -> None:
        # Redraws on every book update/trade fill (engine.update_event), not on a fixed
        # timer -- the table is only ever as stale as the last real market event.
        while True:
            await engine.update_event.wait()
            engine.update_event.clear()
            live.update(_render())

    tasks = [
        asyncio.create_task(consume_books()),
        asyncio.create_task(consume_trades()),
    ]
    with Live(_render(), refresh_per_second=20, screen=True) as live:
        tasks.append(asyncio.create_task(render_loop(live)))
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
            engine.close()
            live.update(_render())

    log.info("done — %d total fills, %d hard hedges, session log: %s", engine.n_fills, engine.n_hard_hedges, session_path)


if __name__ == "__main__":
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 120.0
    asyncio.run(main(seconds))
