# Aletheia — File Reference

Living reference for every file in the project. Update whenever a file is added,
removed, or its functionality or status changes.

Status: `active` | `stub` (skeleton only) | `placeholder` (intentionally empty, documents future intent)

---

## Repository Layout

```
aletheia/
├── core/                   ← private submodule (aletheia-core)
│   ├── options/            ← IV surface, calibration, Breeden-Litzenberger
│   ├── models/             ← physical distribution models
│   └── signals/            ← Q vs P comparison engine
├── deribit/                ← native Deribit REST + WebSocket connectors
├── exchange/               ← generic exchange connector abstractions
├── data/                   ← market state dataclasses + normalization
├── strategies/             ← strategy orchestration (thin, imports from core)
├── risk/                   ← Greek aggregation + position limits
├── execution/              ← order routing (placeholder)
├── research/notebooks/     ← Jupyter notebooks for exploratory work
├── config/                 ← settings, secrets
├── utils/                  ← shared utilities
├── checks/                 ← connectivity diagnostics
├── examples/               ← runnable data feed examples
├── docs/                   ← this file
└── main.py                 ← research entry point
```

**Boundary:** The public repo owns connectors, data structures, orchestration, and infrastructure.
`core/` owns all proprietary model logic. Nothing outside `core/` should contain pricing or signal models.

---

## Startup Sequence (main.py)

1. `config/settings.py` — load environment and credentials
2. `deribit/rest.py` — open REST session
3. `data/normalization.py` — fetch and normalise option chain into `MarketState`
4. `core/options/surface.py` — build IV surface
5. `core/options/risk_neutral_distribution.py` — extract Q density per expiry
6. `core/signals/distribution_arbitrage.py` — compare Q vs P, generate signals

---

## core/ (private submodule — aletheia-core)

Model implementations. All proprietary logic lives here. See `core/MODEL.md` for the full mathematical specification.

| File | Purpose | Status |
|------|---------|--------|
| `core/MODEL.md` | Mathematical specification: IV surface, Breeden-Litzenberger, physical distribution models, signal construction | active |
| `core/options/surface.py` | `IVSlice`, `IVSurface`, `build_surface()`. Cubic spline on log-moneyness `m = log(K/F)`. One slice per expiry, calls only | active |
| `core/options/calibration.py` | Placeholder for SVI and SABR parametric calibration | placeholder |
| `core/options/risk_neutral_distribution.py` | `RiskNeutralDistribution`, `extract_risk_neutral_distribution()`. Breeden-Litzenberger via numerical second derivative on Black-76 call price grid. Outputs normalised density, CDF, moments, tail probs, validity flag | active |
| `core/models/physical_distribution.py` | `PhysicalDistributionModel` ABC + `LogNormalHistoricalModel` (lognormal from realised vol). `PhysicalDistribution` dataclass | active |
| `core/models/volatility_models.py` | Placeholder for GARCH(1,1), Heston, EWMA vol forecasting | placeholder |
| `core/signals/distribution_arbitrage.py` | `DistributionSignal`, `compare_distributions()`. Computes KL divergence, Wasserstein-1, variance/skew/tail diffs between Q and P. Produces direction and suggested trade | active |

---

## deribit/

Native async Deribit connectors. Do not modify without updating both REST and WS layers.

| File | Purpose | Status |
|------|---------|--------|
| `deribit/types.py` | TypedDicts for all Deribit objects: `Ticker`, `Trade`, `Instrument`, `OrderBookSnapshot`, `IndexPrice`, `VolatilityIndex`, `OptionMarkPrice`, `FundingRate` | active |
| `deribit/rest.py` | `DeribitREST`: async REST client. `get_instruments`, `get_ticker`, `get_order_book`, `get_index_price`, `get_last_trades`, `get_historical_volatility` | active |
| `deribit/connector.py` | `DeribitConnector`: WebSocket streams. `watch_order_book`, `watch_trades`, `watch_ticker`, `watch_index`, `watch_volatility_index`, `watch_mark_prices`, `watch_funding` | active |

---

## exchange/

Generic connector abstractions for non-Deribit venues. Kept for modularity; not used by the primary research pipeline.

| File | Purpose | Status |
|------|---------|--------|
| `exchange/base.py` | Abstract `BaseRestConnector` and `BaseWebSocketConnector` | active |
| `exchange/registry.py` | Maps venue name strings to connector classes | active |
| `exchange/binance/rest.py` | Binance REST stub | stub |
| `exchange/binance/ws.py` | Binance WebSocket stub | stub |

---

## data/

Market state representation and normalization. Data structures only — no model logic.

| File | Purpose | Status |
|------|---------|--------|
| `data/market_state.py` | `MarketState`, `OptionQuote`, `FutureQuote` dataclasses. Central snapshot object consumed by all models. Convenience methods: `calls()`, `puts()`, `expiries()`, `perpetual()`, `forward()` | active |
| `data/normalization.py` | Converts raw `deribit.types` objects to domain types. `ticker_to_option_quote()`, `ticker_to_future_quote()`, `build_market_state()` | active |

---

## strategies/

Strategy orchestration. Thin layer: consumes `core.signals`, applies risk limits, produces `TradeDecision`.

| File | Purpose | Status |
|------|---------|--------|
| `strategies/option_relative_value.py` | `TradeDecision`, `generate_decision()`. Translates `DistributionSignal` into sized, risk-checked trade instruction | active |

---

## risk/

Portfolio risk management. Greek aggregation and hard position limits.

| File | Purpose | Status |
|------|---------|--------|
| `risk/greeks.py` | `GreekExposure`, `Position`, `compute_exposure()`. Aggregates net/gross Greeks across open positions | active |
| `risk/limits.py` | `RiskLimits` dataclass: max vega, delta, gamma, notional. `RiskLimits.conservative()` preset | active |

---

## execution/

Order routing. Not yet implemented.

| File | Purpose | Status |
|------|---------|--------|
| `execution/__init__.py` | Package marker | placeholder |

---

## research/

Jupyter notebooks for exploratory research. No production code lives here.

| Path | Purpose |
|------|---------|
| `research/notebooks/` | Working notebooks: surface inspection, RND extraction, signal backtesting |

---

## config/

| File | Purpose | Status |
|------|---------|--------|
| `config/settings.py` | `Settings.load()`: reads `.env`, exposes `testnet`, `api_key`, `api_secret`, `currencies`, `dry_run` | active |
| `config/watcher.py` | Hot-reload stub (unused in research mode) | stub |
| `config/.env` | Secret keys; never committed | active |

---

## utils/

| File | Purpose | Status |
|------|---------|--------|
| `utils/logger.py` | `get_logger(name)` — stdout logger with standard formatter | active |

---

## checks/

Connectivity diagnostics. Run manually to verify credentials and feeds.

| File | Purpose |
|------|---------|
| `checks/auth.py` | Verify Deribit API key |
| `checks/rest.py` | Smoke-test REST endpoints |
| `checks/ws.py` | Smoke-test WebSocket streams |

---

## Root

| File | Purpose |
|------|---------|
| `main.py` | Research entry point: fetch option chain, build IV surface, extract RND, print summary |
| `pyproject.toml` | Package metadata and dependencies |
| `CLAUDE.md` | Project instructions for Claude Code |
