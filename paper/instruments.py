from __future__ import annotations

from dataclasses import dataclass

from deribit.rest import DeribitREST


@dataclass(frozen=True)
class OptionInstrument:
    instrument_name: str
    currency: str
    strike: float
    option_type: str  # 'call' | 'put'
    expiration_timestamp_ms: float


async def find_near_the_money_option(
    client: DeribitREST, currency: str, reference_price: float, option_type: str = "call",
) -> OptionInstrument:
    """
    Picks the nearest-expiry, closest-to-the-money instrument for `currency`
    -- typically a 0DTE/1DTE strike given how Deribit lists daily expiries.
    One instrument, not a strike ladder: paper_trading_bot.py quotes a
    single representative option per coin, not a full surface (SVI
    calibration against a live strike grid is future work -- see
    core/models/options/svi.py, not wired in here yet).
    """
    instruments = await client.get_instruments(currency, kind="option", expired=False)
    if not instruments:
        raise ValueError(f"no active options found for {currency}")

    nearest_expiry = min(i["expiration_timestamp"] for i in instruments)
    suffix = "-C" if option_type == "call" else "-P"
    same_expiry = [
        i for i in instruments
        if i["expiration_timestamp"] == nearest_expiry and i["instrument_name"].endswith(suffix)
    ]
    if not same_expiry:
        raise ValueError(f"no {option_type} options found for {currency} at nearest expiry")

    closest = min(same_expiry, key=lambda i: abs(_strike_of(i["instrument_name"]) - reference_price))
    return OptionInstrument(
        instrument_name=closest["instrument_name"],
        currency=currency,
        strike=_strike_of(closest["instrument_name"]),
        option_type=option_type,
        expiration_timestamp_ms=float(closest["expiration_timestamp"]),
    )


def _strike_of(instrument_name: str) -> float:
    # Deribit option naming: {CURRENCY}-{DDMMMYY}-{STRIKE}-{C|P}
    return float(instrument_name.split("-")[2])
