# Aletheia — File Reference

Living reference for every file in the project. Update whenever a file is added,
removed, or its functionality or status changes.

Status: `active` | `stub` | `placeholder` (intentionally empty, documents future intent)

---

## Repository Boundary

| Layer | Visibility | Contents |
|-------|-----------|----------|
| `core/` | **Private** (submodule) | Market state domain model, options analytics, distribution models, signal generation, strategy, risk management |
| Everything else | **Public** | Exchange connectors, data fetching, normalization, config, utilities, research notebooks, future backtesting framework |

The public repo contains zero model or strategy logic. `core/` contains zero connector or I/O code.

---

## Repository Layout

```
aletheia/                       ← public repo
├── core/                       ← private submodule (aletheia-core)
│   ├── market_state.py         ← domain model: MarketState, OptionQuote, FutureQuote
│   ├── options/                ← IV surface, calibration, implied distribution extraction
│   ├── models/                 ← statistical distribution models, vol forecasting
│   ├── signals/                ← signal generation from pricing and distribution analysis
│   ├── strategies/             ← trade decision generation
│   ├── risk/                   ← Greek aggregation, position limits
│   └── MODEL.md                ← full mathematical specification
├── deribit/                    ← native Deribit REST + WebSocket connectors
├── exchange/                   ← generic connector abstractions (CCXT etc.)
├── data/
│   └── normalization.py        ← raw Deribit types → core domain types
├── execution/                  ← order routing (placeholder)
├── research/
│   └── notebooks/              ← Jupyter notebooks for exploratory work
├── config/                     ← settings, secrets
├── utils/                      ← shared utilities (logger)
├── checks/                     ← connectivity diagnostics
├── examples/                   ← runnable Deribit WebSocket streaming examples
├── docs/                       ← this file
└── main.py                     ← research entry point
```

---

## Startup Sequence (main.py)

1. `config/settings.py` — load environment and credentials
2. `deribit/rest.py` — open async REST session
3. `data/normalization.py` — fetch raw Deribit data, normalise into `core.MarketState`
4. `core/options/surface.py` — build IV surface from `MarketState`
5. `core/options/risk_neutral_distribution.py` — extract implied distribution per expiry
6. `core/signals/distribution_arbitrage.py` — generate signals, emit `DistributionSignal`
7. `core/strategies/option_relative_value.py` — translate signal into `TradeDecision` (risk-checked)

---

## core/ (private submodule — aletheia-core)

All model, strategy, and risk logic. See `core/MODEL.md` for the full mathematical specification.

### Domain model

| File | Purpose | Status |
|------|---------|--------|
| `core/market_state.py` | `MarketState`, `OptionQuote`, `FutureQuote` dataclasses. The canonical in-memory representation of a market snapshot. Convenience methods: `calls()`, `puts()`, `expiries()`, `perpetual()`, `forward()` | active |

### Options analytics (`core/options/`)

| File | Purpose | Status |
|------|---------|--------|
| `core/options/surface.py` | `IVSlice`, `IVSurface`, `build_surface()`. Cubic spline on log-moneyness `m = log(K/F)`, one slice per expiry, calls only | active |
| `core/options/calibration.py` | Placeholder for SVI and SABR parametric surface calibration | placeholder |
| `core/options/risk_neutral_distribution.py` | `RiskNeutralDistribution`, `extract_risk_neutral_distribution()`. Extracts the implied distribution from option prices. Outputs normalised density, CDF, moments, tail probabilities, validity flag | active |

### Statistical distribution models (`core/models/`)

| File | Purpose | Status |
|------|---------|--------|
| `core/models/physical_distribution.py` | `PhysicalDistributionModel` ABC, `PhysicalDistribution` dataclass, `LogNormalHistoricalModel` baseline | active |
| `core/models/volatility_models.py` | Placeholder for GARCH(1,1), Heston, EWMA vol forecasting | placeholder |

### Signal generation (`core/signals/`)

| File | Purpose | Status |
|------|---------|--------|
| `core/signals/distribution_arbitrage.py` | `DistributionSignal`, `compare_distributions()`. Generates arbitrage signals from pricing and distribution analysis. Emits direction and suggested trade structure | active |

### Strategy (`core/strategies/`)

| File | Purpose | Status |
|------|---------|--------|
| `core/strategies/option_relative_value.py` | `TradeDecision`, `generate_decision()`. Translates `DistributionSignal` into a sized, risk-checked trade instruction | active |

### Risk management (`core/risk/`)

| File | Purpose | Status |
|------|---------|--------|
| `core/risk/greeks.py` | `GreekExposure`, `Position`, `compute_exposure()`. Aggregates net and gross Greeks (delta, gamma, vega, theta) across open option positions | active |
| `core/risk/limits.py` | `RiskLimits` dataclass: hard caps on vega, delta, gamma, notional. `RiskLimits.conservative()` preset | active |

---

## deribit/ (public)

Native async Deribit connectors. Do not modify without updating both REST and WS layers.

| File | Purpose | Status |
|------|---------|--------|
| `deribit/types.py` | TypedDicts for all Deribit wire types: `Ticker`, `Trade`, `Instrument`, `OrderBookSnapshot`, `IndexPrice`, `VolatilityIndex`, `OptionMarkPrice`, `FundingRate` | active |
| `deribit/rest.py` | `DeribitREST`: async REST client. `get_instruments`, `get_ticker`, `get_order_book`, `get_index_price`, `get_last_trades`, `get_historical_volatility` | active |
| `deribit/connector.py` | `DeribitConnector`: WebSocket streams. `watch_order_book`, `watch_trades`, `watch_ticker`, `watch_index`, `watch_volatility_index`, `watch_mark_prices`, `watch_funding` | active |

---

## exchange/ (public)

Generic connector abstractions for non-Deribit venues. Modular; not used by the primary research pipeline.

| File | Purpose | Status |
|------|---------|--------|
| `exchange/base.py` | Abstract `BaseRestConnector` and `BaseWebSocketConnector` | active |
| `exchange/registry.py` | Maps venue name strings to connector classes | active |
| `exchange/binance/rest.py` | Binance REST stub | stub |
| `exchange/binance/ws.py` | Binance WebSocket stub | stub |

---

## data/ (public)

Data normalization pipeline. Converts raw exchange wire types into core domain objects. No model logic.

| File | Purpose | Status |
|------|---------|--------|
| `data/normalization.py` | `ticker_to_option_quote()`, `ticker_to_future_quote()`, `build_market_state()`. Transforms raw `deribit.types` objects into `core.market_state` types | active |

*Future additions: `data/feed.py` (live WebSocket feed manager), `data/storage.py` (historical snapshot persistence).*

---

## execution/ (public, placeholder)

Order routing. Not yet implemented. Will remain public (infrastructure).

---

## research/ (public)

Jupyter notebooks for exploratory research. No production code lives here.

| Path | Purpose |
|------|---------|
| `research/notebooks/` | Surface inspection, RND extraction, signal backtesting |

*Future: a backtesting framework (e.g. vectorbt, backtesting.py, or custom) will be integrated here and remain public.*

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

Connectivity diagnostics. Run manually to verify credentials and feeds.

| File | Purpose |
|------|---------|
| `checks/auth.py` | Verify Deribit API key |
| `checks/rest.py` | Smoke-test REST endpoints |
| `checks/ws.py` | Smoke-test WebSocket streams |

---

## examples/ (public)

Runnable WebSocket streaming examples against live Deribit data. No production code;
demonstrates `deribit/connector.py` usage. Not order-book/microstructure tooling —
this strategy trades on minutes-to-days horizons off mark IV, mark price, index, and
DVOL, not L2 depth.

| File | Purpose | Status |
|------|---------|--------|
| `examples/stream_index.py` | Streams spot index price and DVOL (30d forward IV) for BTC or ETH | active |
| `examples/stream_options.py` | Streams the full options chain mark prices/IV via `markprice.options.{index}`, renders a calls/puts table around ATM | active |

*Removed: `examples/print_orderbook.py` — depended on `data/orderbook.py`, which was
deleted in the market-making → distribution-arbitrage restructure (`11faa8e`). L2 order
book depth is not part of this strategy's data requirements; execution-cost modelling
(when `execution/` is built out) only needs top-of-book.*

---

## Root

| File | Purpose |
|------|---------|
| `main.py` | Research entry point: fetch option chain → build surface → extract implied distribution → print summary |
| `pyproject.toml` | Package metadata and dependencies (`scipy` added for surface interpolation) |
| `CLAUDE.md` | Project instructions for Claude Code |
