from __future__ import annotations

from dataclasses import dataclass

from core.models.greeks_aggregator import PortfolioGreeks


@dataclass(frozen=True)
class HardHedgeLimits:
    """Threshold for a hard-band hedge: a discrete, immediate paper trade to flatten delta."""
    max_abs_delta: float = 0.5


def soft_hedge_inventory(perp_position_quantity: float, portfolio_delta_excluding_perp: float) -> float:
    """
    Effective "inventory" for the perp's own AS reservation-price skew
    (core.strategies.market_maker.generate_quotes's inventory_override),
    including delta exposure from every *other* instrument in the book
    (e.g. an option leg) as phantom inventory.

    This is the soft delta band: continuous, self-correcting, never fires a
    trade by itself -- it just makes the perp quote skew a little harder in
    the direction that reduces net portfolio delta, same mechanism AS
    already uses for its own inventory, just fed a broader number. Low
    blast radius if the underlying delta estimate is noisy, unlike a hard
    hedge trade (see should_hard_hedge()).
    """
    return perp_position_quantity + portfolio_delta_excluding_perp


def should_hard_hedge(portfolio_delta: float, limits: HardHedgeLimits) -> tuple[bool, float]:
    """
    Hard delta band: net portfolio delta breaching max_abs_delta triggers an
    immediate flattening trade (the caller executes it -- this function only
    decides whether to and how much).

    Deliberately gated on real fills existing (paper.fill_simulator's
    trade-tape-driven matching, not L2-crossing), per the risk/execution
    debate this followed: firing an irreversible (even paper) trade off a
    delta estimate built on fantasy fills is the "false confidence" failure
    mode a soft, continuous nudge doesn't have.

    Returns (should_hedge, hedge_quantity) -- hedge_quantity is the size and
    sign of perp trade that would flatten portfolio_delta back to exactly 0
    (not just back inside the band, to avoid hedging every single tick once
    near the threshold).
    """
    if abs(portfolio_delta) <= limits.max_abs_delta:
        return False, 0.0
    return True, -portfolio_delta


def portfolio_delta_excluding(components: list[PortfolioGreeks], exclude_index: int) -> float:
    """Sum of .delta across all components except the one at exclude_index (the perp being quoted)."""
    return sum(c.delta for i, c in enumerate(components) if i != exclude_index)
