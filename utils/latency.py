from __future__ import annotations

# Dependencies: time, collections.deque
# Consumed by: execution.orders, execution.placer, core.strategy
#
# Tick-to-trade latency tracking. Timestamps every stage of the quoting pipeline.
# All functions are dependency-free and have no side effects beyond the deque.
#
# Stages measured:
#   market_received   — exchange timestamp on the order book event
#   local_received    — time.monotonic() at feed handler receipt
#   state_built       — MarketState construction complete
#   quote_computed    — model.compute_quotes() returned
#   risk_checked      — all risk gates passed
#   order_sent        — order instruction dispatched to exchange connector
#   order_acked       — exchange ack received
#
# LatencyTracker:
#   record(event_id, stage, t) → None     — store a timestamp for a stage
#   summarise(event_id) → dict[str,float] — per-stage deltas in milliseconds
#   rolling_stats(stage_pair) → (p50, p95, p99)  — percentile latencies over window
