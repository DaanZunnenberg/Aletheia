"""
Live index price and DVOL (Deribit Volatility Index) printer.

Streams both the spot index price and the 30-day forward IV derived from options
(DVOL) for BTC or ETH concurrently.

Usage:
    python -m examples.stream_index              # BTC
    python -m examples.stream_index eth          # ETH
"""

import asyncio
import sys
from datetime import datetime, timezone

from deribit import DeribitConnector
from deribit.types import IndexPrice, VolatilityIndex

_state: dict[str, float] = {}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


async def stream_index(connector: DeribitConnector, index_name: str) -> None:
    async for idx in connector.watch_index(index_name):
        _state["index"] = idx["price"]
        print(f"{_now()}  {index_name.upper():>10}  {idx['price']:>12,.2f}  USD")


async def stream_dvol(connector: DeribitConnector, index_name: str) -> None:
    # Deribit DVOL channel uses price index name (btc_usd), not btc_dvol.
    async for dvol in connector.watch_volatility_index(index_name):
        _state["dvol"] = dvol["volatility"]
        label = index_name.upper().replace("_USD", "_DVOL")
        print(f"{_now()}  {label:>10}  {dvol['volatility']:>12.2f}  %")


async def main() -> None:
    currency = sys.argv[1].lower() if len(sys.argv) > 1 else "btc"
    index_name = f"{currency}_usd"

    # Public market data always reads from mainnet.
    connector = DeribitConnector(testnet=False)

    print(f"Streaming {index_name} index price and DVOL …\n")
    print(f"{'TIME':>8}  {'CHANNEL':>10}  {'VALUE':>12}  NOTE")
    print("─" * 52)

    await asyncio.gather(
        stream_index(connector, index_name),
        stream_dvol(connector, index_name),
    )


if __name__ == "__main__":
    asyncio.run(main())
