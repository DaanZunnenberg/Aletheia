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
| `data/orderbook.py` | `OrderBookUpdate` — exchange-agnostic L2 snapshot every connector normalises into. `best_bid`/`best_ask`/`mid_price`/`key` convenience properties | active |

---

## exchanges/

| File | Purpose | Status |
|------|---------|--------|
| `exchanges/base.py` | `OrderBookConnector` protocol — `stream_order_books(symbols, depth) -> AsyncIterator[OrderBookUpdate]` | active |
| `exchanges/deribit_connector.py` | `DeribitOrderBookConnector` — multi-instrument L2 streaming over one WS connection (`public/subscribe` with multiple `book.*` channels). Maintains local book state per instrument with `change_id` gap detection; a gap clears that instrument's book and awaits a fresh snapshot rather than silently drifting out of sync | active |
| `exchanges/binance_connector.py` | `BinanceOrderBookConnector(market_type)` — multi-symbol L2 streaming over one combined-stream WS connection, for `spot` or `perpetual` (separate hosts). Uses the partial book depth stream (`<symbol>@depth<5\|10\|20>@100ms`) — a ready top-N snapshot per update, not a diff stream requiring local state reconstruction. Spot and futures use different JSON key names for the same data (`bids`/`asks` vs. `b`/`a`); handled transparently | active |
| `exchanges/stream_manager.py` | `MultiExchangeStreamManager`, `StreamSpec` — runs an arbitrary number of connectors concurrently (one asyncio task each), merges into a single async stream via a shared queue. A connector task dying is caught and logged, not propagated, so one dead stream doesn't take down the others | active |

---

## deribit/

| File | Purpose | Status |
|------|---------|--------|
| `deribit/types.py` | TypedDicts for Deribit wire types: `Trade` (incl. `mark_price`), `Instrument`, `OrderBookSnapshot`, `Ticker`, `IndexPrice`, `FundingRate` | active |
| `deribit/rest.py` | `DeribitREST`: async REST client. `get_instruments`, `get_ticker`, `get_order_book`, `get_index_price`, `get_last_trades`, `get_trades_by_time_range` (paginated historical trades — Deribit's only free historical endpoint; no L2/book history exists) | active |

---

## examples/

| File | Purpose | Status |
|------|---------|--------|
| `examples/stream_multi_exchange_books.py` | Streams 6 concurrent L2 books (BTC/ETH x {Deribit perp, Binance perp, Binance spot}) via `MultiExchangeStreamManager`, logs final mid/update-count per stream. Proves multi-exchange, multi-coin, spot+perp concurrent streaming in one process | active |
| `examples/live_quote_loop.py` | First end-to-end live quoting loop: real Deribit L2 book → EWMA vol → `core.strategies.market_maker.generate_quotes` (Avellaneda-Stoikov) → printed bid/ask. Wires in `core.risk.tail_risk.TailRiskMonitor`. Dry-run only — no order placement, `mark_price`/`index_price` approximated by live mid (no ticker/funding stream wired in yet) | active |

---

## tests/

| File | Purpose | Status |
|------|---------|--------|
| `tests/test_orderbook.py` | pytest coverage for `data/orderbook.py`: best bid/ask, mid price, key identity, empty-book NaN handling, immutability | active |
| `tests/test_stream_manager.py` | pytest coverage for `exchanges/stream_manager.py` against fake (non-network) connectors: multi-connector merging, clean shutdown, one connector dying doesn't crash the manager | active |

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
