# Aletheia

A market-making framework for Deribit BTC/ETH perpetuals.

The core idea: quote both sides continuously, capture the spread, and manage
the resulting inventory risk with an Avellaneda-Stoikov quoting model —
skewing the reservation price against inventory and widening the spread when
either volatility or adverse selection risk rises.

## Architecture

```
deribit/          — async WebSocket + REST connectors (native aiohttp)
data/             — market state normalisation (Deribit → internal types)
config/           — settings and secrets (dry_run, testnet, API keys)
utils/            — dependency-free helpers (logger)
core/             — private submodule: the model itself
main.py           — test entry point
```

`core/` is a private git submodule ([aletheia-core](https://github.com/DaanZunnenberg/aletheia-core))
and is not included in this public repository. It contains:

- `core/market_state.py` — `MarketState` domain model (top-of-book, mark/index price, funding)
- `core/models/quoting.py` — Avellaneda-Stoikov reservation price, optimal spread, fill-intensity calibration
- `core/models/volatility.py` — realised volatility estimator (EWMA of squared log returns)
- `core/signals/microstructure.py` — order book imbalance, trade imbalance
- `core/risk/exposure.py` — position tracking, realized/unrealized P&L, funding accrual
- `core/risk/limits.py` — hard position/order/notional/loss limits
- `core/strategies/market_maker.py` — assembles the above into a risk-checked `QuoteDecision`

Everything outside `core/` is infrastructure for exercising the model, not the
strategy itself: fetching a snapshot, normalising it, and running one quoting
decision through it. There is no live order-placement loop yet.

## Data Flow

```
Deribit REST/WS → ticker + order book for the perpetual
                → normalise to MarketState
                → estimate realised vol
                → Avellaneda-Stoikov reservation price + spread
                → risk-check against position limits
                → emit a QuoteDecision (dry-run by default; no order routing yet)
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
| `CURRENCIES` | `BTC,ETH` | Comma-separated list of underlyings whose perpetual to quote |
| `LOG_LEVEL` | `INFO` | Python log level (`DEBUG`, `INFO`, `WARNING`) |

**Warning:** setting `TESTNET=false` connects to `deribit.com` with real funds and prints a large warning to stderr. This requires `DERIBIT_API_KEY` and `DERIBIT_API_SECRET` to be set.

## Dependencies

| Package | Version | Purpose |
|---|---|---|
| `aiohttp` | ≥ 3.9 | Async HTTP client and WebSocket transport for Deribit connectors |
| `orjson` | ≥ 3.9 | Fast JSON serialisation / deserialisation of exchange messages |
| `python-dotenv` | ≥ 1.0 | Load `config/.env` into environment at startup |
| `numpy` | ≥ 1.24 | Numerical arrays, EWMA vol, kappa calibration |
| `pandas` | ≥ 2.0 | Trade tape handling for fill-intensity calibration and imbalance signals |

## Entry Point

`main.py` fetches the current perpetual ticker + order book for each
configured currency, builds a `MarketState`, and logs a single quoting
decision (bid/ask price, size, and any risk-limit breaches). No orders are
sent — order routing is not yet implemented (`execution/` is a placeholder).

## Mathematical Specification

See `core/MODEL.md` in the private submodule for the full mathematical specification.

## Risk Defaults

`RiskLimits.conservative()`:

| Limit | Default |
|---|---|
| Max net position (contracts) | 0.25 |
| Max order size (contracts) | 0.025 |
| Max gross notional (USD) | 10,000 |
| Max daily loss (USD) | 500 |

Override by instantiating `RiskLimits` directly.
