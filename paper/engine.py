from __future__ import annotations

import time
from dataclasses import dataclass, field

import pandas as pd

from core.market_state import MarketState
from core.models.options.black76 import OptionType
from core.models.quoting import QuotingParams
from core.models.volatility import ewma_volatility
from core.risk.limits import RiskLimits
from core.strategies.market_maker import QuoteDecision, generate_quotes
from data.orderbook import OrderBookUpdate
from paper.dashboard import InstrumentSnapshot
from paper.fill_simulator import check_fill
from paper.option_quoting import generate_option_quote
from paper.position_book import PositionBook
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
    Dry-run market-making engine: consumes OrderBookUpdate events (from
    exchanges.stream_manager.MultiExchangeStreamManager), quotes perps via
    core.strategies.market_maker (Avellaneda-Stoikov) and options via
    paper.option_quoting (Black-76 off realized vol), simulates fills by
    crossing (paper.fill_simulator), and tracks P&L per instrument
    (paper.position_book). No orders are ever sent anywhere.

    Reference-only streams (e.g. Binance spot/perp here) are tracked for
    display and future cross-venue hedging but are not quoted.
    """

    def __init__(
        self,
        quoted_perps: list[QuotedPerp],
        quoted_options: list[QuotedOption],
        reference_keys: list[tuple[str, str, str]],
    ) -> None:
        self._quoted_perps = {q.key: q for q in quoted_perps}
        self._quoted_options = {q.key: q for q in quoted_options}
        self._reference_keys = set(reference_keys)

        self.latest_books: dict[tuple[str, str, str], OrderBookUpdate] = {}
        self.resting_quotes: dict[tuple[str, str, str], QuoteDecision] = {}
        self.position_book = PositionBook()
        self.mid_history: dict[str, list[float]] = {q.underlying_ccy: [] for q in quoted_perps}
        self.start_time = time.time()
        self.n_fills = 0

    def _sigma_for(self, currency: str) -> float | None:
        history = self.mid_history.get(currency, [])
        if len(history) < _VOL_WARMUP_UPDATES:
            return None
        window = pd.Series(history[-_VOL_WARMUP_UPDATES * 5:])
        return ewma_volatility(window, _VOL_HALFLIFE_SECONDS, sampling_seconds=1.0)

    def on_book_update(self, update: OrderBookUpdate) -> None:
        self.latest_books[update.key] = update

        if update.key in self._quoted_perps:
            self._handle_perp_update(update)
        elif update.key in self._quoted_options:
            self._handle_option_update(update)
        # reference streams: stored above, no quoting/fill logic

    def _apply_fills(self, key: tuple[str, str, str], quote: QuoteDecision, update: OrderBookUpdate) -> None:
        instrument_id = _instrument_id(key)
        for fill in check_fill(quote, update):
            self.position_book.apply_fill(instrument_id, update.timestamp / 1000.0, fill)
            self.n_fills += 1
            log.info("FILL  %-22s %s %.6g @ %.6g", update.symbol, fill.side, fill.size, fill.price)

    def _handle_perp_update(self, update: OrderBookUpdate) -> None:
        spec = self._quoted_perps[update.key]
        if spec.key in self.resting_quotes:
            self._apply_fills(spec.key, self.resting_quotes[spec.key], update)

        self.mid_history.setdefault(spec.underlying_ccy, []).append(update.mid_price)
        sigma = self._sigma_for(spec.underlying_ccy)
        if sigma is None:
            return

        state = MarketState(
            instrument_name=update.symbol,
            best_bid_price=update.best_bid, best_ask_price=update.best_ask,
            best_bid_size=update.bids[0][1] if update.bids else 0.0,
            best_ask_size=update.asks[0][1] if update.asks else 0.0,
            mark_price=update.mid_price, index_price=update.mid_price,
            current_funding=None, timestamp=update.timestamp,
        )
        position = self.position_book.position_for(_instrument_id(spec.key))
        self.resting_quotes[spec.key] = generate_quotes(state, position, sigma, _PERP_PARAMS, _PERP_LIMITS)

    def _handle_option_update(self, update: OrderBookUpdate) -> None:
        spec = self._quoted_options[update.key]
        if spec.key in self.resting_quotes:
            self._apply_fills(spec.key, self.resting_quotes[spec.key], update)

        underlying_book = self.latest_books.get(spec.underlying_key)
        sigma = self._sigma_for(spec.underlying_ccy)
        if underlying_book is None or sigma is None:
            return

        time_to_expiry = max(
            (spec.expiration_timestamp_ms - update.timestamp) / 1000.0 / _SECONDS_PER_YEAR, 0.0
        )
        self.resting_quotes[spec.key] = generate_option_quote(
            underlying_price=underlying_book.mid_price,
            time_to_expiry_years=time_to_expiry,
            realized_vol=sigma,
            strike=spec.strike,
            option_type=spec.option_type,
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
