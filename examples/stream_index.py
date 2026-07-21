"""
Live index price printer.

Usage:
    python -m examples.stream_index              # BTC
    python -m examples.stream_index eth          # ETH
"""

import asyncio
import sys
from datetime import datetime, timezone

from deribit import DeribitConnector


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


async def main() -> None:
    currency = sys.argv[1].lower() if len(sys.argv) > 1 else "btc"
    index_name = f"{currency}_usd"

    # Public market data always reads from mainnet.
    connector = DeribitConnector(testnet=False)

    print(f"Streaming {index_name} index price …\n")
    async for idx in connector.watch_index(index_name):
        print(f"{_now()}  {index_name.upper():>10}  {idx['price']:>12,.2f}  USD")


if __name__ == "__main__":
    asyncio.run(main())
