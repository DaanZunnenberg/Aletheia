"""
Aletheia — option implied distribution arbitrage framework.

Research entry point: fetch a full Deribit option chain, build the IV surface,
extract the risk-neutral distribution per expiry, and print a summary.
"""
from __future__ import annotations

import asyncio

from config.settings import Settings
from deribit.rest import DeribitREST
from deribit.types import Instrument, Ticker
from core.market_state import FutureQuote, OptionQuote
from data.normalization import build_market_state, ticker_to_future_quote, ticker_to_option_quote
from core.options.surface import build_surface
from core.options.risk_neutral_distribution import extract_risk_neutral_distribution
from utils.logger import get_logger

log = get_logger(__name__)

# Deribit public endpoints: 20 req/s unauthenticated, higher with auth.
# Keep below the limit with a semaphore so the loop never gets rate-limited.
_TICKER_CONCURRENCY = 20


async def _fetch_option_ticker(
    rest: DeribitREST,
    sem: asyncio.Semaphore,
    inst: Instrument,
) -> OptionQuote | None:
    async with sem:
        try:
            ticker: Ticker = await rest.get_ticker(inst["instrument_name"])
            if ticker["mark_iv"] and ticker["mark_iv"] > 0:
                return ticker_to_option_quote(ticker, inst)
        except Exception as exc:
            log.warning("Ticker fetch failed for %s: %s", inst["instrument_name"], exc)
    return None


async def _fetch_future_ticker(
    rest: DeribitREST,
    sem: asyncio.Semaphore,
    inst: Instrument,
) -> FutureQuote | None:
    async with sem:
        try:
            ticker = await rest.get_ticker(inst["instrument_name"])
            return ticker_to_future_quote(ticker, inst)
        except Exception as exc:
            log.warning("Ticker fetch failed for %s: %s", inst["instrument_name"], exc)
    return None


async def fetch_market_state(rest: DeribitREST, currency: str):
    log.info("Fetching %s instruments…", currency)

    opt_instruments, fut_instruments, index = await asyncio.gather(
        rest.get_instruments(currency, "option"),
        rest.get_instruments(currency, "future"),
        rest.get_index_price(f"{currency.lower()}_usd"),
    )
    spot = index["price"]

    sem = asyncio.Semaphore(_TICKER_CONCURRENCY)

    active_opts = [i for i in opt_instruments if i["is_active"]]
    active_futs = [i for i in fut_instruments if i["is_active"]]

    opt_results, fut_results = await asyncio.gather(
        asyncio.gather(*[_fetch_option_ticker(rest, sem, i) for i in active_opts]),
        asyncio.gather(*[_fetch_future_ticker(rest, sem, i) for i in active_futs]),
    )

    option_quotes = [r for r in opt_results if r is not None]
    future_quotes = [r for r in fut_results if r is not None]

    log.info(
        "%s: fetched %d/%d option tickers, %d/%d future tickers",
        currency,
        len(option_quotes), len(active_opts),
        len(future_quotes), len(active_futs),
    )

    return build_market_state(currency, spot, option_quotes, future_quotes)


async def main() -> None:
    settings = Settings.load()
    rest = DeribitREST(
        api_key=settings.api_key,
        api_secret=settings.api_secret,
        testnet=settings.testnet,
    )

    try:
        for currency in settings.currencies:
            state = await fetch_market_state(rest, currency)
            log.info(
                "%s: spot=%.2f  options=%d  futures=%d  expiries=%d",
                currency,
                state.spot_price,
                len(state.option_chain),
                len(state.futures_curve),
                len(state.expiries()),
            )

            surface = build_surface(state)
            log.info("%s IV surface: %d slices", currency, len(surface.slices))

            for sl in surface.slices:
                try:
                    rnd = extract_risk_neutral_distribution(sl)
                    log.info(
                        "  expiry=%d T=%.3fy  valid=%s  mean=%.2f  skew=%.3f  kurt=%.3f",
                        sl.expiry_ts, sl.T, rnd.is_valid,
                        rnd.mean, rnd.skewness, rnd.kurtosis,
                    )
                except Exception as exc:
                    log.warning("  RND extraction failed for expiry %d: %s", sl.expiry_ts, exc)
    finally:
        await rest.close()


if __name__ == "__main__":
    asyncio.run(main())
