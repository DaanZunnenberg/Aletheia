"""
First end-to-end live quoting loop: real L2 book data (exchanges/) feeding
the existing Avellaneda-Stoikov model (core/) to produce real-time quotes.

Deliberately the simplest version that works, not the most capable one --
single instrument, single exchange, dry-run only (prints quotes, places no
orders), mark_price/index_price approximated by the live mid (no ticker/
funding stream wired in yet). Extending to multi-instrument, the GLFT+regime
engine, real mark price, and actual order placement are all natural next
steps once this loop is proven out end to end.

Layers exercised, matching core/MODEL.md's architecture:
  - volatility : core.models.volatility.ewma_volatility on the live mid series
  - logic      : core.strategies.market_maker.generate_quotes (Avellaneda-Stoikov)
  - risk       : core.risk.limits.RiskLimits / core.risk.exposure.Position
  - tail risk  : core.risk.tail_risk.TailRiskMonitor -- halts quoting on a
                 price jump, a stale feed, or an abnormal vol spike
  - inventory  : core.risk.exposure.Position, updated only by real fills in
                 a live system; here it stays flat since nothing executes

Run: python examples/live_quote_loop.py [seconds]
Defaults to running for 30 seconds then exiting (Ctrl-C also works).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pandas as pd

from core.market_state import MarketState
from core.models.quoting import QuotingParams
from core.models.volatility import ewma_volatility
from core.risk.exposure import Position
from core.risk.limits import RiskLimits
from core.risk.tail_risk import TailRiskLimits, TailRiskMonitor
from core.strategies.market_maker import generate_quotes
from exchanges.deribit_connector import DeribitOrderBookConnector
from utils.logger import get_logger

log = get_logger(__name__)

_INSTRUMENT = "BTC-PERPETUAL"
_VOL_HALFLIFE_SECONDS = 60.0
_VOL_WARMUP_UPDATES = 20
_QUOTING_PARAMS = QuotingParams(gamma=5.0, time_horizon=1.0, kappa=1.5, A=0.05)
_RISK_LIMITS = RiskLimits()
_TAIL_RISK_LIMITS = TailRiskLimits()


async def main(run_seconds: float) -> None:
    connector = DeribitOrderBookConnector()
    position = Position()  # flat -- nothing executes in this demo, dry-run only
    tail_risk = TailRiskMonitor(_TAIL_RISK_LIMITS)
    mid_history: list[float] = []

    async def quote_loop() -> None:
        async for book in connector.stream_order_books([_INSTRUMENT], depth=5):
            now = book.timestamp / 1000.0
            tail_risk.update(now, book.mid_price)
            mid_history.append(book.mid_price)

            if len(mid_history) < _VOL_WARMUP_UPDATES:
                continue
            sigma = ewma_volatility(
                pd.Series(mid_history[-_VOL_WARMUP_UPDATES * 5:]), _VOL_HALFLIFE_SECONDS, sampling_seconds=1.0
            )

            halted, tail_breaches = tail_risk.should_halt(now)
            if halted:
                log.warning("TAIL RISK HALT: %s", "; ".join(tail_breaches))
                continue

            state = MarketState(
                instrument_name=_INSTRUMENT,
                best_bid_price=book.best_bid,
                best_ask_price=book.best_ask,
                best_bid_size=book.bids[0][1] if book.bids else 0.0,
                best_ask_size=book.asks[0][1] if book.asks else 0.0,
                mark_price=book.mid_price,   # approximation -- no ticker stream wired in yet
                index_price=book.mid_price,  # approximation -- see module docstring
                current_funding=None,
                timestamp=book.timestamp,
            )
            decision = generate_quotes(state, position, sigma, _QUOTING_PARAMS, _RISK_LIMITS)

            log.info(
                "%s  mid=%.2f  sigma=%.3f  bid=%.2f(%.3f)  ask=%.2f(%.3f)  spread=%.2f%s",
                _INSTRUMENT, book.mid_price, sigma,
                decision.bid_price, decision.bid_size, decision.ask_price, decision.ask_size,
                decision.ask_price - decision.bid_price,
                f"  breaches={decision.breaches}" if decision.breaches else "",
            )

    task = asyncio.create_task(quote_loop())
    try:
        await asyncio.sleep(run_seconds)
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0
    asyncio.run(main(seconds))
