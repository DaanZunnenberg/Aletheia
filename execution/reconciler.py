from __future__ import annotations

# Dependencies: exchange.base.BaseRestConnector, execution.oms.OMS,
#               core.portfolio.Portfolio, utils.logger
# Consumed by: main.py (runs as a periodic async task, separate from quoting loop)
#
# Compares internal state against exchange state and flags discrepancies.
# Runs every N minutes intraday and at session end.
#
# Reconciler.run() → ReconciliationReport
#   1. Fetch live orders from exchange REST (connector.get_open_orders())
#   2. Compare against oms.get_live_orders()
#      → orders present in OMS but not on exchange: mark as CANCELLED in OMS
#      → orders on exchange but not in OMS: log as GHOST ORDER (manual review)
#   3. Fetch positions from exchange REST (connector.get_position())
#   4. Compare against portfolio.position
#      → discrepancy > tolerance: flag POSITION_MISMATCH, do not auto-correct
#   5. Write report to runtime/reconciliation.log
#
# Discrepancies are logged and alerted but never auto-corrected.
# Position mismatches require manual operator review.
