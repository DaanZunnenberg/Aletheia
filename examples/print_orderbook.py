"""
Live order book printer.

Connects to Deribit, subscribes to the configured instrument, and renders
a refreshing order book ladder in the terminal.

Usage:
    python -m examples.print_orderbook
"""

import asyncio
import sys

from config.settings import Settings
from data.feed import DeribitFeed
from data.orderbook import OrderBook
from deribit import DeribitConnector
from deribit.types import OrderBookSnapshot

LEVELS = 5

_RESET = "\033[0m"
_RED = "\033[31m"
_GREEN = "\033[32m"
_DIM = "\033[2m"
_CLEAR = "\033[H\033[J"


def print_book(book: OrderBook, levels: int = LEVELS) -> None:
    asks = book.asks[:levels]
    bids = book.bids[:levels]
    col_w = 14

    lines: list[str] = []
    lines.append(f"{_DIM}{'─' * (col_w * 2 + 5)}{_RESET}")
    lines.append(
        f"  {book.instrument}   mid {book.mid:.4f}"
        f"   spread {book.spread:.4f}   imbal {book.imbalance:+.3f}"
    )
    lines.append(f"{_DIM}{'─' * (col_w * 2 + 5)}{_RESET}")
    lines.append(f"  {'PRICE':>{col_w}}   {'QTY':>{col_w}}")
    lines.append(f"{_DIM}{'─' * (col_w * 2 + 5)}{_RESET}")

    for price, qty in asks[::-1]:
        lines.append(f"{_RED}  {price:>{col_w}.2f}   {qty:>{col_w}.4f}{_RESET}")

    lines.append(f"{_DIM}{'── mid ─── ' + f'{book.mid:.4f}':>{col_w * 2 + 5}}{_RESET}")

    for price, qty in bids:
        lines.append(f"{_GREEN}  {price:>{col_w}.2f}   {qty:>{col_w}.4f}{_RESET}")

    lines.append(f"{_DIM}{'─' * (col_w * 2 + 5)}{_RESET}")

    sys.stdout.write(_CLEAR + "\n".join(lines) + "\n")
    sys.stdout.flush()


async def main() -> None:
    settings = Settings.load()
    connector = DeribitConnector(settings.api_key, settings.api_secret, testnet=settings.testnet)
    book = OrderBook()
    feed = DeribitFeed(connector)

    def on_book(snapshot: OrderBookSnapshot) -> None:
        book.update(snapshot)
        if book.ready:
            print_book(book, levels=LEVELS)

    feed.on_order_book(on_book)
    await feed.run_order_book(settings.symbol, depth=max(LEVELS, settings.ob_depth))


if __name__ == "__main__":
    asyncio.run(main())
