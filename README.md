# Aletheia

An options implied distribution arbitrage research and trading framework targeting Deribit BTC and ETH options.

The core idea: extract the risk-neutral distribution Q from live option prices via Breeden-Litzenberger, estimate the physical distribution P from realised returns, and trade the divergence between them — vol carry, skew carry, or tail mispricing — using delta-neutral option spreads.

## Architecture

```
deribit/          — async WebSocket + REST connectors (native aiohttp)
data/             — market state normalisation (Deribit → internal types)
config/           — settings and secrets (dry_run, testnet, API keys)
utils/            — dependency-free helpers (logger)
core/             — private submodule: model logic, strategies, risk
main.py           — research entry point
```

`core/` is a private git submodule ([aletheia-core](https://github.com/DaanZunnenberg/aletheia-core)) and is not included in this public repository. It contains:

- `core/market_state.py` — `OptionQuote`, `FutureQuote`, `MarketState` domain model
- `core/options/surface.py` — IV surface construction (log-moneyness, cubic spline per expiry)
- `core/options/risk_neutral_distribution.py` — Breeden-Litzenberger RND extraction
- `core/models/physical_distribution.py` — log-normal historical P distribution
- `core/signals/distribution_arbitrage.py` — KL divergence, Wasserstein-1, vol/skew signals
- `core/strategies/option_relative_value.py` — delta-neutral trade decisions
- `core/risk/` — Greek exposure aggregation and hard position limits
- `core/_math.py` — shared CDF, moment, and tail probability utilities

## Data Flow

```
Deribit REST → fetch option chain + futures curve + spot index
             → normalise to MarketState
             → build IV surface (cubic spline per expiry)
             → extract RND via Breeden-Litzenberger (Q)
             → compare against historical P distribution
             → compute KL divergence + Wasserstein-1 + vol/skew signals
             → generate delta-neutral trade decisions
             → enforce risk limits → emit orders (dry-run by default)
```

## Setup

**Requirements:** Python ≥ 3.10

```bash
git clone --recurse-submodules https://github.com/DaanZunnenberg/Aletheia.git
cd Aletheia
pip install -e .
cp config/.env.example config/.env   # then fill in credentials
python main.py
```

**Environment variables** (all optional; defaults are safe for research):

| Variable | Default | Description |
|---|---|---|
| `TESTNET` | `true` | Connect to `test.deribit.com` (paper trading). Set `false` for live. |
| `DRY_RUN` | `true` | Log orders but never send them. Set `false` only in production. |
| `DERIBIT_TEST_API_KEY` | — | Testnet API key (required if using authenticated endpoints) |
| `DERIBIT_TEST_API_SECRET` | — | Testnet API secret |
| `DERIBIT_API_KEY` | — | Production API key |
| `DERIBIT_API_SECRET` | — | Production API secret |
| `CURRENCIES` | `BTC,ETH` | Comma-separated list of underlying currencies to monitor |
| `LOG_LEVEL` | `INFO` | Python log level (`DEBUG`, `INFO`, `WARNING`) |

**Warning:** setting `TESTNET=false` connects to `deribit.com` with real funds and prints a large warning to stderr. This requires `DERIBIT_API_KEY` and `DERIBIT_API_SECRET` to be set.

## Dependencies

| Package | Version | Purpose |
|---|---|---|
| `aiohttp` | ≥ 3.9 | Async HTTP client and WebSocket transport for Deribit connectors |
| `orjson` | ≥ 3.9 | Fast JSON serialisation / deserialisation of exchange messages |
| `python-dotenv` | ≥ 1.0 | Load `config/.env` into environment at startup |
| `numpy` | ≥ 1.24 | Numerical arrays, spline evaluation, integral approximation |
| `scipy` | ≥ 1.11 | `CubicSpline` for IV surface fitting; `norm` for Black-Scholes |
| `pandas` | ≥ 2.0 | Historical return series for physical distribution calibration |

## Entry Point

`main.py` is a research script. It fetches the full option chain for each configured currency, builds the IV surface per expiry, and logs the extracted risk-neutral distribution (mean, skewness, kurtosis, validity). No orders are sent.

The quoting loop and live strategy execution live in `core/strategies/` (private submodule) and are invoked from a separate entry point not included in this public repository.

## Mathematical Specification

See `core/MODEL.md` in the private submodule for the full mathematical specification covering:

- Breeden-Litzenberger RND extraction: f^Q(K) = e^(rT) · d²C/dK²
- IV surface parameterisation (log-moneyness normalisation, cubic spline)
- Physical distribution estimation (log-normal, EWMA volatility)
- Signal construction (KL divergence, Wasserstein-1 distance)
- Delta-neutral trade construction and Greek risk aggregation

## Risk Defaults

All position limits default to conservative values and apply before any order is generated:

| Limit | Default |
|---|---|
| Max gross vega (USD) | 10,000 |
| Max net delta (USD) | 50,000 |
| Max gross gamma (USD) | 5,000 |
| Max notional (USD) | 500,000 |
| Delta hedge tolerance | 2% of notional |

Override by instantiating `RiskLimits` directly or using `RiskLimits.conservative()`.
