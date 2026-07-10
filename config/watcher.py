from __future__ import annotations

# Dependencies: asyncio, pathlib, time, config.settings.Settings, utils.logger
# Consumed by: main.py
#
# Watches config/.env for changes and hot-reloads parameters without
# restarting the process or interrupting the quoting loop.
#
# Only reloads safe runtime parameters (spread floor, size, gamma, etc.).
# Credentials and venue settings require a full restart.
#
# ConfigWatcher:
#   async run() → None
#     Polls config/.env mtime every N seconds.
#     On change: reload Settings, diff against current, apply safe params,
#     log a summary of what changed.
#
# Safe to hot-reload:
#   gamma, spread_floor_bps, max_notional, quote_size,
#   vpin_pause_threshold, drawdown_limit
#
# Requires restart:
#   venue, symbol, api_key, api_secret, dry_run
