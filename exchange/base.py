from __future__ import annotations

# Dependencies: abc, typing
# Consumed by: exchange.registry, exchange.binance.rest, exchange.binance.ws,
#              deribit.connector (should be refactored to implement this interface)
#
# Abstract base classes for all venue connectors:
#   BaseRestConnector  — place_order, amend_order, cancel_order, cancel_all,
#                        get_position, get_open_orders, get_fills
#   BaseWebSocketConnector — watch_order_book, watch_trades, watch_fills
#
# All concrete connectors must implement these interfaces.
# execution.orders is the only module that calls into connectors directly.
