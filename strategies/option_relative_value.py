from __future__ import annotations

from dataclasses import dataclass

from data.market_state import MarketState
from signals.distribution_arbitrage import DistributionSignal, Direction
from risk.limits import RiskLimits
from risk.greeks import GreekExposure


@dataclass
class TradeDecision:
    expiry_ts: int
    action: str                   # human-readable description
    direction: Direction
    size_vega: float              # target net vega in USD
    max_delta: float              # delta to hedge; expressed as fraction of notional
    signal_strength: float
    signal_confidence: float
    blocked: bool = False
    block_reason: str = ""


def generate_decision(
    signal: DistributionSignal,
    state: MarketState,
    exposure: GreekExposure,
    limits: RiskLimits,
) -> TradeDecision:
    """
    Translate a DistributionSignal into a TradeDecision subject to risk limits.

    Sizing: vega target scales linearly with signal strength, capped at
    limits.max_vega_usd. Delta from the option trade is assumed to be hedged
    immediately with the perpetual.

    Returns a TradeDecision with blocked=True if limits would be breached.
    """
    if signal.direction == Direction.NEUTRAL or signal.strength < 0.05:
        return TradeDecision(
            expiry_ts=signal.expiry_ts,
            action="No signal",
            direction=Direction.NEUTRAL,
            size_vega=0.0,
            max_delta=0.0,
            signal_strength=signal.strength,
            signal_confidence=signal.confidence,
            blocked=True,
            block_reason="Signal below threshold",
        )

    target_vega = min(
        signal.strength * signal.confidence * limits.max_vega_usd,
        limits.max_vega_usd,
    )

    # Block if adding this vega would breach the gross vega limit
    projected_vega = abs(exposure.net_vega_usd) + target_vega
    if projected_vega > limits.max_vega_usd:
        return TradeDecision(
            expiry_ts=signal.expiry_ts,
            action=signal.suggested_trade,
            direction=signal.direction,
            size_vega=target_vega,
            max_delta=0.0,
            signal_strength=signal.strength,
            signal_confidence=signal.confidence,
            blocked=True,
            block_reason=f"Gross vega limit: {projected_vega:.0f} > {limits.max_vega_usd:.0f}",
        )

    return TradeDecision(
        expiry_ts=signal.expiry_ts,
        action=signal.suggested_trade,
        direction=signal.direction,
        size_vega=target_vega,
        max_delta=0.02,   # hedge delta to within 2% of notional
        signal_strength=signal.strength,
        signal_confidence=signal.confidence,
    )
