from __future__ import annotations

# Dependencies: exchange.base, exchange.binance.rest, exchange.binance.ws
# Consumed by: main.py, config.settings
#
# Maps venue name strings to (RestConnector, WebSocketConnector) class pairs.
# config.settings.venue determines which connector pair is instantiated at boot.
#
# Example:
#   REGISTRY = {
#       "deribit":  (DeribitRestConnector,  DeribitWebSocketConnector),
#       "binance":  (BinanceRestConnector,  BinanceWebSocketConnector),
#   }
