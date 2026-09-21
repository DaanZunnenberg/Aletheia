from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class LatencyModel:
    """
    Network + matching-engine latency between "we decide to quote" and "the
    exchange's book actually reflects it." Without this, paper fills are
    instant and exact-price -- a resting quote is treated as live in the
    book the moment we compute it, which no real system achieves.

    base_ms  : fixed round-trip latency floor.
    jitter_ms: extra latency drawn from an exponential distribution (heavier
               tail than uniform -- occasional slow round trips are common,
               a bounded uniform jitter understates that).
    """
    base_ms: float = 50.0
    jitter_ms: float = 30.0

    def sample_latency_ms(self, rng: np.random.Generator) -> float:
        return self.base_ms + rng.exponential(self.jitter_ms)

    def quote_live_at(self, decision_timestamp_ms: float, rng: np.random.Generator) -> float:
        """The timestamp at which a quote decided at decision_timestamp_ms actually becomes live."""
        return decision_timestamp_ms + self.sample_latency_ms(rng)


def is_quote_live(quote_live_at_ms: float, now_ms: float) -> bool:
    """
    A trade at now_ms can only fill a quote that was actually live in the
    book by then. Without this, a trade occurring in the latency gap
    (decided-but-not-yet-live) could "fill" an order the exchange never
    actually saw yet -- an unrealistically fast reaction to information we
    hadn't acted on.
    """
    return now_ms >= quote_live_at_ms


def taker_slippage_price(
    mid_price: float, side: str, size: float, depth_estimate: float, impact_bps_per_unit: float = 2.0,
) -> float:
    """
    Execution price for an immediate (IOC/market) taker order -- used for
    hard-band hedge execution, not passive maker quotes. Linear temporary-
    impact model: price moves impact_bps_per_unit basis points per unit of
    size relative to depth_estimate (resting size near touch), in the
    direction that costs the taker (buy -> pay up, sell -> receive less).

    Deliberately a crude placeholder, not a calibrated Almgren-Chriss model
    -- there's no real fill data yet to calibrate impact against (same
    caveat market_impact.py and smart_order_router.py inherit).
    """
    if side not in ("buy", "sell"):
        raise ValueError(f"side must be 'buy' or 'sell', got {side!r}")
    if depth_estimate <= 0.0:
        relative_size = 1.0  # no depth reference -- assume maximal impact rather than divide by zero
    else:
        relative_size = size / depth_estimate

    impact_bps = impact_bps_per_unit * relative_size
    direction = 1.0 if side == "buy" else -1.0
    return mid_price * (1.0 + direction * impact_bps / 1e4)
