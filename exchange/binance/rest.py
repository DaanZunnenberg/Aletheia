from __future__ import annotations

# Dependencies: aiohttp, exchange.base.BaseRestConnector, config.settings.VenueCredentials
# Consumed by: exchange.registry
#
# Binance REST connector: implements BaseRestConnector for spot and perpetual markets.
# Handles authentication (HMAC-SHA256), rate limit tracking, and order serialisation
# to Binance's REST API format.
