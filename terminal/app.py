from __future__ import annotations

# Dependencies: textual, terminal.bridge.StateBridge,
#               terminal.screens.quotes, terminal.screens.inventory,
#               terminal.screens.pnl, terminal.screens.risk
# Consumed by: main.py (launched as a concurrent async task)
#
# Textual TUI application. Reads state exclusively via terminal.bridge.
# Never imports from core/, execution/, or exchange/.
#
# Layout (single screen, tabbed panels):
#   Top bar:    instrument | regime | kill switch status | system time
#   Left:       live quotes panel (terminal.screens.quotes)
#   Centre:     order book depth visualisation
#   Right:      inventory + PnL panel (terminal.screens.pnl)
#   Bottom bar: latency stats | fill rate | VPIN | reconnect count
#
# Keybindings:
#   k  — trigger kill switch (with confirmation prompt)
#   r  — reset kill switch
#   q  — quit
