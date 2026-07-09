"""
Live options chain printer.

Subscribes to the markprice.options.{index} channel, which delivers mark prices
and implied volatility for every listed option on that index in a single stream.
Also fetches the current index price via REST on startup for context.

Usage:
    python -m examples.stream_options                     # BTC options
    python -m examples.stream_options eth                 # ETH options
"""

import asyncio
import sys
from datetime import datetime, timezone

from deribit import DeribitConnector, DeribitREST
from deribit.types import OptionMarkPrice

_CLEAR = "\033[H\033[J"
_DIM = "\033[2m"
_RESET = "\033[0m"
_CYAN = "\033[36m"
_YELLOW = "\033[33m"


def _format_expiry(name: str) -> str:
    """Extract expiry string from instrument name, e.g. 'BTC-26DEC25-100000-C' → '26DEC25'."""
    parts = name.split("-")
    return parts[1] if len(parts) >= 3 else ""


def render(
    prices: list[OptionMarkPrice],
    index_name: str,
    index_price: float,
    update_count: int,
) -> None:
    by_expiry: dict[str, list[OptionMarkPrice]] = {}
    for p in prices:
        expiry = _format_expiry(p["instrument_name"])
        by_expiry.setdefault(expiry, []).append(p)

    now = datetime.now(timezone.utc).strftime("%H:%M:%S")
    lines: list[str] = [
        f"{_DIM}{'─' * 72}{_RESET}",
        f"  {_CYAN}{index_name.upper()}{_RESET}  index {index_price:,.2f}   "
        f"options {len(prices)}   updates {update_count}   {now} UTC",
        f"{_DIM}{'─' * 72}{_RESET}",
        f"  {'INSTRUMENT':<35} {'MARK':>10} {'MARK IV':>10}",
        f"{_DIM}{'─' * 72}{_RESET}",
    ]

    for expiry in sorted(by_expiry):
        entries = sorted(
            by_expiry[expiry],
            key=lambda x: (x["instrument_name"].split("-")[2] if len(x["instrument_name"].split("-")) >= 4 else "0",
                           x["instrument_name"]),
        )
        lines.append(f"{_YELLOW}  {expiry}{_RESET}")
        for p in entries:
            lines.append(
                f"  {p['instrument_name']:<35} {p['mark_price']:>10.6f} {p['mark_iv']:>9.1f}%"
            )

    sys.stdout.write(_CLEAR + "\n".join(lines) + "\n")
    sys.stdout.flush()


async def main() -> None:
    currency = sys.argv[1].upper() if len(sys.argv) > 1 else "BTC"
    index_name = f"{currency.lower()}_usd"

    # Public market data always reads from mainnet.
    rest = DeribitREST(testnet=False)
    connector = DeribitConnector(testnet=False)

    idx = await rest.get_index_price(index_name)
    index_price = idx["price"]

    update_count = 0

    try:
        async for prices in connector.watch_mark_prices(index_name):
            update_count += 1
            render(prices, index_name, index_price, update_count)
    finally:
        await rest.close()


if __name__ == "__main__":
    asyncio.run(main())
