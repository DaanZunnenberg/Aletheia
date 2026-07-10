from __future__ import annotations

# Dependencies: textual, terminal.bridge.LiveState
# Consumed by: terminal.app
#
# Inventory panel: position size, notional, inventory fraction bar (∈ [-1, 1]),
# average entry price, and distance to inventory hard limit.
# Bar turns red when inventory_fraction > 0.75.
