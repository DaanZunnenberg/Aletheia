from __future__ import annotations

# Dependencies: time, collections.deque, utils.logger
# Consumed by: execution.killswitch, execution.orders, execution.pnl,
#              core.strategy, terminal.bridge
#
# Structured metrics pipeline. Emits time-series observations that can be
# consumed by the terminal display or written to a file for post-session analysis.
#
# Metric categories:
#   LATENCY   — tick-to-trade stages (from latency.py)
#   BUSINESS  — fill_rate_bid, fill_rate_ask, spread_capture_per_trade,
#               inventory_drift, vpin_level, regime
#   RISK      — drawdown, inventory_fraction, kill_switch_events
#   SYSTEM    — feed_staleness, reconnect_count, order_reject_rate
#
# Metrics:
#   emit(category, name, value, tags) → None  — push an observation
#   snapshot() → dict                         — latest value per metric name
#   rolling(name, window) → np.ndarray        — recent observations as array
#
# Sink: in-memory ring buffer by default. Optional: write to runtime/metrics.jsonl.
