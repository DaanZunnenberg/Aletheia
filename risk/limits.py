from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RiskLimits:
    """
    Hard position limits for the options portfolio.

    All USD values are in USD notional. These are checked by the strategy layer
    before generating a TradeDecision. Breach → decision is blocked, not sized down.
    """
    max_vega_usd: float = 10_000.0     # gross vega exposure cap
    max_delta_usd: float = 50_000.0    # net delta cap (residual after hedge)
    max_gamma_usd: float = 5_000.0     # net gamma cap
    max_notional_usd: float = 500_000.0  # total gross option notional

    @classmethod
    def conservative(cls) -> RiskLimits:
        return cls(
            max_vega_usd=2_000.0,
            max_delta_usd=10_000.0,
            max_gamma_usd=1_000.0,
            max_notional_usd=100_000.0,
        )
