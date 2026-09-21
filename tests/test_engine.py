from __future__ import annotations

import numpy as np

from core.models.options.black76 import OptionType
from data.orderbook import OrderBookUpdate
from deribit.types import Trade
from paper.engine import PaperTradingEngine, QuotedOption, QuotedPerp
from paper.fill_simulator import PaperFill
from paper.hedger import HardHedgeLimits

_PERP_KEY = ("deribit", "perpetual", "BTC-PERPETUAL")
_OPTION_KEY = ("deribit", "option", "BTC-21SEP26-81000-C")
_REF_KEY = ("binance", "spot", "BTCUSDT")


def _perp_update(mid: float, t: float, spread: float = 2.0) -> OrderBookUpdate:
    return OrderBookUpdate(
        exchange="deribit", market_type="perpetual", symbol="BTC-PERPETUAL",
        bids=((mid - spread / 2, 5.0),), asks=((mid + spread / 2, 5.0),), timestamp=t * 1000.0,
    )


def _option_update(bid: float, ask: float, t: float) -> OrderBookUpdate:
    return OrderBookUpdate(
        exchange="deribit", market_type="option", symbol="BTC-21SEP26-81000-C",
        bids=((bid, 5.0),), asks=((ask, 5.0),), timestamp=t * 1000.0,
    )


def _ref_update(mid: float, t: float) -> OrderBookUpdate:
    return OrderBookUpdate(
        exchange="binance", market_type="spot", symbol="BTCUSDT",
        bids=((mid - 0.5, 5.0),), asks=((mid + 0.5, 5.0),), timestamp=t * 1000.0,
    )


def _trade(instrument: str, price: float, amount: float, direction: str, t: float) -> Trade:
    return Trade(
        instrument_name=instrument, price=price, amount=amount, direction=direction,
        timestamp=t * 1000.0, trade_id="1", index_price=price, mark_price=price,
    )


def _new_engine(**overrides) -> PaperTradingEngine:
    defaults = dict(
        quoted_perps=[QuotedPerp(key=_PERP_KEY, underlying_ccy="BTC")],
        quoted_options=[
            QuotedOption(
                key=_OPTION_KEY, underlying_ccy="BTC", underlying_key=_PERP_KEY,
                strike=81_000.0, option_type=OptionType.CALL, expiration_timestamp_ms=1e15,  # far future
            )
        ],
        reference_keys=[_REF_KEY],
    )
    defaults.update(overrides)
    return PaperTradingEngine(**defaults)


def _warm_up_perp(engine: PaperTradingEngine, seed: int = 0, mid: float = 81_000.0) -> float:
    rng = np.random.default_rng(seed)
    for i in range(30):
        mid += rng.normal(0, 1.0)
        engine.on_book_update(_perp_update(mid, t=float(i)))
    return mid


def test_no_quote_before_volatility_warmup():
    engine = _new_engine()
    engine.on_book_update(_perp_update(81_000.0, t=0.0))
    assert _PERP_KEY not in engine.resting_quotes


def test_perp_quote_appears_after_warmup():
    engine = _new_engine()
    _warm_up_perp(engine)
    assert _PERP_KEY in engine.resting_ladders
    ladder = engine.resting_ladders[_PERP_KEY]
    assert ladder.bid_levels[0].price < ladder.ask_levels[0].price
    assert len(ladder.bid_levels) == 3  # default LadderParams.n_levels
    assert len(ladder.ask_levels) == 3


def test_reference_stream_is_never_quoted():
    engine = _new_engine()
    for i in range(30):
        engine.on_book_update(_ref_update(81_000.0 + i, t=float(i)))
    assert _REF_KEY not in engine.resting_quotes


def test_perp_fill_via_trade_tape_walking_through_our_bid():
    engine = _new_engine()
    _warm_up_perp(engine, seed=1)
    ladder = engine.resting_ladders[_PERP_KEY]
    # walk through the deepest bid level -- guarantees every level fills
    deepest_bid = ladder.bid_levels[-1].price

    trade = _trade("BTC-PERPETUAL", price=deepest_bid - 1.0, amount=1.0, direction="sell", t=31.0)
    engine.on_trade(trade)

    assert engine.position_book.position_for("deribit:perpetual:BTC-PERPETUAL").quantity > 0.0
    assert engine.n_fills >= 1


def test_trade_before_latency_elapses_does_not_fill():
    """A trade at the exact same timestamp as the quote decision hasn't had
    time to see our (not-yet-live) quote -- must not fill."""
    engine = _new_engine()
    _warm_up_perp(engine, seed=1)
    ladder = engine.resting_ladders[_PERP_KEY]
    deepest_bid = ladder.bid_levels[-1].price

    trade = _trade("BTC-PERPETUAL", price=deepest_bid - 1.0, amount=1.0, direction="sell", t=29.0)
    engine.on_trade(trade)
    assert engine.n_fills == 0


def test_trade_for_an_unquoted_instrument_is_ignored():
    engine = _new_engine()
    _warm_up_perp(engine, seed=1)
    trade = _trade("SOL-PERPETUAL", price=50.0, amount=100.0, direction="sell", t=31.0)
    engine.on_trade(trade)  # must not raise
    assert engine.n_fills == 0


def test_option_quote_requires_underlying_and_volatility():
    engine = _new_engine()
    # option book arrives before any perp (underlying) data -- must not crash, must not quote yet
    engine.on_book_update(_option_update(0.01, 0.011, t=0.0))
    assert _OPTION_KEY not in engine.resting_quotes


def test_option_quote_appears_once_underlying_and_vol_are_available():
    engine = _new_engine()
    _warm_up_perp(engine, seed=2)
    engine.on_book_update(_option_update(0.01, 0.011, t=31.0))
    assert _OPTION_KEY in engine.resting_quotes
    quote = engine.resting_quotes[_OPTION_KEY]
    assert quote.bid_price < quote.ask_price
    assert quote.bid_price < 1.0  # coin-denominated, not USD


def test_option_greeks_do_not_crash_on_a_flat_bar_run():
    """Regression: a run of bit-identical bar closes gives EWMA sigma of
    exactly 0.0, which black76_greeks divides by -- crashed live before
    engine.py floored it. Feed perfectly flat prices to reproduce."""
    engine = _new_engine()
    for i in range(30):
        engine.on_book_update(_perp_update(81_000.0, t=float(i)))  # identical mid every tick -> sigma == 0.0
    engine.on_book_update(_option_update(0.01, 0.011, t=31.0))
    assert _OPTION_KEY in engine.resting_quotes  # must not have raised


def test_option_fill_via_trade_tape():
    engine = _new_engine()
    _warm_up_perp(engine, seed=2)
    engine.on_book_update(_option_update(0.01, 0.011, t=31.0))
    quote = engine.resting_quotes[_OPTION_KEY]

    trade = _trade("BTC-21SEP26-81000-C", price=quote.ask_price + 0.001, amount=5.0, direction="buy", t=32.0)
    engine.on_trade(trade)
    assert engine.position_book.position_for("deribit:option:BTC-21SEP26-81000-C").quantity < 0.0


def test_snapshot_reflects_all_seen_instruments():
    engine = _new_engine()
    engine.on_book_update(_perp_update(81_000.0, t=0.0))
    engine.on_book_update(_ref_update(81_000.0, t=0.0))
    symbols = {row.instrument for row in engine.snapshot()}
    assert symbols == {"BTC-PERPETUAL", "BTCUSDT"}


def test_snapshot_marks_reference_rows_correctly():
    engine = _new_engine()
    engine.on_book_update(_ref_update(81_000.0, t=0.0))
    row = engine.snapshot()[0]
    assert row.kind == "reference-spot"
    assert row.our_bid is None and row.our_ask is None


def test_spot_and_perp_sharing_a_symbol_get_separate_positions():
    """Regression: Binance spot and perpetual both use the literal symbol
    'BTCUSDT' -- positions must be keyed by (exchange, market_type, symbol),
    not bare symbol, or one would silently absorb the other's fills."""
    engine = _new_engine()
    engine.position_book.apply_fill("binance:spot:BTCUSDT", 0.0, PaperFill(side="bid", price=81_000.0, size=1.0))
    engine.position_book.apply_fill("binance:perpetual:BTCUSDT", 0.0, PaperFill(side="ask", price=81_000.0, size=2.0))

    assert engine.position_book.position_for("binance:spot:BTCUSDT").quantity == 1.0
    assert engine.position_book.position_for("binance:perpetual:BTCUSDT").quantity == -2.0


def test_portfolio_greeks_populated_after_perp_warmup():
    engine = _new_engine()
    _warm_up_perp(engine, seed=0)
    assert "BTC" in engine.portfolio_greeks


def test_flat_book_has_near_zero_portfolio_delta():
    engine = _new_engine()
    _warm_up_perp(engine, seed=0)
    assert abs(engine.portfolio_greeks["BTC"].delta) < 1e-6


def test_hard_hedge_fires_when_position_breaches_the_delta_band():
    engine = _new_engine(hard_hedge_limits=HardHedgeLimits(max_abs_delta=0.1))
    _warm_up_perp(engine, seed=0)
    # force a large position directly, bypassing normal fill flow, to isolate the hedge trigger
    engine.position_book.position_for("deribit:perpetual:BTC-PERPETUAL").apply_fill(0.5, 81_000.0)

    engine.on_book_update(_perp_update(81_000.0, t=30.0))  # one more update triggers the hedge check
    assert engine.n_hard_hedges >= 1

    hedge_events = [e for e in engine.event_log if e.event_type == "hedge"]
    assert hedge_events
    assert hedge_events[-1].fee is not None and hedge_events[-1].fee > 0.0  # taker fee is a real cost
    assert hedge_events[-1].slippage is not None


def test_hard_hedge_does_not_fire_within_the_band():
    engine = _new_engine(hard_hedge_limits=HardHedgeLimits(max_abs_delta=1.0))
    _warm_up_perp(engine, seed=0)
    engine.on_book_update(_perp_update(81_000.0, t=30.0))
    assert engine.n_hard_hedges == 0


def test_session_log_records_quotes_and_fills(tmp_path):
    from paper.session_replay import load_session

    log_path = tmp_path / "session.jsonl"
    engine = _new_engine(session_log_path=log_path)
    _warm_up_perp(engine, seed=1)
    ladder = engine.resting_ladders[_PERP_KEY]
    deepest_bid = ladder.bid_levels[-1].price
    engine.on_trade(_trade("BTC-PERPETUAL", price=deepest_bid - 1.0, amount=1.0, direction="sell", t=31.0))
    engine.close()

    events = load_session(log_path)
    assert any(e.event_type == "quote" for e in events)
    assert any(e.event_type == "fill" for e in events)
    assert any(e.event_type == "greeks" for e in events)


def test_warmup_status_starts_at_fast_vol_stage():
    engine = _new_engine()
    engine.on_book_update(_perp_update(81_000.0, t=0.0))
    stage, collected, needed, eta = engine.warmup_status("BTC")
    assert stage == "fast_vol"
    assert collected == 1
    assert eta > 0.0


def test_warmup_status_progresses_to_regime_stage_after_fast_vol_ready():
    engine = _new_engine()
    _warm_up_perp(engine, seed=0)  # 30 bars -- clears fast_vol (20) but not regime (300)
    stage, collected, needed, eta = engine.warmup_status("BTC")
    assert stage == "regime"
    assert collected == 30
    assert eta > 0.0


def test_warmup_status_reaches_ready_after_enough_bars():
    engine = _new_engine()
    rng = np.random.default_rng(0)
    mid = 81_000.0
    for i in range(310):
        mid += rng.normal(0, 1.0)
        engine.on_book_update(_perp_update(mid, t=float(i)))
    stage, collected, needed, eta = engine.warmup_status("BTC")
    assert stage == "ready"
    assert eta == 0.0


def test_no_regime_before_warmup_completes():
    engine = _new_engine()
    _warm_up_perp(engine, seed=0)
    assert "BTC" not in engine.regimes


def test_regime_appears_once_warmed_up():
    engine = _new_engine()
    rng = np.random.default_rng(0)
    mid = 81_000.0
    for i in range(310):
        mid += rng.normal(0, 1.0)
        engine.on_book_update(_perp_update(mid, t=float(i)))
    assert "BTC" in engine.regimes
    regime = engine.regimes["BTC"]
    assert regime.vol_regime in {"CALM", "NORMAL", "ACTIVE", "VOLATILE"}
    assert regime.trend_regime in {"BULL", "BEAR", "EVEN"}


def test_sustained_uptrend_is_classified_bull():
    engine = _new_engine()
    mid = 81_000.0
    for i in range(310):
        mid *= 1.0002  # steady upward drift, no noise
        engine.on_book_update(_perp_update(mid, t=float(i)))
    assert engine.regimes["BTC"].trend_regime == "BULL"


def test_update_event_is_set_on_book_update():
    engine = _new_engine()
    assert not engine.update_event.is_set()
    engine.on_book_update(_perp_update(81_000.0, t=0.0))
    assert engine.update_event.is_set()


def test_update_event_is_set_on_fill():
    engine = _new_engine()
    _warm_up_perp(engine, seed=1)
    engine.update_event.clear()
    ladder = engine.resting_ladders[_PERP_KEY]
    deepest_bid = ladder.bid_levels[-1].price
    engine.on_trade(_trade("BTC-PERPETUAL", price=deepest_bid - 1.0, amount=1.0, direction="sell", t=31.0))
    assert engine.update_event.is_set()


def test_risk_snapshots_empty_before_perp_has_a_book():
    engine = _new_engine()
    assert engine.risk_snapshots() == {}


def test_risk_snapshots_reports_position_against_limits():
    engine = _new_engine()
    _warm_up_perp(engine, seed=1)
    ladder = engine.resting_ladders[_PERP_KEY]
    deepest_bid = ladder.bid_levels[-1].price
    engine.on_trade(_trade("BTC-PERPETUAL", price=deepest_bid - 1.0, amount=1.0, direction="sell", t=31.0))
    snapshot = engine.risk_snapshots()["BTC"]
    assert snapshot.position > 0.0
    assert snapshot.max_position == 1.0
    assert snapshot.max_gross_notional_usd == 50_000.0
    assert snapshot.max_abs_delta == HardHedgeLimits().max_abs_delta


def test_event_log_records_merged_book_and_quote_snapshot():
    engine = _new_engine()
    _warm_up_perp(engine, seed=1)
    quote_events = [e for e in engine.event_log if e.event_type == "quote"]
    assert quote_events
    row = quote_events[-1]
    assert row.our_bid is not None and row.our_ask is not None
    assert row.book_bid is not None and row.book_ask is not None
    assert row.book_bid_size is not None and row.book_ask_size is not None


def test_event_log_records_fill_with_fee_and_slippage():
    engine = _new_engine()
    _warm_up_perp(engine, seed=1)
    ladder = engine.resting_ladders[_PERP_KEY]
    deepest_bid = ladder.bid_levels[-1].price
    engine.on_trade(_trade("BTC-PERPETUAL", price=deepest_bid - 1.0, amount=1.0, direction="sell", t=31.0))
    fill_events = [e for e in engine.event_log if e.event_type == "fill"]
    assert fill_events
    row = fill_events[-1]
    assert row.side == "bid"
    assert row.price is not None
    assert row.size is not None
    assert row.fee is not None
    assert row.slippage == 0.0  # maker fill: no execution slippage


def test_snapshot_includes_order_book_depth():
    engine = _new_engine()
    _warm_up_perp(engine, seed=0)
    snap = next(s for s in engine.snapshot() if s.instrument == "BTC-PERPETUAL")
    assert len(snap.book_bids) >= 1
    assert len(snap.book_asks) >= 1


def test_event_log_excludes_greeks_and_regime_state_updates():
    engine = _new_engine()
    rng = np.random.default_rng(0)
    mid = 81_000.0
    for i in range(310):
        mid += rng.normal(0, 1.0)
        engine.on_book_update(_perp_update(mid, t=float(i)))
    event_types = {e.event_type for e in engine.event_log}
    assert "greeks" not in event_types
    assert "regime" not in event_types
    assert "BTC" in engine.regimes  # still tracked as state, just not tape rows
    assert "BTC" in engine.portfolio_greeks


def test_snapshot_includes_option_pricing_and_vrp_edge():
    engine = _new_engine()
    _warm_up_perp(engine, seed=2)
    engine.on_book_update(_option_update(0.01, 0.011, t=31.0))
    snap = next(s for s in engine.snapshot() if s.instrument == "BTC-21SEP26-81000-C")
    assert snap.realized_vol is not None
    assert snap.fair_vol is not None
    assert snap.fair_vol > snap.realized_vol  # VRP_MULTIPLIER > 1.0
    assert snap.theo_price is not None
    assert snap.theo_price > 0.0
