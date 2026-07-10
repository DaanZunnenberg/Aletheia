from __future__ import annotations

# Dependencies: exchange.base.BaseRestConnector, execution.pretrade.PreTradeGate,
#               execution.oms.OMS, utils.logger, utils.latency, utils.metrics
# Consumed by: execution.placer (only module that calls this)
#
# Single choke point for all outbound order instructions.
# No other module sends orders to the exchange directly.
#
# OrderRouter:
#   async place(order) → str | None
#     1. pretrade.check(order) — abort if False
#     2. connector.place_order(order) — send to exchange
#     3. oms.on_ack(...) on success, oms.on_reject(...) on failure
#     4. Record send timestamp for latency tracking
#     Returns venue_order_id or None on rejection.
#
#   async amend(client_order_id, new_price, new_size) → bool
#     Amend in-place if exchange supports it; cancel+replace otherwise.
#
#   async cancel(client_order_id) → bool
#
#   async cancel_all() → None
#     Issues cancel for every order in oms.get_live_orders().
#     Used by kill switch — must be resilient to partial failures.
