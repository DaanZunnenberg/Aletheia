from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from collections import deque
from pathlib import Path

import numpy as np
import pandas as pd

from core.models.greeks_aggregator import (
    PortfolioGreeks,
    aggregate_portfolio,
    option_position_greeks,
    perp_position_greeks,
)
from core.models.glft import GLFTParams
from core.models.ladder import LadderParams, LadderQuoteDecision, generate_ladder_quotes
from core.models.options.black76 import OptionType, black76_greeks, black76_price
from core.models.regime_monitor import RegimeState, classify_trend_regime, classify_vol_regime
from core.models.volatility import ema_drift, ewma_volatility
from core.risk.limits import RiskLimits
from core.strategies.market_maker import QuoteDecision
from data.orderbook import OrderBookUpdate
from deribit.types import Trade
from paper.bar_builder import LiveBarAggregator
from paper.dashboard import BlotterRow, InstrumentSnapshot, RiskSnapshot
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

_VOL_HALFLIFE_SECONDS = 60.0        # "HFT" fast vol estimate -- reacts within seconds
_VOL_WARMUP_UPDATES = 20            # bars before the fast estimate is trusted at all
_SLOW_HALFLIFE_SECONDS = 600.0      # "macro" slow vol estimate -- 10 min halflife
_DRIFT_HALFLIFE_SECONDS = 900.0     # macro trend EMA -- 15 min halflife
_REGIME_WARMUP_BARS = 300           # bars before the slow/macro regime axis is trusted (5 min at 1s bars) --
                                     # a 600s-halflife EWMA computed from 20s of data is meaningless noise, not a baseline
_PERP_GLFT_PARAMS = GLFTParams(gamma=5.0, kappa=1.5, A=0.05, q_max=1.0)
_PERP_LADDER_PARAMS = LadderParams(n_levels=3, intensity_decay_per_level=0.5, size_decay_per_level=0.6)
_PERP_LIMITS = RiskLimits()
_SECONDS_PER_YEAR = 365.0 * 24.0 * 3600.0
_OB_DEPTH_LEVELS_SHOWN = 5  # top-of-book depth surfaced to the dashboard, real exchange liquidity (not our own quotes)

# Illustrative Deribit-like fee schedule (bps of notional). Resting-quote
# fills via the trade-tape/queue tracker are maker (we provided the
# liquidity that got hit); hard-hedge fills cross the book, so they're
# taker. Not pulled from a live fee-tier API -- flat, conservative estimate.
_MAKER_FEE_BPS = 0.0
_TAKER_FEE_BPS = 5.0


def _instrument_id(key: tuple[str, str, str]) -> str:
    """
    exchange:market_type:symbol -- not just the bare symbol. Binance spot
    and perpetual share the literal symbol "BTCUSDT"; keying positions by
    symbol alone would silently merge two different instruments' fills into
    one Position the moment both were ever quoted.
    """
    return f"{key[0]}:{key[1]}:{key[2]}"


def _blotter_row(timestamp: float, instrument: str, event_type: str, data: dict) -> BlotterRow:
    """Maps a logged event's raw data dict onto the blotter's fixed column schema."""
    if event_type == "quote":
        book_bid, book_ask = data["book_bid"], data["book_ask"]
        book_bid_size, book_ask_size = data["book_bid_size"], data["book_ask_size"]
        if "bid_levels" in data:  # ladder (perp)
            bids, asks = data["bid_levels"], data["ask_levels"]
            our_bid = bids[0][0] if bids else None
            our_ask = asks[0][0] if asks else None
            note = f"{len(bids)}lvl bidsz={bids[0][1]:.4f} asksz={asks[0][1]:.4f}" if bids and asks else "skip"
        else:
            our_bid, our_ask = data["bid"], data["ask"]
            note = f"bidsz={data['bid_size']:.4f} asksz={data['ask_size']:.4f}"
        return BlotterRow(
            timestamp, instrument, event_type, book_bid=book_bid, book_ask=book_ask,
            book_bid_size=book_bid_size, book_ask_size=book_ask_size, our_bid=our_bid, our_ask=our_ask, note=note,
        )
    if event_type == "fill":
        return BlotterRow(
            timestamp, instrument, event_type, side=data["side"], price=data["price"], size=data["size"],
            fee=data.get("fee"), slippage=data.get("slippage"), note=f"L{data['level']}",
        )
    if event_type == "hedge":
        side = "buy" if data["hedge_qty"] > 0 else "sell"
        return BlotterRow(
            timestamp, instrument, event_type, side=side, price=data["exec_price"], size=abs(data["hedge_qty"]),
            fee=data.get("fee"), slippage=data.get("slippage"),
            note=f"delta {data['portfolio_delta_before']:+.4f}->band",
        )
    return BlotterRow(timestamp, instrument, event_type, note=str(data))


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
    and Trade events (fills), and wires together every layer built so far:
    perps quote a multi-level GLFT ladder (core.models.ladder, level spacing
    tied to kappa, sizes decaying geometrically -- see LadderParams), with a
    soft delta-hedge inventory override; options quote a single Black-76
    level (paper.option_quoting). Both flow through paper.queue_tracker
    (FIFO-approximation fills against real trades, not L2-crossing) and
    paper.execution_latency (fills gated on the quote actually having been
    live long enough). core.models.greeks_aggregator aggregates portfolio
    Greeks across the option + perp book; paper.hedger drives soft
    (continuous, via the ladder's own skew) and hard (threshold-triggered)
    hedging. Every quote/fill/Greeks snapshot/hedge is persisted via
    paper.session_log. No real orders are ever sent anywhere.

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
        self.resting_quotes: dict[tuple[str, str, str], QuoteDecision] = {}      # options: single level
        self.resting_ladders: dict[tuple[str, str, str], LadderQuoteDecision] = {}  # perps: multi-level
        self.position_book = PositionBook()
        self.queue_tracker = QueueTracker()
        self.latency_model = latency_model or LatencyModel()
        self.hard_hedge_limits = hard_hedge_limits or HardHedgeLimits()
        self._rng = np.random.default_rng(seed)
        self._quote_live_at: dict[tuple[str, str, str], float] = {}
        self.session_logger = SessionLogger(session_log_path) if session_log_path is not None else None
        self.portfolio_greeks: dict[str, PortfolioGreeks] = {}
        self.regimes: dict[str, RegimeState] = {}

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
        self.event_log: deque[BlotterRow] = deque(maxlen=500)  # dashboard tape, one fixed-schema row per event
        self.update_event = asyncio.Event()  # set on every book/trade update so the dashboard can render live, not on a timer

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

    def warmup_status(self, currency: str) -> tuple[str, int, int, float]:
        """
        (stage, bars_collected, bars_needed, eta_seconds) -- what's still
        warming up and roughly how long until it's ready, for dashboard
        display. Two stages: 'fast_vol' (the AS/GLFT quoting input, ready
        after _VOL_WARMUP_UPDATES bars) then 'regime' (the slow/macro axis,
        needs _REGIME_WARMUP_BARS -- far more history, since a 600s-halflife
        EWMA computed from 20s of data is meaningless). 'ready' once both
        have enough bars.
        """
        collected = len(self.bars[currency].closed_series()) if currency in self.bars else 0
        if collected < _VOL_WARMUP_UPDATES:
            needed = _VOL_WARMUP_UPDATES
            return "fast_vol", collected, needed, (needed - collected) * self._bar_seconds
        if collected < _REGIME_WARMUP_BARS:
            needed = _REGIME_WARMUP_BARS
            return "regime", collected, needed, (needed - collected) * self._bar_seconds
        return "ready", collected, _REGIME_WARMUP_BARS, 0.0

    def _regime_for(self, currency: str) -> RegimeState | None:
        aggregator = self.bars.get(currency)
        if aggregator is None:
            return None
        closes = aggregator.closed_series()
        if len(closes) < _REGIME_WARMUP_BARS:
            return None

        window = pd.Series(closes[-_REGIME_WARMUP_BARS * 3:])
        sigma_fast = ewma_volatility(window, _VOL_HALFLIFE_SECONDS, sampling_seconds=self._bar_seconds)
        sigma_slow = ewma_volatility(window, _SLOW_HALFLIFE_SECONDS, sampling_seconds=self._bar_seconds)
        drift = ema_drift(window, _DRIFT_HALFLIFE_SECONDS, sampling_seconds=self._bar_seconds)

        state = RegimeState(
            vol_regime=classify_vol_regime(sigma_fast, sigma_slow),
            trend_regime=classify_trend_regime(drift),
            sigma_fast=sigma_fast, sigma_slow=sigma_slow, drift=drift,
        )
        self.regimes[currency] = state
        return state

    def _log(self, timestamp: float, event_type: str, instrument: str, data: dict) -> None:
        if self.session_logger is not None:
            self.session_logger.log(SessionEvent(timestamp=timestamp, event_type=event_type, instrument=instrument, data=data))
        # greeks/regime are continuously-updated *state*, not discrete order/market
        # events -- they belong in the dashboard's header (always current), not
        # repeated on every tick in the tape, or they'd drown out real events.
        if event_type not in ("greeks", "regime"):
            self.event_log.append(_blotter_row(timestamp, instrument, event_type, data))

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
        self.update_event.set()

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
            "book_bid": update.bids[0][0] if update.bids else None, "book_ask": update.asks[0][0] if update.asks else None,
            "book_bid_size": update.bids[0][1] if update.bids else None, "book_ask_size": update.asks[0][1] if update.asks else None,
        })

    def _register_resting_ladder(self, key: tuple[str, str, str], ladder: LadderQuoteDecision, update: OrderBookUpdate) -> None:
        instrument = update.symbol
        self.resting_ladders[key] = ladder
        self._quote_live_at[key] = self.latency_model.quote_live_at(update.timestamp, self._rng)

        for i, level in enumerate(ladder.bid_levels):
            if not ladder.skip_bid and level.size > 0.0:
                self.queue_tracker.place_order(
                    instrument, "bid", level.price, level.size, _size_ahead_at_price(update.bids, level.price), level=i
                )
            else:
                self.queue_tracker.clear_order(instrument, "bid", level=i)
        for i, level in enumerate(ladder.ask_levels):
            if not ladder.skip_ask and level.size > 0.0:
                self.queue_tracker.place_order(
                    instrument, "ask", level.price, level.size, _size_ahead_at_price(update.asks, level.price), level=i
                )
            else:
                self.queue_tracker.clear_order(instrument, "ask", level=i)

        self._log(update.timestamp / 1000.0, "quote", instrument, {
            "bid_levels": [(lvl.price, lvl.size) for lvl in ladder.bid_levels],
            "ask_levels": [(lvl.price, lvl.size) for lvl in ladder.ask_levels],
            "book_bid": update.bids[0][0] if update.bids else None, "book_ask": update.asks[0][0] if update.asks else None,
            "book_bid_size": update.bids[0][1] if update.bids else None, "book_ask_size": update.asks[0][1] if update.asks else None,
        })

    def _handle_perp_update(self, update: OrderBookUpdate) -> None:
        spec = self._quoted_perps[update.key]

        self.bars.setdefault(spec.underlying_ccy, LiveBarAggregator(self._bar_seconds)).update(
            update.timestamp / 1000.0, update.mid_price
        )
        sigma = self._sigma_for(spec.underlying_ccy)
        if sigma is None:
            return

        regime = self._regime_for(spec.underlying_ccy)
        if regime is not None:
            self._log(update.timestamp / 1000.0, "regime", spec.underlying_ccy, {
                "vol_regime": regime.vol_regime, "trend_regime": regime.trend_regime,
                "sigma_fast": regime.sigma_fast, "sigma_slow": regime.sigma_slow, "drift": regime.drift,
            })

        self._refresh_portfolio_greeks(spec.underlying_ccy, update)
        option_delta = self._option_delta_for(spec.underlying_ccy)

        position = self.position_book.position_for(_instrument_id(spec.key))
        effective_inventory = soft_hedge_inventory(position.quantity, option_delta)

        ladder = generate_ladder_quotes(
            update.mid_price, position, update.mid_price, sigma, _PERP_GLFT_PARAMS, _PERP_LADDER_PARAMS, _PERP_LIMITS,
            reference_price=update.microprice, inventory_override=effective_inventory,
        )
        self._register_resting_ladder(spec.key, ladder, update)
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
        for side, level, filled_size in fills:
            price = self._resting_price_at(key, side, level)
            if price is None:
                continue
            self.position_book.apply_fill(
                _instrument_id(key), now_ms / 1000.0, PaperFill(side=side, price=price, size=filled_size),
            )
            # Maker fill: we were the resting order, filled exactly at our quoted
            # price -- no execution slippage, just the (typically zero/rebate) maker fee.
            fee = price * filled_size * _MAKER_FEE_BPS / 1e4
            if fee != 0.0:
                self.position_book.position_for(_instrument_id(key)).apply_fee(fee)
            self.n_fills += 1
            self._log(now_ms / 1000.0, "fill", instrument, {
                "side": side, "level": level, "price": price, "size": filled_size, "fee": fee, "slippage": 0.0,
            })
            self.update_event.set()
            log.info("FILL  %-22s %s L%d %.6g @ %.6g (queue/trade-tape)", instrument, side, level, filled_size, price)

    def _resting_price_at(self, key: tuple[str, str, str], side: str, level: int) -> float | None:
        """Price of a specific (side, level) quote -- ladder levels for a perp, or the single option quote (level 0)."""
        ladder = self.resting_ladders.get(key)
        if ladder is not None:
            levels = ladder.bid_levels if side == "bid" else ladder.ask_levels
            return levels[level].price if level < len(levels) else None
        quote = self.resting_quotes.get(key)
        if quote is not None:
            return quote.bid_price if side == "bid" else quote.ask_price
        return None

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
        position = self.position_book.position_for(_instrument_id(perp_key))
        self.position_book.apply_fill(_instrument_id(perp_key), update.timestamp / 1000.0, fill)
        # Taker fill: crosses the book, so it pays the taker fee and eats the
        # slippage taker_slippage_price() already walked into exec_price.
        fee = exec_price * abs(hedge_qty) * _TAKER_FEE_BPS / 1e4
        slippage = exec_price - perp_book.mid_price
        position.apply_fee(fee)
        self.n_hard_hedges += 1
        self._log(update.timestamp / 1000.0, "hedge", perp_book.symbol, {
            "reason": "hard_delta_band", "portfolio_delta_before": total.delta, "hedge_qty": hedge_qty,
            "exec_price": exec_price, "fee": fee, "slippage": slippage,
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
            ladder = self.resting_ladders.get(key)
            bid_levels = ask_levels = None
            if key in self._quoted_perps:
                kind, pnl_ccy, mark = "perp-quoted", "USD", update.mid_price
                our_bid = ladder.bid_levels[0].price if ladder and ladder.bid_levels else None
                our_ask = ladder.ask_levels[0].price if ladder and ladder.ask_levels else None
                if ladder is not None:
                    bid_levels = tuple((lvl.price, lvl.size) for lvl in ladder.bid_levels)
                    ask_levels = tuple((lvl.price, lvl.size) for lvl in ladder.ask_levels)
            elif key in self._quoted_options:
                spec = self._quoted_options[key]
                mark = update.mid_price  # coin-denominated, matches Position's price units for this instrument
                kind, pnl_ccy = "option-quoted", spec.underlying_ccy
                our_bid = quote.bid_price if quote else None
                our_ask = quote.ask_price if quote else None
            else:
                kind, pnl_ccy, mark = f"reference-{market_type}", "USD", update.mid_price
                our_bid = our_ask = None

            instrument_id = _instrument_id(key)
            position = self.position_book.position_for(instrument_id)
            underlying_ccy = self._quoted_perps.get(key, self._quoted_options.get(key)).underlying_ccy \
                if key in self._quoted_perps or key in self._quoted_options else None

            realized_vol = fair_vol = theo_price = None
            if key in self._quoted_options:
                spec = self._quoted_options[key]
                sigma = self._sigma_for(spec.underlying_ccy)
                underlying_book = self.latest_books.get(spec.underlying_key)
                if sigma is not None and underlying_book is not None:
                    realized_vol = sigma
                    fair_vol = sigma * VRP_MULTIPLIER
                    time_to_expiry = max((spec.expiration_timestamp_ms - update.timestamp) / 1000.0 / _SECONDS_PER_YEAR, 1e-6)
                    theo_price = black76_price(
                        underlying_book.microprice, spec.strike, time_to_expiry, fair_vol, spec.option_type,
                    ) / underlying_book.microprice  # coin-denominated, comparable to `mid`

            rows.append(
                InstrumentSnapshot(
                    instrument=symbol, exchange=exchange, kind=kind, mid=update.mid_price,
                    our_bid=our_bid, our_ask=our_ask,
                    position_qty=position.quantity,
                    unrealized_pnl=position.unrealized_pnl_usd(mark),
                    pnl_ccy=pnl_ccy,
                    n_fills=sum(1 for _, sym, _ in self.position_book.fill_log if sym == instrument_id),
                    bid_levels=bid_levels, ask_levels=ask_levels,
                    best_bid_size=update.bids[0][1] if update.bids else None,
                    best_ask_size=update.asks[0][1] if update.asks else None,
                    sigma=self._sigma_for(underlying_ccy) if underlying_ccy else None,
                    book_bids=update.bids[:_OB_DEPTH_LEVELS_SHOWN],
                    book_asks=update.asks[:_OB_DEPTH_LEVELS_SHOWN],
                    realized_vol=realized_vol, fair_vol=fair_vol, theo_price=theo_price,
                )
            )
        return rows

    def warmup_statuses(self) -> dict[str, tuple[str, int, int, float]]:
        currencies = {q.underlying_ccy for q in self._quoted_perps.values()}
        return {ccy: self.warmup_status(ccy) for ccy in currencies}

    def risk_snapshots(self) -> dict[str, RiskSnapshot]:
        """Per-currency exposure against core.risk.limits.RiskLimits and the hard-hedge delta band -- for the dashboard, not a trading decision."""
        snapshots = {}
        for spec in self._quoted_perps.values():
            ccy = spec.underlying_ccy
            update = self.latest_books.get(spec.key)
            if update is None:
                continue
            position = self.position_book.position_for(_instrument_id(spec.key))
            gross_notional = abs(position.quantity) * update.mid_price
            delta = self.portfolio_greeks.get(ccy)
            snapshots[ccy] = RiskSnapshot(
                position=position.quantity, max_position=_PERP_LIMITS.max_position,
                gross_notional_usd=gross_notional, max_gross_notional_usd=_PERP_LIMITS.max_gross_notional_usd,
                daily_loss_usd=-min(0.0, position.net_pnl_usd(update.mid_price)),
                max_daily_loss_usd=_PERP_LIMITS.max_daily_loss_usd,
                portfolio_delta=delta.delta if delta else 0.0,
                max_abs_delta=self.hard_hedge_limits.max_abs_delta,
            )
        return snapshots
