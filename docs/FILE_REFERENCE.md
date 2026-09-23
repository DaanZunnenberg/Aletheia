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
├── exchanges/       ← live L2 order-book connectors + stream manager (hand-rolled, per-exchange)
├── ccxt_stream/     ← live L2/trade connectors via ccxt.pro (exchange-agnostic, alternative to exchanges/)
├── deribit/         ← Deribit REST client (historical trades, instruments)
├── paper/           ← paper trading engine (fills, positions, dashboard) -- orchestration, not model logic
├── backtest_cli/    ← terminal replay viewer for a backtest, paper-floor-style -- orchestration, not model logic
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
| `data/recorder.py` | `StreamRecorder` — append-only JSONL writer for raw live `OrderBookUpdate`/`deribit.types.Trade` events, exactly as received from `exchanges/`, before any strategy logic. Deribit has no historical L2 endpoint, so this is the only way to accumulate real order-book depth for backtesting — recording forward from now, not retroactively. Fed by `examples/record_live_streams.py`; replayed by `core/backtest/l2_replay.py` | active |

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

## ccxt_stream/

Live data via [ccxt.pro](https://github.com/ccxt/ccxt) (free WebSocket streaming, merged into the main `ccxt` package since v4) instead of the hand-rolled `exchanges/` connectors — one exchange-agnostic class covers any ccxt.pro-supported venue, at the cost of venue-specific tuning (e.g. Deribit's own `change_id` gap detection) the hand-rolled connectors have. Produces the exact same `data.orderbook.OrderBookUpdate` / `data/recorder.py` JSONL schema, so recordings are interchangeable with `examples/record_live_streams.py`'s and replay unchanged through `core/backtest/l2_replay.py`.

| File | Purpose | Status |
|------|---------|--------|
| `ccxt_stream/connector.py` | `CCXTOrderBookConnector(exchange_id, market_type, depth)` — implements `exchanges.base.OrderBookConnector`'s protocol via `ccxt.pro`'s `watch_order_book_for_symbols`, so it's a drop-in `StreamSpec.connector` for `exchanges.stream_manager.MultiExchangeStreamManager` too. Requests the smallest valid ccxt depth ≥ the caller's request (Binance futures only accepts 5/10/20/50/100/500/1000 — 25 is rejected) and truncates down to exactly what was asked for | active |
| `ccxt_stream/trades.py` | `CCXTTradeStreamConnector`, `CCXTTrade` — ccxt.pro analogue of `exchanges/deribit_trades.py`, generalised to any venue. `CCXTTrade` has the same field names as `deribit.types.Trade` so recordings are replay-compatible without format-specific branching | active |
| `ccxt_stream/select_option.py` | `select_near_1dte_option()` — nearest-to-1-day-to-expiry, nearest-the-money Deribit call, via ccxt REST. Binance discontinued its options market in 2024 (verified live: zero option markets listed) so Deribit — already this project's real options venue per CLAUDE.md — is the only live source for "1DTE options" data | active |
| `ccxt_stream/record.py` | Runnable recorder: 25-level Binance USDT-M perpetual (BTC, ETH) depth + trades, and the selected Deribit 1DTE BTC/ETH option depth + trades (whatever depth actually rests — thin option books often have fewer than 25 real levels). Writes to `runtime/ccxt_recordings/*.jsonl` via `data/recorder.py`. Run: `python ccxt_stream/record.py [seconds]` | active |

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
| `paper/engine.py` | `PaperTradingEngine` — wires book updates to quoting (perp via a multi-level GLFT ladder, `core.models.ladder`, with a soft-hedge inventory override; option via `paper.option_quoting`), trade updates to queue-tracker fills (latency-gated, per ladder level, maker fee applied via `core.risk.exposure.Position.apply_fee`), portfolio Greeks refresh + hard-hedge check (taker fee + slippage applied) + dual-timescale regime classification (`core.models.regime_monitor`) on every update, and session logging. `warmup_status()`/`warmup_statuses()` expose fast-vol/regime warm-up progress; `risk_snapshots()` reports perp position/notional/daily-loss/delta against `core.risk.limits.RiskLimits` and the hard-hedge delta band. `event_log` (bounded deque of `paper.dashboard.BlotterRow`, built by `_blotter_row()`) is a fixed-schema tape of discrete order/market events only (`quote` -- a merged real-book + our-own-quote snapshot, `fill`, `hedge`, each carrying fee/slippage where applicable) -- `greeks` and `regime` are continuously-updated *state*, logged to the session file for replay but deliberately excluded from `event_log`; surfaced instead via `self.regimes`/`self.portfolio_greeks` for the dashboard header. `snapshot()` also carries option pricing/stat-arb detail for option-quoted instruments (`realized_vol`, `fair_vol` = realized_vol * `paper.option_quoting.VRP_MULTIPLIER`, `theo_price` via `core.models.options.black76.black76_price`) and `book_bids`/`book_asks` (top-N real exchange order-book depth, independent of our own resting quotes). `update_event` (`asyncio.Event`) is set on every book update and fill so the dashboard redraws on real market events, not a fixed timer. Positions keyed by `exchange:market_type:symbol`, not bare symbol — Binance spot and perpetual share the literal symbol `"BTCUSDT"` | active |
| `paper/dashboard.py` | `MarketDashboard` — `rich`-based live terminal view focused on BTC (the primary currency): a compact header (title bar + one-line BTC status -- warm-up/regime/Greeks in words -- plus a dim one-line ETH reference strip, tight padding), two side-by-side order-book tables laid out via `Table.grid` (`Columns` reflows to a vertical stack once too wide, a grid doesn't) -- "BTC Perp OB" (our quote, the real book's own bid/ask/spread-bps, position, fills, P&L) and "BTC Option OB" (the same plus pricing/stat-arb detail: realized vol, the fair/implied vol we actually quote at, the VRP edge between them, and our Black-76 theoretical price vs. the market's own mid) -- each built only from its own instrument's `InstrumentSnapshot`, so one table never changes because the other instrument's book ticked. Every column in both tables is a fixed, `no_wrap` width (abbreviated headers) rather than autosized -- autosized headers wrapped to two lines at different points for the two tables and threw their rows out of vertical alignment; `_fmt_coin_price()` (4-decimal, not 6) keeps the Option OB's narrower price columns from truncating. A "BTC Blotter" table (`BlotterRow`: every event type -- quote/fill/hedge -- fills the same fixed columns, blank rather than differently-shaped; a "quote" row merges the real order book and our own resting quote into one line instead of two; fee/slippage columns; newest row at the bottom) follows. Plain white text throughout; green/red appear only for buy-vs-sell (bid/ask) and profit-vs-loss, never as decoration. `render_dashboard()` (plain-string, no `rich` needed) kept as a fallback/test-friendly renderer | active |

---

## backtest_cli/

Terminal replay viewer for a `BacktestResult` -- the paper-trading-floor look (`paper/dashboard.py`) applied to a backtest instead of a live session. Post-hoc replay, not a live view: `core.backtest.l2_replay`/`core.backtest.historical` compute the full result before returning, so this runs the backtest once then plays `BacktestResult.history` back one bar at a time at a configurable speed.

| File | Purpose | Status |
|------|---------|--------|
| `backtest_cli/dashboard.py` | `BacktestDashboard`, `BacktestRunInfo`, `BlotterRow` — single-instrument replay view: header (source recording/CSV, params, bar progress, running Sharpe/drawdown/turnover/breach-rate), a one-row current-state table (mid/our quote/inventory/P&L breakdown/breach), and a scrolling "Fills" blotter derived by diffing `inventory` between consecutive history rows (`BacktestResult.history` has no per-fill log, only per-bar snapshots). Same visual convention as `paper/dashboard.py`: plain text, green/red only for buy/sell and profit/loss | active |
| `backtest_cli/run.py` | Runnable: `python backtest_cli/run.py {l2\|historical} <path> [--gamma G] [--kappa K] [--speed N]`. Runs `core.backtest.l2_replay.run_l2_replay_backtest` or `core.backtest.historical.run_historical_ladder_backtest` once, then replays via `rich.Live`. `_RunningMetrics` is a from-scratch O(1)-per-bar reimplementation of `core.backtest.metrics.summarize()` (recomputing summarize on a growing slice every frame is O(n²) over a full replay -- both real recordings on hand are ~64k bars, which would stall the first frame for minutes); render rate is capped at ~20fps independent of `--speed` so skimming a long recording at high speed doesn't make rich rendering the bottleneck | active |

---

## examples/

| File | Purpose | Status |
|------|---------|--------|
| `examples/stream_multi_exchange_books.py` | Streams 6 concurrent L2 books (BTC/ETH x {Deribit perp, Binance perp, Binance spot}) via `MultiExchangeStreamManager`, logs final mid/update-count per stream. Proves multi-exchange, multi-coin, spot+perp concurrent streaming in one process | active |
| `examples/live_quote_loop.py` | First end-to-end live quoting loop: real Deribit L2 book → EWMA vol → `core.strategies.market_maker.generate_quotes` (Avellaneda-Stoikov) → printed bid/ask. Wires in `core.risk.tail_risk.TailRiskMonitor`. Dry-run only — no order placement, `mark_price`/`index_price` approximated by live mid (no ticker/funding stream wired in yet) | active |
| `examples/paper_trading_bot.py` | Live paper trading bot (`paper/`): Deribit perp + nearest-ATM option per coin (quoted, both books AND trades streamed), Binance spot + perpetual (reference-only), refreshing terminal dashboard with portfolio Greeks, session logged to `runtime/paper_sessions/*.jsonl`, dry-run. Validated live against all four venues/market types including a real near-0DTE option (~2.3h to expiry) | active |
| `examples/record_live_streams.py` | Pure recorder, no quoting: streams real Deribit perp L2 + trades and Binance spot/perp L2 via `MultiExchangeStreamManager`, persists every event via `data/recorder.py` to `runtime/recordings/*.jsonl`. Run unattended to accumulate a real-L2 dataset for `core/backtest/l2_replay.py` | active |

---

## tests/

| File | Purpose | Status |
|------|---------|--------|
| `tests/test_orderbook.py` | pytest coverage for `data/orderbook.py`: best bid/ask, mid price, microprice (symmetric/imbalanced/empty-book), key identity, immutability | active |
| `tests/test_ccxt_stream.py` | pytest coverage for `ccxt_stream/`: depth-rounding to a valid ccxt limit then truncation, 1DTE-option selection (nearest to target hours, not soonest; nearest strike at the chosen expiry; raises when no options exist) — offline, against fake market data, no network | active |
| `tests/test_backtest_cli.py` | pytest coverage for `backtest_cli/`: `_RunningMetrics`' O(1)-per-bar stats verified bar-by-bar against `core.backtest.metrics.summarize()`'s batch calculation on the same synthetic history (caught a real turnover double-count bug on the first bar before it shipped), dashboard renders without error | active |
| `tests/test_stream_manager.py` | pytest coverage for `exchanges/stream_manager.py` against fake (non-network) connectors: multi-connector merging, clean shutdown, one connector dying doesn't crash the manager | active |
| `tests/test_fill_simulator.py` | pytest coverage for `paper/fill_simulator.py`: crossing conditions both sides, skip flags, zero size | active |
| `tests/test_queue_tracker.py` | pytest coverage for `paper/queue_tracker.py`: walk-through fills, queue-ahead consumption, multi-trade progressive draining, per-instrument/per-side independence | active |
| `tests/test_execution_latency.py` | pytest coverage for `paper/execution_latency.py`: latency floor/jitter, live-gating boundary, taker slippage direction/scaling | active |
| `tests/test_hedger.py` | pytest coverage for `paper/hedger.py`: soft inventory summation, hard-hedge band triggering (both directions, boundary case), delta-exclusion helper | active |
| `tests/test_bar_builder.py` | pytest coverage for `paper/bar_builder.py`: same-bar updates, bar closing, forward-fill through empty bars, floor-not-round boundaries | active |
| `tests/test_session_log.py` | pytest coverage for `paper/session_log.py`/`session_replay.py`: round-trip logging, immediate flush, dataframe flattening, fills/P&L-curve extraction | active |
| `tests/test_position_book.py` | pytest coverage for `paper/position_book.py`: fills, round-trip realized P&L, per-instrument isolation | active |
| `tests/test_option_quoting.py` | pytest coverage for `paper/option_quoting.py`: bid<ask, coin-denominated output, expiry/zero-price edge cases, vol/spread sensitivity, pin-risk size reduction | active |
| `tests/test_dashboard.py` | pytest coverage for `paper/dashboard.py`: plain-text fallback formatting, `spread_bps()`, `utilization()`/`utilization_tier()`, and `MarketDashboard`'s BTC-focused layout (side-by-side Perp OB / Option OB tables + one Blotter table), confirming each order-book table only reflects its own instrument, the Option OB's VRP-edge/theo-price coloring, the Blotter's merged book+quote rows and fee/slippage/bid=green/ask=red styling and row cap, and the header's warm-up/regime status, full-word Greeks, and dim ETH reference line | active |
| `tests/test_engine.py` | pytest coverage for `paper/engine.py`: vol-warmup gating, reference streams never quoted, trade-tape fills (incl. latency gating, unquoted-instrument no-ops, fee/slippage), option quoting requires both underlying and vol, option pricing/VRP-edge snapshot fields, spot/perp symbol-collision regression, portfolio Greeks, hard-hedge triggering (incl. fee/slippage), session logging, event_log excludes greeks/regime state, flat-bar-run sigma=0.0 regression (caught live) | active |

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
