from __future__ import annotations

# Dependencies: deribit.types.Trade, numpy
# Consumed by: core.market_state (via feed callbacks)
#
# Aggregates raw trade events into flow metrics:
#   - signed volume (buyer- vs seller-initiated)
#   - trade imbalance over a rolling window
#   - VPIN proxy (volume-synchronised probability of informed trading)
#   - Kyle's lambda (price impact per unit signed flow)
