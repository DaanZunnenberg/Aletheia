from __future__ import annotations

# Dependencies: numpy, collections.deque
# Consumed by: core.calibration
#
# Fixed-length ring buffer of recent OrderBookSnapshot and Trade events.
# Provides windowed arrays of mid-prices and signed volumes for
# volatility and flow calibration routines.
