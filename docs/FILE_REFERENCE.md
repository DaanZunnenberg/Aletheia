# Aletheia — File Reference

Living reference for every file in the public repo. Update whenever a file
is added, removed, or its functionality or status changes.

Status: `active` | `stub` | `placeholder` (intentionally empty, documents future intent)

Rebuilt 2026-09-18 as a clean slate (see README.md). `core/` and `research/`
are private submodules with their own history and their own reference
material (`core/MODEL.md`); this file only documents the public layer.

---

## Repository Layout

```
aletheia/                       ← public repo
├── data/           ← OrderBookUpdate (exchange-agnostic L2 book type)
├── exchanges/       ← live L2 order-book connectors + stream manager
├── deribit/         ← Deribit REST client (historical trades, instruments)
├── paper/           ← paper trading engine (fills, positions, dashboard) -- orchestration, not model logic
├── examples/        ← runnable demos
├── tests/           ← tests for the public layer
├── utils/           ← dependency-free helpers (logger)
├── core/            ← PRIVATE submodule (aletheia-core)
├── research/        ← PRIVATE submodule (aletheia-research)
└── docs/            ← this file
```

---

## data/

| File | Purpose | Status |
|------|---------|--------|
| `data/orderbook.py` | `OrderBookUpdate` — exchange-agnostic L2 snapshot every connector normalises into. `best_bid`/`best_ask`/`mid_price`/`microprice` (size-weighted mid, Stoikov 2018)/`key` convenience properties. `market_type` includes `"option"` | active |

---

## exchanges/

| File | Purpose | Status |
|------|---------|--------|
| `exchanges/base.py` | `OrderBookConnector` protocol — `stream_order_books(symbols, depth) -> AsyncIterator[OrderBookUpdate]` | active |
| `exchanges/deribit_connector.py` | `DeribitOrderBookConnector(market_type="perpetual")` — multi-instrument L2 streaming over one WS connection (`public/subscribe` with multiple `book.*` channels). `market_type` is constructor-configurable (also used for `"option"`; the `book.*` channel is generic across instrument kinds). Maintains local book state per instrument with `change_id` gap detection; a gap clears that instrument's book and awaits a fresh snapshot rather than silently drifting out of sync | active |
| `exchanges/binance_connector.py` | `BinanceOrderBookConnector(market_type)` — multi-symbol L2 streaming over one combined-stream WS connection, for `spot` or `perpetual` (separate hosts). Uses the partial book depth stream (`<symbol>@depth<5\|10\|20>@100ms`) — a ready top-N snapshot per update, not a diff stream requiring local state reconstruction. Spot and futures use different JSON key names for the same data (`bids`/`asks` vs. `b`/`a`); handled transparently | active |
| `exchanges/stream_manager.py` | `MultiExchangeStreamManager`, `StreamSpec` — runs an arbitrary number of connectors concurrently (one asyncio task each), merges into a single async stream via a shared queue. A connector task dying is caught and logged, not propagated, so one dead stream doesn't take down the others | active |
| `exchanges/deribit_trades.py` | `DeribitTradeStreamConnector` — multi-instrument live trade stream (same multi-channel-over-one-WS pattern as the order-book connector), yielding `deribit.types.Trade`. Feeds `paper/queue_tracker.py`'s trade-tape-driven fills — replaces the earlier L2-crossing fill approximation | active |

---

## deribit/

| File | Purpose | Status |
|------|---------|--------|
| `deribit/types.py` | TypedDicts for Deribit wire types: `Trade` (incl. `mark_price`), `Instrument`, `OrderBookSnapshot`, `Ticker`, `IndexPrice`, `FundingRate` | active |
| `deribit/rest.py` | `DeribitREST`: async REST client. `get_instruments`, `get_ticker`, `get_order_book`, `get_index_price`, `get_last_trades`, `get_trades_by_time_range` (paginated historical trades — Deribit's only free historical endpoint; no L2/book history exists) | active |

---

## paper/

Paper trading engine: consumes live `OrderBookUpdate`s, quotes, simulates
fills, tracks positions/P&L, renders a terminal dashboard. **No real orders
are ever sent** -- this is orchestration/wiring, not new model logic, so it
lives in the public repo, not `core/`.

| File | Purpose | Status |
|------|---------|--------|
| `paper/fill_simulator.py` | `check_fill()` — crossing-based paper fill (L2 top-of-book only). Superseded by `paper/queue_tracker.py` for instruments with a live trade stream (all currently-quoted instruments); kept as the documented simpler fallback and still used for the hard-hedge execution fill container (`PaperFill`) | active |
| `paper/queue_tracker.py` | `QueueTracker`, `process_trade_against_order()` — FIFO queue-position approximation: a resting quote's estimated position is the size resting at that exact price when placed, decremented by real trade volume at that price; a trade printing *through* the level (not just at it) is a guaranteed fill. Not full L3 precision (no visibility into cancels ahead of us), but a real step up from L2-crossing | active |
| `paper/execution_latency.py` | `LatencyModel` — fixed+exponential-jitter delay between quote decision and the quote actually being live in the book; `is_quote_live()` gates fills on it. `taker_slippage_price()` — linear temporary-impact model for hard-hedge taker execution (uncalibrated placeholder, no real fill data yet) | active |
| `paper/hedger.py` | `soft_hedge_inventory()` — perp's phantom inventory for AS's own skew mechanism (real perp position + option book delta), feeding `core.strategies.market_maker.generate_quotes`'s `inventory_override`. `should_hard_hedge()` — threshold-triggered immediate (paper) taker hedge, deliberately gated on trade-tape fills existing (a hedge trigger built on L2-crossing fantasy fills is the "false confidence" failure mode a continuous soft nudge doesn't have) | active |
| `paper/position_book.py` | `PositionBook` — per-instrument `core.risk.exposure.Position` tracking, fill log, aggregate net P&L. Generic contract math, applies identically to perps and options | active |
| `paper/option_quoting.py` | `generate_option_quote()` — Black-76 off `realized_vol * VRP_MULTIPLIER`, fixed +/- vol-space half-spread, size scaled by `core.risk.pin_risk.pin_risk_size_multiplier()`. No SVI, no Greek-based skew (that's the perp side's job via the soft-hedge inventory override) — the options analogue of plain AS, not the GLFT+regime stack. Converts Black-76's USD price to the coin-denominated units Deribit actually quotes options in (approximate inverse-option conversion, not exact Greeks) | active |
| `paper/instruments.py` | `find_near_the_money_option()` — REST instrument discovery: nearest-expiry (typically 0DTE/1DTE), closest-to-the-money strike for a currency | active |
| `paper/bar_builder.py` | `LiveBarAggregator` — buckets irregularly-arriving ticks into fixed-width, forward-filled bars before feeding `core.models.volatility.ewma_volatility()`, which assumes evenly-sampled input. Fixes a real bug: feeding raw ticks in silently distorted the live vol estimate | active |
| `paper/session_log.py` | `SessionLogger`, `SessionEvent` — append-only JSONL log of every quote/fill/Greeks-snapshot/hedge, flushed per write. Without this a paper session's entire history vanished on process exit | active |
| `paper/session_replay.py` | `load_session()`, `session_to_dataframe()`, `fills_only()`, `pnl_curve()` — post-hoc analysis of a session log | active |
| `paper/engine.py` | `PaperTradingEngine` — wires book updates to quoting (perp via a multi-level GLFT ladder, `core.models.ladder`, with a soft-hedge inventory override; option via `paper.option_quoting`), trade updates to queue-tracker fills (latency-gated, per ladder level), portfolio Greeks refresh + hard-hedge check + dual-timescale regime classification (`core.models.regime_monitor`) on every update, and session logging. `warmup_status()`/`warmup_statuses()` expose fast-vol/regime warm-up progress; `recent_fills` is a bounded ring buffer and `risk_snapshots()` reports position/notional/daily-loss/delta against `core.risk.limits.RiskLimits` and the hard-hedge delta band, both for the dashboard. `update_event` (`asyncio.Event`) is set on every book update and fill so the dashboard redraws on real market events, not a fixed timer. Positions keyed by `exchange:market_type:symbol`, not bare symbol — Binance spot and perpetual share the literal symbol `"BTCUSDT"` | active |
| `paper/dashboard.py` | `MarketDashboard` — `rich`-based live terminal view styled as a trading-floor board: color-coded bid(green)/ask(red) market table (with fill count) and per-cell change-flash highlighting, ladder sub-rows for multi-level perp quotes, a risk panel (position/notional/daily-loss/delta utilization vs. limits, red on breach), a market-regime panel (HFT vol regime + macro trend), a warm-up-status panel, portfolio Greeks, and recent fills. `render_dashboard()` (plain-string, no `rich` needed) kept as a fallback/test-friendly renderer | active |

---

## examples/

| File | Purpose | Status |
|------|---------|--------|
| `examples/stream_multi_exchange_books.py` | Streams 6 concurrent L2 books (BTC/ETH x {Deribit perp, Binance perp, Binance spot}) via `MultiExchangeStreamManager`, logs final mid/update-count per stream. Proves multi-exchange, multi-coin, spot+perp concurrent streaming in one process | active |
| `examples/live_quote_loop.py` | First end-to-end live quoting loop: real Deribit L2 book → EWMA vol → `core.strategies.market_maker.generate_quotes` (Avellaneda-Stoikov) → printed bid/ask. Wires in `core.risk.tail_risk.TailRiskMonitor`. Dry-run only — no order placement, `mark_price`/`index_price` approximated by live mid (no ticker/funding stream wired in yet) | active |
| `examples/paper_trading_bot.py` | Live paper trading bot (`paper/`): Deribit perp + nearest-ATM option per coin (quoted, both books AND trades streamed), Binance spot + perpetual (reference-only), refreshing terminal dashboard with portfolio Greeks, session logged to `runtime/paper_sessions/*.jsonl`, dry-run. Validated live against all four venues/market types including a real near-0DTE option (~2.3h to expiry) | active |

---

## tests/

| File | Purpose | Status |
|------|---------|--------|
| `tests/test_orderbook.py` | pytest coverage for `data/orderbook.py`: best bid/ask, mid price, microprice (symmetric/imbalanced/empty-book), key identity, immutability | active |
| `tests/test_stream_manager.py` | pytest coverage for `exchanges/stream_manager.py` against fake (non-network) connectors: multi-connector merging, clean shutdown, one connector dying doesn't crash the manager | active |
| `tests/test_fill_simulator.py` | pytest coverage for `paper/fill_simulator.py`: crossing conditions both sides, skip flags, zero size | active |
| `tests/test_queue_tracker.py` | pytest coverage for `paper/queue_tracker.py`: walk-through fills, queue-ahead consumption, multi-trade progressive draining, per-instrument/per-side independence | active |
| `tests/test_execution_latency.py` | pytest coverage for `paper/execution_latency.py`: latency floor/jitter, live-gating boundary, taker slippage direction/scaling | active |
| `tests/test_hedger.py` | pytest coverage for `paper/hedger.py`: soft inventory summation, hard-hedge band triggering (both directions, boundary case), delta-exclusion helper | active |
| `tests/test_bar_builder.py` | pytest coverage for `paper/bar_builder.py`: same-bar updates, bar closing, forward-fill through empty bars, floor-not-round boundaries | active |
| `tests/test_session_log.py` | pytest coverage for `paper/session_log.py`/`session_replay.py`: round-trip logging, immediate flush, dataframe flattening, fills/P&L-curve extraction | active |
| `tests/test_position_book.py` | pytest coverage for `paper/position_book.py`: fills, round-trip realized P&L, per-instrument isolation | active |
| `tests/test_option_quoting.py` | pytest coverage for `paper/option_quoting.py`: bid<ask, coin-denominated output, expiry/zero-price edge cases, vol/spread sensitivity, pin-risk size reduction | active |
| `tests/test_dashboard.py` | pytest coverage for `paper/dashboard.py`: plain-text fallback formatting, `spread_bps()`, `utilization()`/`utilization_tier()`, and `MarketDashboard`'s ladder-level rows, change-highlight flashing, regime/warm-up/fills/risk panels (incl. red-on-breach styling) | active |
| `tests/test_engine.py` | pytest coverage for `paper/engine.py`: vol-warmup gating, reference streams never quoted, trade-tape fills (incl. latency gating, unquoted-instrument no-ops), option quoting requires both underlying and vol, spot/perp symbol-collision regression, portfolio Greeks, hard-hedge triggering, session logging, flat-bar-run sigma=0.0 regression (caught live) | active |

Connector WS parsing logic (`deribit_connector.py`, `binance_connector.py`)
is validated against live exchanges during development, not covered by
hermetic unit tests — mocking aiohttp's WS protocol in detail wasn't judged
worth the complexity for an initial version. Revisit if a real parsing bug
ships.

---

## utils/

| File | Purpose | Status |
|------|---------|--------|
| `utils/logger.py` | `get_logger(name)` — stdlib `logging` wrapper, one formatted stream handler, level from `LOG_LEVEL` env var | active |

---

## Not yet rebuilt

- `execution/` — order routing/placement. Everything in this repo is dry-run.
- `config/` — settings/secrets loader. Not needed yet (all current connectors use public, unauthenticated endpoints); restore when execution needs API keys.
- `checks/` — connectivity diagnostics.
