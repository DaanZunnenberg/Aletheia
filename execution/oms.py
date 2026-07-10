from __future__ import annotations

# Dependencies: dataclasses, enum, asyncio, utils.logger
# Consumed by: execution.placer, execution.tracker, execution.orders
#
# Order Management System. Owns the full lifecycle of every order.
# The only module allowed to transition order state.
#
# OrderState enum: PENDING | SENT | ACKED | PARTIALLY_FILLED | FILLED | CANCELLED | REJECTED
#
# Order dataclass:
#   client_order_id  str         — deterministic ID generated here; idempotency key
#   venue_order_id   str | None  — assigned by exchange on ack
#   instrument       str
#   side             Side        — BID | ASK
#   price            float
#   size             float
#   filled_size      float
#   state            OrderState
#   created_at       float       — unix epoch seconds
#   updated_at       float
#
# OMS methods:
#   create(instrument, side, price, size) → Order
#   on_ack(client_order_id, venue_order_id) → None
#   on_fill(venue_order_id, filled_qty, fill_price) → Order
#   on_cancel(venue_order_id) → None
#   on_reject(client_order_id, reason) → None
#   get_live_orders() → list[Order]
#   get_order(client_order_id) → Order | None
#
# Persistence: writes order state to a WAL file in runtime/ on every transition.
# On startup, replays the WAL to reconstruct live order state before connecting.
