# Aletheia — File Reference

Living reference for every file in the project. Update whenever a file is added,
removed, or its functionality or status changes.

Status: `active` | `stub` | `placeholder` (intentionally empty, documents future intent)

---

## Repository Boundary

| Layer | Visibility | Contents |
|-------|-----------|----------|
| `core/` | **Private** (submodule) | Market state domain model, quoting model, microstructure signals, position/risk management, market-making strategy |
| `research/` | **Private** (submodule) | Research notebooks, ideas, and validation scripts |
| Everything else | **Public** | Deribit connector, data normalisation, config, utilities, connectivity checks, examples |

The public repo contains zero model or strategy logic. `core/` contains zero connector or I/O code.

---

## Repository Layout

```
aletheia/                       ← public repo
├── core/                       ← private submodule (aletheia-core)
│   ├── market_state.py         ← domain model: MarketState (perpetual snapshot)
│   ├── models/                 ← Avellaneda-Stoikov quoting model, realised vol estimator
│   ├── signals/                ← microstructure signals (book/trade imbalance)
│   ├── strategies/              ← quote generation, risk-checked
│   ├── risk/                   ← position/P&L tracking, hard limits
│   └── MODEL.md                ← full mathematical specification
├── deribit/                    ← native Deribit REST + WebSocket connectors
├── data/
│   └── normalization.py        ← raw Deribit types → core domain types
├── execution/                  ← order routing (placeholder)
├── research/                   ← private submodule (aletheia-research)
├── config/                     ← settings, secrets
├── utils/                      ← shared utilities (logger)
├── checks/                     ← connectivity diagnostics
├── examples/                   ← runnable Deribit WebSocket streaming examples
├── docs/                       ← this file
└── main.py                     ← test entry point
```

---

## Startup Sequence (main.py)

1. `config/settings.py` — load environment and credentials
2. `deribit/rest.py` — fetch ticker + order book for the configured perpetual(s)
3. `data/normalization.py` — normalise into `core.MarketState`
4. `core/models/quoting.py` — compute reservation price and optimal spread (fixed sigma placeholder until a rolling vol estimator is wired in)
5. `core/strategies/market_maker.py` — risk-check and size the quote, emit `QuoteDecision`

Order placement is not implemented; this is a test harness for the model, not a live loop.

---

## core/ (private submodule — aletheia-core)

All model, strategy, and risk logic. See `core/MODEL.md` for the full mathematical specification.

### Domain model

| File | Purpose | Status |
|------|---------|--------|
| `core/market_state.py` | `MarketState` dataclass — top-of-book (price/size), mark price, index price, current funding, timestamp. Convenience properties: `mid_price`, `microprice`, `spread` | active |

### Quoting model (`core/models/`)

| File | Purpose | Status |
|------|---------|--------|
| `core/models/quoting.py` | `QuotingParams`, `reservation_price()`, `optimal_spread()`, `quote_prices()` — Avellaneda-Stoikov (2008); `calibrate_kappa()` fits fill-intensity decay from the trade tape | active |
| `core/models/volatility.py` | `ewma_volatility()` — realised vol from an EWMA of squared log mid-price returns, feeds `sigma` into the quoting model | active |

### Microstructure signals (`core/signals/`)

| File | Purpose | Status |
|------|---------|--------|
| `core/signals/microstructure.py` | `order_book_imbalance()`, `trade_imbalance()` — not yet wired into quote generation; inputs for a future adverse-selection extension | active |

### Strategy (`core/strategies/`)

| File | Purpose | Status |
|------|---------|--------|
| `core/strategies/market_maker.py` | `QuoteDecision`, `generate_quotes()` — combines the quoting model, current `Position`, and `RiskLimits` into a sized, risk-checked bid/ask instruction | active |

### Risk management (`core/risk/`)

| File | Purpose | Status |
|------|---------|--------|
| `core/risk/exposure.py` | `Position` — net inventory, average entry price, realized/unrealized P&L, funding accrual; `check_limits()` against `RiskLimits` | active |
| `core/risk/limits.py` | `RiskLimits` dataclass: hard caps on net position, order size, gross notional, daily loss. `RiskLimits.conservative()` preset | active |

---

## deribit/ (public)

Native async Deribit connectors, perpetual/future scope only (options-chain
streaming was removed with the distribution-arbitrage strategy). Do not modify
without updating both REST and WS layers.

| File | Purpose | Status |
|------|---------|--------|
| `deribit/types.py` | TypedDicts for Deribit wire types: `Ticker`, `Trade`, `Instrument`, `OrderBookSnapshot`, `IndexPrice`, `FundingRate` | active |
| `deribit/rest.py` | `DeribitREST`: async REST client. `get_instruments`, `get_ticker`, `get_order_book`, `get_index_price`, `get_last_trades` | active |
| `deribit/connector.py` | `DeribitConnector`: WebSocket streams. `watch_order_book`, `watch_trades`, `watch_ticker`, `watch_index`, `watch_funding` | active |

*Removed: `deribit` options-chain streams (`watch_volatility_index`, `watch_mark_prices`) and
associated types (`VolatilityIndex`, `OptionMarkPrice`) — DVOL and per-option mark IV have no
role in perpetual market making.*

---

## data/ (public)

Data normalization pipeline. Converts raw exchange wire types into core domain objects. No model logic.

| File | Purpose | Status |
|------|---------|--------|
| `data/normalization.py` | `build_market_state()` — combines a `Ticker` and `OrderBookSnapshot` into a `core.market_state.MarketState` | active |

---

## execution/ (public, placeholder)

Order routing. Not yet implemented. Will remain public (infrastructure).

---

## research/ (private submodule — aletheia-research)

Research notebooks, ideas, and validation scripts. Not part of the public repository history; contents are not documented here. See the submodule's own README for its internal reference.

---

## config/ (public)

| File | Purpose | Status |
|------|---------|--------|
| `config/settings.py` | `Settings.load()`: reads `.env`, exposes `testnet`, `api_key`, `api_secret`, `currencies`, `dry_run` | active |
| `config/watcher.py` | Hot-reload stub (unused in research mode) | stub |
| `config/.env` | Secret keys; never committed | active |

---

## utils/ (public)

| File | Purpose | Status |
|------|---------|--------|
| `utils/logger.py` | `get_logger(name)` — stdout logger with standard formatter | active |

---

## checks/ (public)

Connectivity diagnostics. Venue-agnostic; unchanged by the market-making restructure. Run manually to verify credentials and feeds.

| File | Purpose |
|------|---------|
| `checks/auth.py` | Verify Deribit API key |
| `checks/rest.py` | Smoke-test REST endpoints |
| `checks/ws.py` | Smoke-test WebSocket streams |

---

## examples/ (public)

Runnable WebSocket streaming examples against live Deribit data. No production
code; demonstrates `deribit/connector.py` usage against the exact data the
market-making model needs (top-of-book, funding), not L2 depth or an options
chain.

| File | Purpose | Status |
|------|---------|--------|
| `examples/stream_index.py` | Streams spot index price for BTC or ETH | active |
| `examples/stream_perpetual.py` | Streams top-of-book and funding rate for a perpetual (BTC-PERPETUAL / ETH-PERPETUAL) — the raw inputs to `core.market_state.MarketState` | active |

*Removed: `examples/stream_options.py` — full options-chain mark-price/IV streaming,
no longer relevant now that the strategy quotes perpetuals, not the options chain.*

---

## Removed in the market-making restructure

`core/options/` (IV surface, Breeden-Litzenberger risk-neutral density),
`core/models/physical_distribution.py` and `volatility_models.py`,
`core/signals/distribution_arbitrage.py`, `core/strategies/option_relative_value.py`,
`core/risk/greeks.py`, `core/_math.py` (CDF/moment utilities used only by the RND
extraction), and `exchange/` (generic multi-venue connector abstraction — single
venue, single instrument type, not needed) were all deleted along with the
distribution-arbitrage strategy they supported. See `core/MODEL.md` for what
replaced them.

---

## Root

| File | Purpose |
|------|---------|
| `main.py` | Test entry point: fetch perpetual ticker + book → build `MarketState` → print one `QuoteDecision` |
| `pyproject.toml` | Package metadata and dependencies |
| `CLAUDE.md` | Project instructions for Claude Code |
