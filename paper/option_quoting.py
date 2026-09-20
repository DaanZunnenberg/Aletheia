from __future__ import annotations

from core.models.options.black76 import OptionType, black76_price
from core.strategies.market_maker import QuoteDecision

_VRP_MULTIPLIER = 1.2  # realised-vol -> "fair" IV; see research/validate_vrp_thesis.py (IV > RV persistently)


def generate_option_quote(
    underlying_price: float,
    time_to_expiry_years: float,
    realized_vol: float,
    strike: float,
    option_type: OptionType,
    half_spread_vol: float = 0.05,
    size: float = 0.1,
) -> QuoteDecision:
    """
    Deliberately simple option quoting for the paper bot: no SVI surface, no
    Greek-based inventory skew, no queue/toxicity gating -- fair vol is just
    realized_vol * a fixed VRP multiplier (this project's own research found
    a persistent IV > RV premium; 1.2x is illustrative, not fit), and the
    quote is a fixed +/- half_spread_vol band in *vol space*, each side
    converted to a price via Black-76. This is the options analogue of the
    perp side's plain Avellaneda-Stoikov quoting: a working first version,
    not the GLFT+regime+toxicity stack core/ already has for perps.

    Returns a market_maker.QuoteDecision so paper/engine.py can treat option
    and perp quotes identically -- the container is generic (bid/ask price/
    size, skip flags, breaches), nothing about it is perp-specific.

    Deribit quotes option premiums BTC/ETH-denominated (inverse contracts),
    not USD, while black76_price() here is a standard USD-denominated
    price. bid_price/ask_price are divided by underlying_price before
    returning -- the common approximate inverse-option conversion
    (premium_coin ~ premium_usd / spot), not an exact quanto/inverse Greeks
    adjustment. Good enough to compare against and trade against the live
    BTC/ETH-denominated book; not accurate enough to trust the resulting
    Greeks without redoing them properly (see core/models/options/black76.py's
    own caveat).
    """
    if time_to_expiry_years <= 0.0 or underlying_price <= 0.0:
        return QuoteDecision(
            bid_price=0.0, ask_price=0.0, bid_size=0.0, ask_size=0.0,
            skip_bid=True, skip_ask=True, breaches=("expired",),
        )

    fair_vol = realized_vol * _VRP_MULTIPLIER
    bid_vol = max(fair_vol - half_spread_vol, 1e-4)
    ask_vol = fair_vol + half_spread_vol

    bid_price_usd = black76_price(underlying_price, strike, time_to_expiry_years, bid_vol, option_type)
    ask_price_usd = black76_price(underlying_price, strike, time_to_expiry_years, ask_vol, option_type)

    return QuoteDecision(
        bid_price=bid_price_usd / underlying_price,
        ask_price=ask_price_usd / underlying_price,
        bid_size=size, ask_size=size,
        skip_bid=False, skip_ask=False, breaches=(),
    )
