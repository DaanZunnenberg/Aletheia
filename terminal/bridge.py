from __future__ import annotations

# Dependencies: asyncio, orjson, pathlib
# Consumed by: terminal.app
#
# Reads runtime/state.json and exposes a clean typed interface to the TUI.
# Decouples the terminal from live strategy objects — the terminal never
# imports from core/ or execution/ directly.
#
# runtime/state.json is written by core.strategy on each quoting cycle:
#   {
#     "mid": float,
#     "bid": float, "ask": float,
#     "bid_size": float, "ask_size": float,
#     "position": float, "avg_entry": float,
#     "unrealised_pnl": float,
#     "spread_capture": float, "inventory_cost": float,
#     "fee_drag": float, "total_pnl": float,
#     "regime": str,
#     "vpin": float,
#     "inventory_fraction": float,
#     "kill_switch_active": bool,
#     "updated_at": float
#   }
#
# StateBridge:
#   async poll(interval) → AsyncIterator[LiveState]
#     Reads and parses state.json every `interval` seconds.
#     Yields LiveState dataclass; skips silently if file is missing or stale.
