from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from core.market_state import MarketState
from core.models.greeks_aggregator import (
    PortfolioGreeks,
    aggregate_portfolio,
    option_position_greeks,
    perp_position_greeks,
)
from core.models.options.black76 import OptionType, black76_greeks
from core.models.quoting import QuotingParams
from core.models.volatility import ewma_volatility
from core.risk.limits import RiskLimits
from core.strategies.market_maker import QuoteDecision, generate_quotes
from data.orderbook import OrderBookUpdate
from deribit.types import Trade
from paper.bar_builder import LiveBarAggregator
from paper.dashboard import InstrumentSnapshot
from paper.execution_latency import LatencyModel, is_quote_live
from paper.execution_latency import taker_slippage_price
from paper.fill_simulator import PaperFill
from paper.hedger import HardHedgeLimits, should_hard_hedge, soft_hedge_inventory
from paper.option_quoting import VRP_MULTIPLIER, generate_option_quote
from paper.position_book import PositionBook
from paper.queue_tracker import QueueTracker
from paper.session_log import SessionEvent, SessionLogger
from utils.logger import get_logger

log = get_logger(__name__)

_VOL_HALFLIFE_SECONDS = 60.0
_VOL_WARMUP_UPDATES = 20
_PERP_PARAMS = QuotingParams(gamma=5.0, time_horizon=1.0, kappa=1.5, A=0.05)
_PERP_LIMITS = RiskLimits()
_SECONDS_PER_YEAR = 365.0 * 24.0 * 3600.0


def _instrument_id(key: tuple[str, str, str]) -> str:
    """
    exchange:market_type:symbol -- not just the bare symbol. Binance spot
    and perpetual share the literal symbol "BTCUSDT"; keying positions by
    symbol alone would silently merge two different instruments' fills into
    one Position the moment both were ever quoted.
    """
    return f"{key[0]}:{key[1]}:{key[2]}"


def _size_ahead_at_price(levels: tuple[tuple[float, float], ...], price: float) -> float:
    """Resting size at exactly `price` in a book side -- 0.0 if we'd be a brand-new price level."""
    for level_price, level_size in levels:
        if level_price == price:
            return level_size
    return 0.0


@dataclass
class QuotedPerp:
    key: tuple[str, str, str]  # (exchange, market_type, symbol)
    underlying_ccy: str        # 'BTC' | 'ETH' -- groups instruments sharing a vol estimate


@dataclass
class QuotedOption:
    key: tuple[str, str, str]
    underlying_ccy: str
    underlying_key: tuple[str, str, str]  # which stream's mid is the underlying reference price
    strike: float
    option_type: OptionType
    expiration_timestamp_ms: float


class PaperTradingEngine:
    """
    Dry-run market-making engine. Consumes OrderBookUpdate events (quoting)
    and Trade events (fills), and wires together every layer built for this
    pass: core.strategies.market_maker (perp AS quoting, now with a soft
    delta-hedge inventory override), paper.option_quoting (Black-76 options),
    paper.queue_tracker (FIFO-approximation fills against real trades, not
    L2-crossing), paper.execution_latency (fills gated on the quote actually
    having been live long enough), core.models.greeks_aggregator (portfolio
    Greeks across the option + perp book), paper.hedger (soft continuous
    hedging via the AS skew mechanism, hard threshold-triggered hedging),
    and paper.session_log (every quote/fill/Greeks snapshot/hedge persisted
    to disk). No real orders are ever sent anywhere.

    Reference-only streams (e.g. Binance spot/perp here) are tracked for
    display but not quoted.
    """

    def __init__(
        self,
        quoted_perps: list[QuotedPerp],
        quoted_options: list[QuotedOption],
        reference_keys: list[tuple[str, str, str]],
        session_log_path: Path | None = None,
        latency_model: LatencyModel | None = None,
        hard_hedge_limits: HardHedgeLimits | None = None,
        seed: int = 0,
    ) -> None:
        self._quoted_perps = {q.key: q for q in quoted_perps}
        self._quoted_options = {q.key: q for q in quoted_options}
        self._reference_keys = set(reference_keys)

        self.latest_books: dict[tuple[str, str, str], OrderBookUpdate] = {}
        self.resting_quotes: dict[tuple[str, str, str], QuoteDecision] = {}
        self.position_book = PositionBook()
        self.queue_tracker = QueueTracker()
        self.latency_model = latency_model or LatencyModel()
        self.hard_hedge_limits = hard_hedge_limits or HardHedgeLimits()
        self._rng = np.random.default_rng(seed)
        self._quote_live_at: dict[tuple[str, str, str], float] = {}
        self.session_logger = SessionLogger(session_log_path) if session_log_path is not None else None
        self.portfolio_greeks: dict[str, PortfolioGreeks] = {}

        # Fixed-interval bars, not raw ticks: ewma_volatility() assumes evenly-
        # spaced samples (it scales annualisation by a fixed sampling_seconds),
        # but live book updates arrive irregularly. Feeding raw ticks in
        # silently distorts the vol estimate -- see paper/bar_builder.py.
        self._bar_seconds = 1.0
        self.bars: dict[str, LiveBarAggregator] = {
            q.underlying_ccy: LiveBarAggregator(self._bar_seconds) for q in quoted_perps
        }
        self.start_time = time.time()
        self.n_fills = 0
        self.n_hard_hedges = 0

    def close(self) -> None:
        if self.session_logger is not None:
            self.session_logger.close()

    def _sigma_for(self, currency: str) -> float | None:
        aggregator = self.bars.get(currency)
        if aggregator is None:
            return None
        closes = aggregator.closed_series()
        if len(closes) < _VOL_WARMUP_UPDATES:
            return None
        window = pd.Series(closes[-_VOL_WARMUP_UPDATES * 5:])
        return ewma_volatility(window, _VOL_HALFLIFE_SECONDS, sampling_seconds=self._bar_seconds)

    def _log(self, timestamp: float, event_type: str, instrument: str, data: dict) -> None:
        if self.session_logger is not None:
            self.session_logger.log(SessionEvent(timestamp=timestamp, event_type=event_type, instrument=instrument, data=data))

    # ------------------------------------------------------------------
    # Book updates: quoting
    # ------------------------------------------------------------------

    def on_book_update(self, update: OrderBookUpdate) -> None:
        self.latest_books[update.key] = update

        if update.key in self._quoted_perps:
            self._handle_perp_update(update)
        elif update.key in self._quoted_options:
            self._handle_option_update(update)
        # reference streams: stored above, no quoting/fill logic

    def _register_resting_quote(self, key: tuple[str, str, str], quote: QuoteDecision, update: OrderBookUpdate) -> None:
        instrument = update.symbol
        self.resting_quotes[key] = quote
        self._quote_live_at[key] = self.latency_model.quote_live_at(update.timestamp, self._rng)
        if not quote.skip_bid and quote.bid_size > 0.0:
            self.queue_tracker.place_order(
                instrument, "bid", quote.bid_price, quote.bid_size, _size_ahead_at_price(update.bids, quote.bid_price)
            )
        else:
            self.queue_tracker.clear_order(instrument, "bid")
        if not quote.skip_ask and quote.ask_size > 0.0:
            self.queue_tracker.place_order(
                instrument, "ask", quote.ask_price, quote.ask_size, _size_ahead_at_price(update.asks, quote.ask_price)
            )
        else:
            self.queue_tracker.clear_order(instrument, "ask")
        self._log(update.timestamp / 1000.0, "quote", instrument, {
            "bid": quote.bid_price, "ask": quote.ask_price, "bid_size": quote.bid_size, "ask_size": quote.ask_size,
        })

    def _handle_perp_update(self, update: OrderBookUpdate) -> None:
        spec = self._quoted_perps[update.key]

        self.bars.setdefault(spec.underlying_ccy, LiveBarAggregator(self._bar_seconds)).update(
            update.timestamp / 1000.0, update.mid_price
        )
        sigma = self._sigma_for(spec.underlying_ccy)
        if sigma is None:
            return

        self._refresh_portfolio_greeks(spec.underlying_ccy, update)
        option_delta = self._option_delta_for(spec.underlying_ccy)

        position = self.position_book.position_for(_instrument_id(spec.key))
        effective_inventory = soft_hedge_inventory(position.quantity, option_delta)

        state = MarketState(
            instrument_name=update.symbol,
            best_bid_price=update.best_bid, best_ask_price=update.best_ask,
            best_bid_size=update.bids[0][1] if update.bids else 0.0,
            best_ask_size=update.asks[0][1] if update.asks else 0.0,
            mark_price=update.mid_price, index_price=update.mid_price,
            current_funding=None, timestamp=update.timestamp,
        )
        quote = generate_quotes(
            state, position, sigma, _PERP_PARAMS, _PERP_LIMITS,
            reference_price=update.microprice, inventory_override=effective_inventory,
        )
        self._register_resting_quote(spec.key, quote, update)
        self._maybe_hard_hedge(spec.underlying_ccy, update)

    def _handle_option_update(self, update: OrderBookUpdate) -> None:
        spec = self._quoted_options[update.key]

        underlying_book = self.latest_books.get(spec.underlying_key)
        sigma = self._sigma_for(spec.underlying_ccy)
        if underlying_book is None or sigma is None:
            return

        time_to_expiry = max(
            (spec.expiration_timestamp_ms - update.timestamp) / 1000.0 / _SECONDS_PER_YEAR, 0.0
        )
        quote = generate_option_quote(
            underlying_price=underlying_book.microprice,
            time_to_expiry_years=time_to_expiry,
            realized_vol=sigma,
            strike=spec.strike,
            option_type=spec.option_type,
        )
        self._register_resting_quote(spec.key, quote, update)
        self._refresh_portfolio_greeks(spec.underlying_ccy, update)
        self._maybe_hard_hedge(spec.underlying_ccy, update)

    # ------------------------------------------------------------------
    # Trade updates: fills (trade-tape-driven, queue-position-aware)
    # ------------------------------------------------------------------

    def on_trade(self, trade: Trade) -> None:
        instrument = trade["instrument_name"]
        key = self._key_for_instrument(instrument)
        if key is None:
            return

        now_ms = trade["timestamp"]
        live_at = self._quote_live_at.get(key)
        if live_at is not None and not is_quote_live(live_at, now_ms):
            return  # our quote wasn't actually live in the book yet when this trade printed

        fills = self.queue_tracker.on_trade(instrument, trade["price"], trade["amount"])
        for side, filled_size in fills:
            quote = self.resting_quotes.get(key)
            if quote is None:
                continue
            price = quote.bid_price if side == "bid" else quote.ask_price
            self.position_book.apply_fill(
                _instrument_id(key), now_ms / 1000.0, PaperFill(side=side, price=price, size=filled_size),
            )
            self.n_fills += 1
            self._log(now_ms / 1000.0, "fill", instrument, {"side": side, "price": price, "size": filled_size})
            log.info("FILL  %-22s %s %.6g @ %.6g (queue/trade-tape)", instrument, side, filled_size, price)

    def _key_for_instrument(self, instrument: str) -> tuple[str, str, str] | None:
        for key in self._quoted_perps:
            if key[2] == instrument:
                return key
        for key in self._quoted_options:
            if key[2] == instrument:
                return key
        return None

    # ------------------------------------------------------------------
    # Portfolio Greeks + hedging
    # ------------------------------------------------------------------

    def _current_option_greeks(self, spec: QuotedOption):
        underlying_book = self.latest_books.get(spec.underlying_key)
        sigma = self._sigma_for(spec.underlying_ccy)
        option_book = self.latest_books.get(spec.key)
        if underlying_book is None or sigma is None or option_book is None:
            return None
        time_to_expiry = max(
            (spec.expiration_timestamp_ms - option_book.timestamp) / 1000.0 / _SECONDS_PER_YEAR, 1e-6
        )
        # EWMA vol can be exactly 0.0 on a run of bit-identical bar closes (a
        # real degenerate case, not just theoretical -- hit this live), and
        # black76_greeks divides by sigma. Floor it, same convention
        # option_quoting.py already uses for its own bid-side vol.
        fair_vol = max(sigma * VRP_MULTIPLIER, 1e-4)
        return black76_greeks(underlying_book.microprice, spec.strike, time_to_expiry, fair_vol, spec.option_type)

    def _option_delta_for(self, currency: str) -> float:
        total = 0.0
        for spec in self._quoted_options.values():
            if spec.underlying_ccy != currency:
                continue
            greeks = self._current_option_greeks(spec)
            if greeks is None:
                continue
            position = self.position_book.position_for(_instrument_id(spec.key))
            total += option_position_greeks(position.quantity, greeks).delta
        return total

    def _refresh_portfolio_greeks(self, currency: str, update: OrderBookUpdate) -> None:
        components = []
        for spec in self._quoted_perps.values():
            if spec.underlying_ccy != currency:
                continue
            position = self.position_book.position_for(_instrument_id(spec.key))
            components.append(perp_position_greeks(position.quantity))
        for spec in self._quoted_options.values():
            if spec.underlying_ccy != currency:
                continue
            greeks = self._current_option_greeks(spec)
            if greeks is None:
                continue
            position = self.position_book.position_for(_instrument_id(spec.key))
            components.append(option_position_greeks(position.quantity, greeks))

        total = aggregate_portfolio(components)
        self.portfolio_greeks[currency] = total
        self._log(update.timestamp / 1000.0, "greeks", currency, {
            "delta": total.delta, "gamma": total.gamma, "vega": total.vega,
            "theta": total.theta, "vanna": total.vanna, "volga": total.volga, "charm": total.charm,
        })

    def _maybe_hard_hedge(self, currency: str, update: OrderBookUpdate) -> None:
        total = self.portfolio_greeks.get(currency)
        if total is None:
            return
        should, hedge_qty = should_hard_hedge(total.delta, self.hard_hedge_limits)
        if not should:
            return

        perp_key = next((k for k, s in self._quoted_perps.items() if s.underlying_ccy == currency), None)
        if perp_key is None:
            return
        perp_book = self.latest_books.get(perp_key)
        if perp_book is None:
            return

        side = "buy" if hedge_qty > 0 else "sell"
        depth = perp_book.bids[0][1] if side == "sell" else (perp_book.asks[0][1] if perp_book.asks else 1.0)
        exec_price = taker_slippage_price(perp_book.mid_price, side, abs(hedge_qty), depth)

        fill = PaperFill(side="bid" if hedge_qty > 0 else "ask", price=exec_price, size=abs(hedge_qty))
        self.position_book.apply_fill(_instrument_id(perp_key), update.timestamp / 1000.0, fill)
        self.n_hard_hedges += 1
        self._log(update.timestamp / 1000.0, "hedge", perp_book.symbol, {
            "reason": "hard_delta_band", "portfolio_delta_before": total.delta, "hedge_qty": hedge_qty, "exec_price": exec_price,
        })
        log.warning(
            "HARD HEDGE  %s  delta=%.4f breached %.4f -> %s %.4f @ %.4f",
            currency, total.delta, self.hard_hedge_limits.max_abs_delta, side, abs(hedge_qty), exec_price,
        )

    def snapshot(self) -> list[InstrumentSnapshot]:
        rows = []
        for key, update in self.latest_books.items():
            exchange, market_type, symbol = key
            quote = self.resting_quotes.get(key)
            if key in self._quoted_perps:
                kind, pnl_ccy, mark = "perp-quoted", "USD", update.mid_price
            elif key in self._quoted_options:
                spec = self._quoted_options[key]
                mark = update.mid_price  # coin-denominated, matches Position's price units for this instrument
                kind, pnl_ccy = "option-quoted", spec.underlying_ccy
            else:
                kind, pnl_ccy, mark = f"reference-{market_type}", "USD", update.mid_price

            instrument_id = _instrument_id(key)
            position = self.position_book.position_for(instrument_id)
            rows.append(
                InstrumentSnapshot(
                    instrument=symbol, exchange=exchange, kind=kind, mid=update.mid_price,
                    our_bid=quote.bid_price if quote else None, our_ask=quote.ask_price if quote else None,
                    position_qty=position.quantity,
                    unrealized_pnl=position.unrealized_pnl_usd(mark),
                    pnl_ccy=pnl_ccy,
                    n_fills=sum(1 for _, sym, _ in self.position_book.fill_log if sym == instrument_id),
                )
            )
        return rows
