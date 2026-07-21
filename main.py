"""
Aletheia — perpetual market-making framework.

Test entry point: fetch the current BTC/ETH perpetual order book + ticker,
build a MarketState, and print a single quoting decision from the
Avellaneda-Stoikov model. This is infrastructure for exercising the model in
core/, not a live trading loop — order placement is not implemented.
"""
from __future__ import annotations

import asyncio

from config.settings import Settings
from deribit.rest import DeribitREST
from data.normalization import build_market_state
from core.models.quoting import QuotingParams
from core.risk.exposure import Position
from core.risk.limits import RiskLimits
from core.strategies.market_maker import generate_quotes
from utils.logger import get_logger

log = get_logger(__name__)

# Fixed until a proper vol estimator is wired up from a rolling mid-price history
# (core/models/volatility.py needs a sampled series; a single snapshot has none).
_PLACEHOLDER_SIGMA = 0.6


async def quote_perpetual(rest: DeribitREST, currency: str) -> None:
    instrument_name = f"{currency}-PERPETUAL"
    ticker, book = await asyncio.gather(
        rest.get_ticker(instrument_name),
        rest.get_order_book(instrument_name),
    )
    state = build_market_state(ticker, book)

    params = QuotingParams(gamma=0.1, time_horizon=1.0 / 365.0, kappa=1.5, A=140.0)
    limits = RiskLimits.conservative()
    position = Position()

    decision = generate_quotes(state, position, _PLACEHOLDER_SIGMA, params, limits)

    log.info(
        "%s  mid=%.2f  bid=%.2f (size=%.4f, skip=%s)  ask=%.2f (size=%.4f, skip=%s)",
        instrument_name, state.mid_price,
        decision.bid_price, decision.bid_size, decision.skip_bid,
        decision.ask_price, decision.ask_size, decision.skip_ask,
    )
    if decision.breaches:
        log.warning("  risk breaches: %s", "; ".join(decision.breaches))


async def main() -> None:
    settings = Settings.load()
    rest = DeribitREST(
        api_key=settings.api_key,
        api_secret=settings.api_secret,
        testnet=settings.testnet,
    )
    try:
        for currency in settings.currencies:
            await quote_perpetual(rest, currency)
    finally:
        await rest.close()


if __name__ == "__main__":
    asyncio.run(main())
