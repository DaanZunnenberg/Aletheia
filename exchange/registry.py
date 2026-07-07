from exchange.base import BaseConnector


def get_connector(venue: str, api_key: str = "", api_secret: str = "", testnet: bool = False) -> BaseConnector:
    if venue == "binance":
        from exchange.binance.connector import BinanceConnector
        return BinanceConnector(api_key, api_secret)
    if venue == "deribit":
        from exchange.deribit.connector import DeribitConnector
        return DeribitConnector(api_key, api_secret, testnet=testnet)
    raise ValueError(f"Unknown venue: {venue!r}")
