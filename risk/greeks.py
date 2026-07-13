from __future__ import annotations

from dataclasses import dataclass, field

from data.market_state import OptionQuote


@dataclass
class Position:
    instrument_name: str
    quantity: float     # positive = long, negative = short; in contracts


@dataclass
class GreekExposure:
    """Aggregate Greeks across all open option positions."""
    net_delta: float = 0.0      # in units of underlying
    net_gamma: float = 0.0      # delta change per 1-unit move in underlying
    net_vega_usd: float = 0.0   # USD PnL per 1% change in IV
    net_theta_usd: float = 0.0  # USD PnL per calendar day
    gross_vega_usd: float = 0.0


def compute_exposure(
    positions: list[Position],
    quotes: dict[str, OptionQuote],
    spot_price: float,
) -> GreekExposure:
    """
    Aggregate Greeks for a portfolio of option positions.

    Parameters
    ----------
    positions  : list of open option positions
    quotes     : map of instrument_name -> OptionQuote with current Greeks
    spot_price : current index price (used to convert delta to USD)
    """
    net_delta = 0.0
    net_gamma = 0.0
    net_vega_usd = 0.0
    net_theta_usd = 0.0
    gross_vega_usd = 0.0

    for pos in positions:
        q = quotes.get(pos.instrument_name)
        if q is None:
            continue
        n = pos.quantity
        net_delta += (q.delta or 0.0) * n
        net_gamma += (q.gamma or 0.0) * n
        vega_usd = (q.vega or 0.0) * n * spot_price
        net_vega_usd += vega_usd
        net_theta_usd += (q.theta or 0.0) * n * spot_price
        gross_vega_usd += abs(vega_usd)

    return GreekExposure(
        net_delta=net_delta,
        net_gamma=net_gamma,
        net_vega_usd=net_vega_usd,
        net_theta_usd=net_theta_usd,
        gross_vega_usd=gross_vega_usd,
    )
