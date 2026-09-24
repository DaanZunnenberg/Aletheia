from __future__ import annotations

from core.models.options.black76 import OptionType, black76_price
from core.models.options.surface_quoting import quote_from_surface
from core.models.options.svi import SVIParams
from core.risk.pin_risk import PinRiskParams, pin_risk_size_multiplier
from core.strategies.market_maker import QuoteDecision

VRP_MULTIPLIER = 1.2  # realised-vol -> "fair" IV; see research/validate_vrp_thesis.py (IV > RV persistently)


def generate_option_quote(
    underlying_price: float,
    time_to_expiry_years: float,
    realized_vol: float,
    strike: float,
    option_type: OptionType,
    half_spread_vol: float = 0.05,
    size: float = 0.1,
    pin_risk_params: PinRiskParams = PinRiskParams(),
    svi_params: SVIParams | None = None,
) -> QuoteDecision:
    """
    Option quoting for the paper bot: no Greek-based inventory skew (that
    lives in the engine's soft-hedge inventory_override on the *perp* side,
    not here), no toxicity gating.

    Fair vol comes from one of two sources:
    - svi_params given (core.models.options.surface_quoting.fit_smile(),
      calibrated from a live multi-strike cross-section -- see
      ccxt_stream/select_option.py's multi-strike selection): fair vol is
      the smile's own IV at *this* strike, so a downside put quotes off
      that wing's actual skew instead of the same flat number as an ATM
      call.
    - svi_params is None (not enough live strikes to fit a smile yet, or
      this project's original single-strike-per-expiry convention): falls
      back to the original flat realized_vol * VRP_MULTIPLIER (this
      project's own research found a persistent IV > RV premium; 1.2x is
      illustrative, not fit).

    Either way the quote is a fixed +/- half_spread_vol band in *vol
    space*, each side converted to a price via Black-76. This is the
    options analogue of the perp side's plain Avellaneda-Stoikov quoting: a
    working version, not the GLFT+regime+toxicity stack core/ already has
    for perps.

    Size is scaled by core.risk.pin_risk.pin_risk_size_multiplier(): as
    expiry approaches with the underlying near the strike, gamma explodes
    and quoted size shrinks accordingly (never to zero -- see PinRiskParams).

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

    if svi_params is not None:
        bid_price_usd, ask_price_usd = quote_from_surface(
            underlying_price, strike, time_to_expiry_years, option_type, svi_params, half_spread_vol,
        )
    else:
        fair_vol = realized_vol * VRP_MULTIPLIER
        bid_vol = max(fair_vol - half_spread_vol, 1e-4)
        ask_vol = fair_vol + half_spread_vol
        bid_price_usd = black76_price(underlying_price, strike, time_to_expiry_years, bid_vol, option_type)
        ask_price_usd = black76_price(underlying_price, strike, time_to_expiry_years, ask_vol, option_type)

    pin_multiplier = pin_risk_size_multiplier(underlying_price, strike, time_to_expiry_years, pin_risk_params)
    sized = size * pin_multiplier

    return QuoteDecision(
        bid_price=bid_price_usd / underlying_price,
        ask_price=ask_price_usd / underlying_price,
        bid_size=sized, ask_size=sized,
        skip_bid=False, skip_ask=False,
        breaches=() if pin_multiplier == 1.0 else (f"pin risk: size scaled by {pin_multiplier:.2f}",),
    )
