# Aletheia — File Reference

Living reference for every file in the project. Update whenever a file is added,
removed, or its functionality or status changes.

Status codes: `active` (logic implemented) | `stub` (skeleton only) | `placeholder` (intentionally empty, documents future intent)

---

## Startup Sequence (main.py)

1. `config/settings.py` — load environment and credentials
2. `deribit/rest.py` — open REST session
3. `data/normalization.py` — fetch and normalise option chain into MarketState
4. `options/surface.py` — build IV surface from MarketState
5. `options/risk_neutral_distribution.py` — extract Q density per expiry
6. `signals/distribution_arbitrage.py` — compare Q vs P, generate signals

---

## config/

| File | Purpose | Status | Dependencies |
|------|---------|--------|--------------|
| `config/settings.py` | Loads `.env`; exposes `Settings` dataclass with `testnet`, `api_key`, `api_secret`, `currencies`, `dry_run` | active | `python-dotenv` |
| `config/watcher.py` | File-watch hot-reload for settings (unused in research mode) | stub | — |
| `config/.env` | Secret environment variables; never committed | active | — |

---

## deribit/

Native async Deribit connectors. Do not modify without updating both REST and WS layers.

| File | Purpose | Status | Dependencies |
|------|---------|--------|--------------|
| `deribit/types.py` | TypedDicts for all Deribit domain objects: `Ticker`, `Trade`, `Instrument`, `OrderBookSnapshot`, `IndexPrice`, `VolatilityIndex`, `OptionMarkPrice`, `FundingRate` | active | — |
| `deribit/rest.py` | `DeribitREST`: async REST client. `get_instruments`, `get_ticker`, `get_order_book`, `get_index_price`, `get_last_trades`, `get_historical_volatility` | active | `aiohttp`, `orjson`, `pandas` |
| `deribit/connector.py` | `DeribitConnector`: WebSocket streams. `watch_order_book`, `watch_trades`, `watch_ticker`, `watch_index`, `watch_volatility_index`, `watch_mark_prices`, `watch_funding` | active | `aiohttp`, `orjson` |

---

## exchange/

Generic connector abstractions for non-Deribit venues. Modular; not used by the primary research pipeline.

| File | Purpose | Status | Dependencies |
|------|---------|--------|--------------|
| `exchange/base.py` | Abstract `BaseRestConnector` and `BaseWebSocketConnector` interfaces | active | — |
| `exchange/registry.py` | Maps venue name strings to connector classes | active | — |
| `exchange/binance/rest.py` | Binance REST stub | stub | `aiohttp` |
| `exchange/binance/ws.py` | Binance WebSocket stub | stub | `aiohttp` |

---

## data/

Market state representation and data normalization.

| File | Purpose | Status | Dependencies |
|------|---------|--------|--------------|
| `data/market_state.py` | `MarketState`, `OptionQuote`, `FutureQuote` dataclasses. Central snapshot object consumed by all models | active | — |
| `data/normalization.py` | Converts raw `deribit.types` objects to domain types; `build_market_state()` | active | `deribit.types`, `data.market_state` |

---

## options/

Options analytics: IV surface construction and risk-neutral distribution extraction.

| File | Purpose | Status | Dependencies |
|------|---------|--------|--------------|
| `options/surface.py` | `IVSlice`, `IVSurface`, `build_surface()`. Constructs spline-interpolated IV surface normalised to log-moneyness `m = log(K/F)`. Grouped by expiry, calls only | active | `scipy`, `numpy`, `data.market_state` |
| `options/calibration.py` | Placeholder for SVI and SABR parametric calibration. Documents planned interface | placeholder | — |
| `options/risk_neutral_distribution.py` | `RiskNeutralDistribution`, `extract_risk_neutral_distribution()`. Breeden-Litzenberger numerical second derivative on dense call-price grid. Outputs normalised density, CDF, moments, tail probabilities | active | `scipy`, `numpy`, `options.surface` |

---

## models/

Physical distribution estimators. All implement `PhysicalDistributionModel` ABC.

| File | Purpose | Status | Dependencies |
|------|---------|--------|--------------|
| `models/physical_distribution.py` | `PhysicalDistribution`, `PhysicalDistributionModel` ABC, `LogNormalHistoricalModel` (baseline: lognormal from realised vol) | active | `numpy`, `data.market_state` |
| `models/volatility_models.py` | Placeholder for GARCH, Heston, EWMA vol forecasting | placeholder | — |

---

## signals/

Distribution comparison and signal generation.

| File | Purpose | Status | Dependencies |
|------|---------|--------|--------------|
| `signals/distribution_arbitrage.py` | `DistributionSignal`, `compare_distributions()`. Computes KL divergence, Wasserstein-1, variance diff, skew diff, tail probability differences between Q and P | active | `numpy`, `options.risk_neutral_distribution`, `models.physical_distribution` |

---

## strategies/

Strategy decision layer. Consumes signals; produces `TradeDecision` objects.

| File | Purpose | Status | Dependencies |
|------|---------|--------|--------------|
| `strategies/option_relative_value.py` | `TradeDecision`, `generate_decision()`. Translates `DistributionSignal` into a sized, risk-checked trade instruction | active | `signals.distribution_arbitrage`, `risk.limits`, `risk.greeks` |

---

## risk/

Portfolio risk management.

| File | Purpose | Status | Dependencies |
|------|---------|--------|--------------|
| `risk/greeks.py` | `GreekExposure`, `Position`, `compute_exposure()`. Aggregates net and gross Greeks across open positions | active | `data.market_state` |
| `risk/limits.py` | `RiskLimits` dataclass with hard caps on vega, delta, gamma, notional. `RiskLimits.conservative()` preset | active | — |

---

## execution/

Placeholder. Order routing not yet implemented.

| File | Purpose | Status |
|------|---------|--------|
| `execution/__init__.py` | Empty package marker | placeholder |

---

## research/

Jupyter notebooks for exploratory research. No production code here.

| File | Purpose | Status |
|------|---------|--------|
| `research/notebooks/` | Working notebooks for signal development and backtesting | placeholder |

---

## utils/

| File | Purpose | Status | Dependencies |
|------|---------|--------|--------------|
| `utils/logger.py` | `get_logger(name)` — standard `logging.Logger` with stdout handler | active | — |

---

## checks/

Connectivity diagnostics. Run manually to verify API credentials and data feeds.

| File | Purpose | Status |
|------|---------|--------|
| `checks/auth.py` | Verify Deribit API key authentication | active |
| `checks/rest.py` | Smoke-test REST endpoints | active |
| `checks/ws.py` | Smoke-test WebSocket streams | active |

---

## Root

| File | Purpose |
|------|---------|
| `main.py` | Research entry point: fetches live option chain, builds surface, extracts RND per expiry, prints summary |
| `pyproject.toml` | Package metadata and dependencies |
| `CLAUDE.md` | Project instructions for Claude Code |
