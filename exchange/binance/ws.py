from __future__ import annotations

# Dependencies: websockets, orjson, exchange.base.BaseWebSocketConnector
# Consumed by: exchange.registry
#
# Binance WebSocket connector: implements BaseWebSocketConnector.
# Manages combined stream connections, sequence number tracking,
# reconnection with exponential backoff, and dispatches normalised events.
