from __future__ import annotations

# Dependencies: execution.oms.OMS, core.portfolio.Portfolio,
#               execution.pnl.PnLEngine, utils.logger
# Consumed by: data.feed (fill events from WS), core.strategy
#
# Reconciles fill events from the exchange WebSocket with OMS order state.
# The only module that calls portfolio.on_fill() and pnl.record().
#
# Tracker.on_fill_event(event) → None
#   1. Parse raw fill event from exchange WS
#   2. oms.on_fill(venue_order_id, filled_qty, fill_price) → Order
#   3. portfolio.on_fill(fill)
#   4. pnl.record(fill)
#   5. strategy.on_fill(fill)  — triggers rebalance check if needed
#
# Tracker.on_cancel_event(event) → None
#   oms.on_cancel(venue_order_id)
#
# Tracker.on_reject_event(event) → None
#   oms.on_reject(client_order_id, reason); log and alert
