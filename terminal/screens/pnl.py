from __future__ import annotations

# Dependencies: textual, terminal.bridge.LiveState
# Consumed by: terminal.app
#
# PnL panel: displays all three P&L components separately.
#   Spread capture:    cumulative gross edge from round-trips
#   Inventory cost:    live mark-to-market on open position
#   Adverse selection: realised losses from informed fills
#   Fee drag:          cumulative fees
#   Total P&L:         sum of all components
# Updates on every state.json poll cycle.
