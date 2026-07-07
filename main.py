import asyncio

from config.settings import Settings
from data.feed import MarketDataFeed
from data.orderbook import OrderBook
from exchange.registry import get_connector
from utils.logger import get_logger

log = get_logger("aletheia")


async def main() -> None:
    settings = Settings.load()
    log.info("venue=%s  symbol=%s  dry_run=%s", settings.venue, settings.symbol, settings.dry_run)

    creds = settings.credentials[settings.venue]
    connector = get_connector(settings.venue, creds.api_key, creds.api_secret)
    book = OrderBook()
    feed = MarketDataFeed(connector)

    def on_book(snapshot: dict) -> None:
        book.update(snapshot)
        if book.ready:
            log.info(
                "bid=%.2f  ask=%.2f  spread=%.2f  mid=%.2f  μprice=%.2f  imbal=%+.3f",
                book.best_bid, book.best_ask, book.spread,
                book.mid, book.microprice, book.imbalance,
            )

    feed.on_order_book(on_book)

    try:
        await feed.run(settings.symbol, depth=settings.ob_depth)
    finally:
        await connector.close()


if __name__ == "__main__":
    asyncio.run(main())
