from __future__ import annotations

# Dependencies: execution.killswitch.KillSwitch, config.settings.RiskLimits,
#               execution.oms.OMS, utils.logger
# Consumed by: execution.orders (wraps every outbound order instruction)
#
# Pre-trade risk gate. Sits between the strategy and the exchange.
# Checks every order regardless of source — does not know about the model.
# All checks are synchronous and must complete in < 1ms.
#
# check(order, portfolio, limits) → bool
#   Runs all checks in sequence; returns False on first failure and logs reason.
#
# Individual checks (all pure functions):
#   _check_kill_switch(ks)                     → bool  — hard block if active
#   _check_fat_finger(order, mid, limits)      → bool  — price within X% of mid
#   _check_size_limit(order, limits)           → bool  — size < per_order_max
#   _check_gross_notional(order, oms, limits)  → bool  — open orders notional < max
#   _check_net_delta(order, portfolio, limits) → bool  — net position notional < max
