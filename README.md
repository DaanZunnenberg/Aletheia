# Aletheia

Crypto perpetual market-making framework. Quotes both sides of the book on
BTC/ETH perpetuals, managing inventory risk with closed-form quoting models
(Avellaneda-Stoikov, GLFT) and regime/toxicity-aware gating, backtested
against real exchange data.

## Layout

```
aletheia/
├── data/           ← exchange-agnostic OrderBookUpdate type
├── exchanges/       ← live L2 order-book connectors (Deribit, Binance)
├── deribit/         ← Deribit REST client (historical trades, instruments)
├── examples/        ← runnable demos (live streaming, live quoting)
├── core/            ← PRIVATE submodule: quoting models, risk, backtest engines
├── research/        ← PRIVATE submodule: notebooks, validation scripts, real-data demos
├── tests/           ← tests for the public data/exchanges layer
└── utils/           ← dependency-free helpers (logger)
```

`core/` and `research/` are separate private GitHub repos (`aletheia-core`,
`aletheia-research`) linked as git submodules. Everything else in this repo
is public.

## Model architecture

The strategy is layered; each layer is a separate concern with its own
module(s), not a monolith:

| Layer | Module(s) | Role |
|---|---|---|
| **Volatility** | `core/models/volatility.py` | EWMA realised vol feeding every downstream layer |
| **Logic (quoting)** | `core/models/quoting.py`, `core/models/glft.py`, `core/strategies/` | Avellaneda-Stoikov / GLFT reservation price + spread, ladder quoting |
| **Regime / toxicity** | `core/models/regime.py`, `core/models/toxicity.py`, `core/models/forward_risk_net.py` | HMM regime detection, VPIN, a trained nonlinear forward-risk model -- gates gamma and pausing |
| **Inventory** | `core/risk/exposure.py` | Position tracking, realised/unrealised P&L, funding accrual |
| **Risk (static)** | `core/risk/limits.py` | Hard position/notional/order-size/daily-loss caps |
| **Tail risk (dynamic)** | `core/risk/tail_risk.py` | Market-condition circuit breakers: price jump, feed staleness, vol-spike-relative-to-regime -- independent of current inventory |
| **Greeks** | *(not yet built)* | Deferred: relevant only if/when an options overlay is added (see project history for the 0DTE options discussion) |

See `core/MODEL.md` for the full mathematical specification of the quoting
models.

## Data pipeline

`exchanges/` streams live L2 order books from Deribit and Binance
concurrently, for any mix of coins and market types (perpetual, spot) --
`examples/stream_multi_exchange_books.py` demonstrates six concurrent
streams (BTC/ETH x {Deribit perp, Binance perp, Binance spot}) merged into
one feed via `exchanges/stream_manager.py`. This is the hedging-instrument
set: Deribit's perpetual is the primary quoting venue, Binance's spot and
perpetual markets are cross-venue references and hedge legs.

`core/backtest/historical.py` replays real trade tapes (and, for Binance,
real order-book depth) through any quoting engine -- see
`research/historical_backtest_demo.py` and
`research/binance_ladder_backtest_demo.py` for real-BTC/ETH walk-forward
comparisons.

## Quick start

```bash
pip install -r requirements.txt
python examples/stream_multi_exchange_books.py 20   # live multi-exchange book stream
python examples/live_quote_loop.py 30                # live AS quoting, dry-run
pytest tests/ core/tests/                             # 93 tests, public + private layers
```

## Safety

Everything here is dry-run: live examples print quotes, they place no
orders. Order execution is not implemented yet.
