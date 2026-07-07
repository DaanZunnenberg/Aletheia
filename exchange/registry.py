from exchange.base import BaseConnector


def get_connector(venue: str, api_key: str = "", api_secret: str = "") -> BaseConnector:
    if venue == "binance":
        from exchange.binance.connector import BinanceConnector
        return BinanceConnector(api_key, api_secret)
    raise ValueError(f"Unknown venue: {venue!r}")
