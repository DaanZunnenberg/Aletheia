from __future__ import annotations

# Dependencies: execution.orders.OrderRouter, execution.oms.OMS,
#               execution.killswitch.KillSwitch, config.settings.PlacerConfig,
#               utils.logger, utils.latency
# Consumed by: core.strategy
#
# Manages the set of live quotes. Decides whether to place, amend, or cancel
# based on the difference between current live orders and desired quotes.
#
# Placer.sync(bid, ask, bid_size, ask_size) → None
#   Compares desired quotes against live orders from OMS.
#   - No live order on a side: place new limit order via orders.place()
#   - Live order price differs by > reprice_threshold: amend via orders.amend()
#   - No quote desired (risk gate failed upstream): cancel via orders.cancel()
#   reprice_threshold is configurable (default: 0.5 × tick_size)
#
# Placer.cancel_all() → None
#   Cancels all live orders. Called on risk gate failure or kill switch.
#
# Placer.cancel_passive() → None
#   Cancels only the passive side (the side adding to inventory risk).
#   Called before sending an aggressive rebalance order.
#
# Placer.send_rebalance(side, size) → None
#   Sends a market or marketable limit order to reduce inventory breach.
#   Bypasses normal quote logic; goes directly via orders.place().
