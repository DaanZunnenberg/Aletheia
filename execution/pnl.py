from __future__ import annotations

# Dependencies: dataclasses, numpy, core.portfolio.Portfolio, utils.logger
# Consumed by: execution.tracker, core.strategy, terminal.bridge
#
# Decomposes P&L into three independent components from the first fill.
# Never aggregates into a single number without also reporting components.
#
# PnLState (immutable snapshot, rebuilt on each fill):
#   spread_capture    float  — gross edge: sum of (ask_fill_price - bid_fill_price)
#                              on completed round-trips
#   inventory_cost    float  — mark-to-market: position × (current_mid - avg_entry)
#                              negative when open position moves against us
#   adverse_selection float  — realised loss on fills that immediately move against us
#                              (proxy: fill_price - mid N seconds after fill, signed)
#   fee_drag          float  — cumulative fees paid (maker + taker, always negative)
#   realised_pnl      float  — spread_capture + adverse_selection + fee_drag
#                              (inventory_cost excluded — unrealised)
#   total_pnl         float  — realised_pnl + inventory_cost
#
# PnLEngine:
#   record(fill) → None          — update on every fill from tracker
#   mark(mid) → None             — update inventory_cost on each mid update
#   snapshot() → PnLState        — return current immutable state
#   reset() → None               — session reset (start of day)
