"""
Live order book printer.

Connects to Deribit, subscribes to the configured symbol, and renders
a refreshing order book ladder in the terminal up to LEVELS price levels.

Usage:
    python -m examples.print_orderbook
"""

import asyncio
import sys

from config.settings import Settings
from data.feed import MarketDataFeed
from data.orderbook import OrderBook
from exchange.base import OrderBookSnapshot
from exchange.registry import get_connector

LEVELS = 5  # number of bid and ask levels to display

_RESET = "\033[0m"
_RED = "\033[31m"
_GREEN = "\033[32m"
_DIM = "\033[2m"
_CLEAR = "\033[H\033[J"  # move cursor home and erase screen


def print_book(book: OrderBook, symbol: str, levels: int = LEVELS) -> None:
    asks = book.asks[:levels]   # ascending: best ask at index 0
    bids = book.bids[:levels]   # descending: best bid at index 0

    col_w = 14

    lines: list[str] = []
    lines.append(f"{_DIM}{'─' * (col_w * 2 + 5)}{_RESET}")
    lines.append(f"  {symbol}   mid {book.mid:.2f}   spread {book.spread:.2f}   imbal {book.imbalance:+.3f}")
    lines.append(f"{_DIM}{'─' * (col_w * 2 + 5)}{_RESET}")
    lines.append(f"  {'PRICE':>{col_w}}   {'QTY':>{col_w}}")
    lines.append(f"{_DIM}{'─' * (col_w * 2 + 5)}{_RESET}")

    # Asks: print far → near (reverse order so best ask is nearest the mid line)
    for price, qty in asks[::-1]:
        lines.append(f"{_RED}  {price:>{col_w}.2f}   {qty:>{col_w}.4f}{_RESET}")

    lines.append(f"{_DIM}{'── mid ─── ' + f'{book.mid:.2f}':>{col_w * 2 + 5}}{_RESET}")

    for price, qty in bids:
        lines.append(f"{_GREEN}  {price:>{col_w}.2f}   {qty:>{col_w}.4f}{_RESET}")

    lines.append(f"{_DIM}{'─' * (col_w * 2 + 5)}{_RESET}")

    sys.stdout.write(_CLEAR + "\n".join(lines) + "\n")
    sys.stdout.flush()


async def main() -> None:
    settings = Settings.load()
    creds = settings.credentials[settings.venue]
    connector = get_connector(settings.venue, creds.api_key, creds.api_secret, testnet=settings.testnet)

    book = OrderBook()
    feed = MarketDataFeed(connector)

    def on_book(snapshot: OrderBookSnapshot) -> None:
        book.update(snapshot)
        if book.ready:
            print_book(book, settings.symbol, levels=LEVELS)

    feed.on_order_book(on_book)

    try:
        await feed.run(settings.symbol, depth=max(LEVELS, settings.ob_depth))
    finally:
        await connector.close()


if __name__ == "__main__":
    asyncio.run(main())
