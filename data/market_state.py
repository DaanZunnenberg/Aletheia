from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class OptionQuote:
    instrument_name: str
    expiry_ts: int        # unix ms; used to compute T
    strike: float
    option_type: str      # 'call' | 'put'
    mark_price: float     # in index currency (BTC, ETH)
    mark_iv: float        # Deribit mark IV, annualised fraction
    bid_price: float
    ask_price: float
    bid_iv: float | None
    ask_iv: float | None
    delta: float | None
    gamma: float | None
    vega: float | None
    theta: float | None
    open_interest: float


@dataclass
class FutureQuote:
    instrument_name: str
    expiry_ts: int        # unix ms; 0 for perpetuals
    mark_price: float
    index_price: float
    open_interest: float
    current_funding: float | None   # perpetuals only; 8h rate as fraction
    funding_8h: float | None


@dataclass
class MarketState:
    """
    Immutable snapshot of all market data for a single underlying.

    Consumed by every model in the research pipeline. Build via
    data.normalization.build_market_state().
    """
    currency: str                          # 'BTC' | 'ETH' | 'SOL'
    spot_price: float                      # index price
    dvol: float | None                     # Deribit DVOL (30d forward IV, annualised %)
    option_chain: list[OptionQuote] = field(default_factory=list)
    futures_curve: list[FutureQuote] = field(default_factory=list)
    timestamp: float = 0.0                 # unix ms (exchange time of snapshot)

    # ------------------------------------------------------------------
    # Derived convenience properties
    # ------------------------------------------------------------------

    def calls(self, expiry_ts: int | None = None) -> list[OptionQuote]:
        opts = [o for o in self.option_chain if o.option_type == "call"]
        if expiry_ts is not None:
            opts = [o for o in opts if o.expiry_ts == expiry_ts]
        return sorted(opts, key=lambda o: o.strike)

    def puts(self, expiry_ts: int | None = None) -> list[OptionQuote]:
        opts = [o for o in self.option_chain if o.option_type == "put"]
        if expiry_ts is not None:
            opts = [o for o in opts if o.expiry_ts == expiry_ts]
        return sorted(opts, key=lambda o: o.strike)

    def expiries(self) -> list[int]:
        return sorted({o.expiry_ts for o in self.option_chain})

    def perpetual(self) -> FutureQuote | None:
        for f in self.futures_curve:
            if f.expiry_ts == 0:
                return f
        return None

    def forward(self, expiry_ts: int) -> float | None:
        """Return the mark price of the dated future closest to expiry_ts, or None."""
        candidates = [f for f in self.futures_curve if f.expiry_ts == expiry_ts]
        return candidates[0].mark_price if candidates else None
