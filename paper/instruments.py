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


async def find_strikes_near_the_money(
    client: DeribitREST, currency: str, reference_price: float, n_strikes: int = 5, option_type: str = "call",
) -> list[OptionInstrument]:
    """
    Same nearest-expiry selection as find_near_the_money_option(), but
    returns the n_strikes closest-to-the-money instruments instead of one
    -- the cross-section core.models.options.surface_quoting.fit_smile()
    needs to fit a live SVI smile (paper/engine.py's per-tick fit), rather
    than the single flat-vol strike find_near_the_money_option() picks.
    Sorted by |strike - reference_price| ascending.
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

    same_expiry.sort(key=lambda i: abs(_strike_of(i["instrument_name"]) - reference_price))
    chosen = same_expiry[:n_strikes]
    return [
        OptionInstrument(
            instrument_name=i["instrument_name"], currency=currency,
            strike=_strike_of(i["instrument_name"]), option_type=option_type,
            expiration_timestamp_ms=float(i["expiration_timestamp"]),
        )
        for i in chosen
    ]


def _strike_of(instrument_name: str) -> float:
    # Deribit option naming: {CURRENCY}-{DDMMMYY}-{STRIKE}-{C|P}
    return float(instrument_name.split("-")[2])
