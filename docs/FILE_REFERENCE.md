# Aletheia — File Reference

Living reference for every file in the project. Update whenever a file is added,
removed, or its functionality or status changes.

Boot order is listed where it matters. "Status" is one of:
`stub` (file exists, no logic yet) | `active` (logic implemented) | `placeholder` (intentionally empty)

---

## Boot Order (main.py startup sequence)

1. `config/settings.py` — load environment
2. `exchange/registry.py` — resolve venue connector classes
3. `execution/oms.py` — replay WAL, reconstruct live order state
4. `execution/killswitch.py` — initialise, check for persisted active state
5. `core/portfolio.py` — initialise position (zero or restored from reconciliation)
6. `execution/pnl.py` — initialise P&L engine
7. `data/feed.py` — open WebSocket connection, begin receiving events
8. `core/strategy.py` — register callbacks, start calibration loop
9. `config/watcher.py` — start parameter hot-reload loop
10. `execution/reconciler.py` — start periodic reconciliation task
11. `terminal/app.py` — launch TUI (concurrent async task)

---

## config/

| File | Purpose | Status | Dependencies |
|------|---------|--------|--------------|
| `settings.py` | Loads `.env`; exposes `Settings`, `RiskLimits`, `PlacerConfig`, `VenueCredentials` dataclasses | active | `dotenv` |
| `watcher.py` | Hot-reloads safe runtime parameters from `.env` without restart | stub | `config.settings`, `utils.logger` |

---

## data/

| File | Purpose | Status | Dependencies |
|------|---------|--------|--------------|
| `feed.py` | WebSocket manager; dispatches order book, trade, and fill events via callbacks | active | `deribit.connector`, `deribit.types`, `utils.logger` |
| `orderbook.py` | Maintains live L2 state; computes `mid`, `microprice`, `imbalance`, `spread` | active | `numpy`, `deribit.types` |
| `trade_tape.py` | Aggregates trade events; computes signed volume, trade imbalance, VPIN proxy, Kyle λ | stub | `numpy` |
| `historical.py` | Fixed-length ring buffer of snapshots and trades for calibration | stub | `numpy`, `collections.deque` |

---

## exchange/

| File | Purpose | Status | Dependencies |
|------|---------|--------|--------------|
| `base.py` | Abstract `BaseRestConnector` and `BaseWebSocketConnector` interfaces | stub | `abc` |
| `registry.py` | Maps venue name → (RestConnector, WebSocketConnector) class pair | stub | `exchange.base`, `exchange.binance` |
| `binance/rest.py` | Binance REST connector (place, amend, cancel, position, fills) | stub | `aiohttp`, `exchange.base` |
| `binance/ws.py` | Binance WebSocket connector (order book, trades, fills streams) | stub | `websockets`, `orjson`, `exchange.base` |

Note: `deribit/` is the active connector today. `exchange/` is the abstraction layer
that will unify Deribit and future venues under `BaseRestConnector` / `BaseWebSocketConnector`.

---

## core/ (private submodule — github.com/DaanZunnenberg/aletheia-core)

| File | Purpose | Status | Dependencies |
|------|---------|--------|--------------|
| `market_state.py` | Immutable snapshot of market conditions rebuilt on every OB update; includes `Regime` enum | stub | `dataclasses`, `enum`, `numpy` |
| `portfolio.py` | Net position, avg entry, unrealised PnL, inventory fraction; updated only by `execution.tracker` | stub | `dataclasses`, `numpy` |
| `model.py` | Avellaneda-Stoikov / GLT pricing: reservation price + optimal spread → `(bid, ask, bid_size, ask_size)` | stub | `numpy`, `core.market_state`, `core.portfolio` |
| `calibration.py` | Fits σ, κ, γ from `historical.py`; runs off hot path via `asyncio.to_thread` | stub | `numpy`, `data.historical` |
| `risk.py` | Pure-function model risk gates: inventory, drawdown, spread floor, adverse selection, regime | stub | `core.market_state`, `core.portfolio`, `execution.pnl`, `config.settings` |
| `strategy.py` | Quoting loop orchestrator: `on_orderbook_update`, `on_fill`, `run_calibration_loop` | stub | All of core/, execution.placer, execution.pnl, execution.killswitch, utils |

---

## execution/

| File | Purpose | Status | Dependencies |
|------|---------|--------|--------------|
| `oms.py` | Order state machine (PENDING→FILLED/CANCELLED); dedup; WAL persistence | stub | `dataclasses`, `enum`, `asyncio`, `utils.logger` |
| `pretrade.py` | Pre-trade hard gates: kill switch, fat finger, size limit, gross notional, net delta | stub | `execution.killswitch`, `execution.oms`, `config.settings` |
| `killswitch.py` | First-class async kill switch; cancels all orders independently of quoting loop | stub | `asyncio`, `utils.logger`, `utils.metrics` |
| `placer.py` | Manages live quote set; decides place / amend / cancel vs desired quotes | stub | `execution.orders`, `execution.oms`, `execution.killswitch`, `utils.latency` |
| `orders.py` | Single choke point for all outbound order instructions to the exchange | stub | `exchange.base`, `execution.pretrade`, `execution.oms`, `utils.latency` |
| `tracker.py` | Reconciles exchange fill/cancel/reject events; calls `portfolio.on_fill`, `pnl.record` | stub | `execution.oms`, `core.portfolio`, `execution.pnl` |
| `pnl.py` | P&L engine decomposed into spread capture / inventory cost / adverse selection / fee drag | stub | `numpy`, `core.portfolio` |
| `reconciler.py` | Periodic comparison of internal OMS+portfolio state vs exchange REST; flags discrepancies | stub | `exchange.base`, `execution.oms`, `core.portfolio` |

---

## terminal/

| File | Purpose | Status | Dependencies |
|------|---------|--------|--------------|
| `bridge.py` | Reads `runtime/state.json`; exposes typed `LiveState` to TUI; decouples terminal from live objects | stub | `orjson`, `asyncio` |
| `app.py` | Textual TUI: quotes, order book depth, inventory, P&L, latency bar, kill switch keybinding | stub | `textual`, `terminal.bridge`, `terminal.screens.*` |
| `screens/quotes.py` | Live bid/ask/mid/spread/regime display panel | stub | `textual`, `terminal.bridge` |
| `screens/inventory.py` | Position, notional, inventory fraction bar panel | stub | `textual`, `terminal.bridge` |
| `screens/pnl.py` | Three-component P&L display panel | stub | `textual`, `terminal.bridge` |

---

## utils/

| File | Purpose | Status | Dependencies |
|------|---------|--------|--------------|
| `logger.py` | Structured logger factory (`get_logger(__name__)`) | active | `logging` |
| `latency.py` | Tick-to-trade latency tracking; per-stage timestamps; rolling p50/p95/p99 | stub | `time`, `collections.deque` |
| `metrics.py` | Structured metrics ring buffer; business/risk/system/latency categories | stub | `time`, `numpy`, `utils.logger` |

---

## runtime/ (gitignored, local only)

| File | Purpose |
|------|---------|
| `state.json` | Written by `core.strategy` on each quoting cycle; read by `terminal.bridge` |
| `oms.wal` | OMS write-ahead log for crash recovery |
| `reconciliation.log` | Output of `execution.reconciler` |
| `metrics.jsonl` | Optional metrics sink from `utils.metrics` |
| `killswitch.log` | Kill switch trigger/reset history |

---

## Root

| File | Purpose | Status |
|------|---------|--------|
| `main.py` | Entry point: wires all components, starts async tasks | stub |
| `pyproject.toml` | Package metadata and dependencies | active |
| `requirements.txt` | Pinned dependencies | active |
| `.gitmodules` | Points `core/` at private `aletheia-core` repo | active |
