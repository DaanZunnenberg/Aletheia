import asyncio

from config.settings import Settings
from data.feed import DeribitFeed
from data.orderbook import OrderBook
from deribit import DeribitConnector
from deribit.types import OrderBookSnapshot
from utils.logger import get_logger

log = get_logger("aletheia")


async def main() -> None:
    settings = Settings.load()
    log.info("symbol=%s  testnet=%s  dry_run=%s", settings.symbol, settings.testnet, settings.dry_run)

    connector = DeribitConnector(settings.api_key, settings.api_secret, testnet=settings.testnet)
    book = OrderBook()
    feed = DeribitFeed(connector)

    def on_book(snapshot: OrderBookSnapshot) -> None:
        book.update(snapshot)
        if book.ready:
            log.info(
                "bid=%.2f  ask=%.2f  spread=%.4f  mid=%.4f  μprice=%.4f  imbal=%+.3f",
                book.best_bid, book.best_ask, book.spread,
                book.mid, book.microprice, book.imbalance,
            )

    feed.on_order_book(on_book)
    await feed.run_order_book(settings.symbol, depth=settings.ob_depth)


if __name__ == "__main__":
    asyncio.run(main())
