from __future__ import annotations

# Dependencies: asyncio, utils.logger, utils.metrics
# Consumed by: execution.pretrade, core.strategy, main.py
#
# First-class kill switch. Operates independently of the quoting loop.
# Can be triggered from multiple sources simultaneously.
#
# KillSwitch:
#   active: bool                       — checked synchronously in pretrade
#
#   async trigger(reason) → None       — sets active=True, fires cancel_all,
#                                        emits alert, writes to runtime/killswitch.log
#   async reset(reason) → None         — sets active=False (manual operator action only)
#   async _cancel_all() → None         — calls exchange.cancel_all() directly,
#                                        bypassing the normal placer/OMS path
#
# Trigger sources:
#   - automated: inventory breach, drawdown limit, adverse selection spike, feed staleness
#   - manual: operator signal (SIGUSR1 or terminal command)
#   - watchdog: if no orderbook update received in N seconds, auto-trigger
