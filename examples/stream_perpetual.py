"""
Live perpetual order book + funding printer.

Streams the top-of-book, mid, and funding rate for a Deribit perpetual —
the raw inputs the market-making model in core/ consumes. This is a
connectivity/data-plumbing test, not part of the live quoting loop.

Usage:
    python -m examples.stream_perpetual              # BTC-PERPETUAL
    python -m examples.stream_perpetual eth          # ETH-PERPETUAL
"""

import asyncio
import sys
from datetime import datetime, timezone

from deribit import DeribitConnector


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


async def stream_book(connector: DeribitConnector, instrument: str) -> None:
    async for book in connector.watch_order_book(instrument):
        if not book["bids"] or not book["asks"]:
            continue
        bid_price, bid_size = book["bids"][0]
        ask_price, ask_size = book["asks"][0]
        mid = 0.5 * (bid_price + ask_price)
        print(
            f"{_now()}  {instrument:>14}  "
            f"bid={bid_price:>10,.2f} ({bid_size:.3f})  "
            f"ask={ask_price:>10,.2f} ({ask_size:.3f})  "
            f"mid={mid:>10,.2f}"
        )


async def stream_funding(connector: DeribitConnector, instrument: str) -> None:
    async for f in connector.watch_funding(instrument):
        print(f"{_now()}  {instrument:>14}  funding_8h={f['funding_8h']:.6f}")


async def main() -> None:
    currency = sys.argv[1].upper() if len(sys.argv) > 1 else "BTC"
    instrument = f"{currency}-PERPETUAL"

    connector = DeribitConnector(testnet=False)

    print(f"Streaming {instrument} order book and funding …\n")
    await asyncio.gather(
        stream_book(connector, instrument),
        stream_funding(connector, instrument),
    )


if __name__ == "__main__":
    asyncio.run(main())
