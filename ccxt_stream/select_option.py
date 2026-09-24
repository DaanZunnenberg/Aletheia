from __future__ import annotations

import time
from dataclasses import dataclass

import ccxt


@dataclass(frozen=True)
class SelectedOption:
    symbol: str          # ccxt unified symbol, e.g. 'BTC/USD:BTC-260922-69000-C'
    strike: float
    expiry_ms: float
    hours_to_expiry: float


def select_near_1dte_option(
    exchange: ccxt.deribit, currency: str, spot_price: float, target_hours: float = 24.0,
) -> SelectedOption:
    """
    Nearest-to-1-day-to-expiry, nearest-to-the-money call on Deribit.

    Deribit (unlike Binance, which discontinued its options market in 2024 --
    verified live via ccxt: zero option markets currently listed there)
    lists daily expiries, so "1DTE" is well-defined here: the expiry whose
    time-to-expiry is closest to target_hours, not necessarily the very next
    expiry (which could be a few hours out right after a daily 08:00 UTC
    settlement).
    """
    markets = exchange.load_markets()
    now_ms = time.time() * 1000.0
    candidates = [
        m for m in markets.values()
        if m.get("option") and m.get("base") == currency and m.get("settle") == currency
        and m.get("optionType") == "call" and m["expiry"] > now_ms
    ]
    if not candidates:
        raise ValueError(f"no live {currency} call options found on {exchange.id}")

    expiries = sorted({m["expiry"] for m in candidates})
    best_expiry = min(expiries, key=lambda e: abs((e - now_ms) / 3600_000.0 - target_hours))

    same_expiry = [m for m in candidates if m["expiry"] == best_expiry]
    nearest = min(same_expiry, key=lambda m: abs(m["strike"] - spot_price))

    return SelectedOption(
        symbol=nearest["symbol"], strike=nearest["strike"], expiry_ms=best_expiry,
        hours_to_expiry=(best_expiry - now_ms) / 3600_000.0,
    )


def select_strikes_near_expiry(
    exchange: ccxt.deribit, currency: str, spot_price: float, n_strikes: int = 5, target_hours: float = 24.0,
) -> list[SelectedOption]:
    """
    Same nearest-1DTE expiry as select_near_1dte_option(), but returns the
    n_strikes calls closest to spot at that expiry instead of just the
    single nearest one -- a cross-section, not a point. This is what
    core.models.options.surface_quoting.fit_smile() needs: SVI has 5 free
    parameters, so fitting a smile off a single strike (this project's
    original live-quoting convention) is meaningless, and
    fit_smile()/MIN_STRIKES_FOR_SVI already refuses fewer than 3 anyway.

    Sorted by |strike - spot| ascending, so callers that only want the
    single nearest-the-money strike (e.g. to keep quoting the same
    instrument select_near_1dte_option() would have picked) can just take
    result[0].
    """
    markets = exchange.load_markets()
    now_ms = time.time() * 1000.0
    candidates = [
        m for m in markets.values()
        if m.get("option") and m.get("base") == currency and m.get("settle") == currency
        and m.get("optionType") == "call" and m["expiry"] > now_ms
    ]
    if not candidates:
        raise ValueError(f"no live {currency} call options found on {exchange.id}")

    expiries = sorted({m["expiry"] for m in candidates})
    best_expiry = min(expiries, key=lambda e: abs((e - now_ms) / 3600_000.0 - target_hours))

    same_expiry = [m for m in candidates if m["expiry"] == best_expiry]
    same_expiry.sort(key=lambda m: abs(m["strike"] - spot_price))
    chosen = same_expiry[:n_strikes]

    return [
        SelectedOption(
            symbol=m["symbol"], strike=m["strike"], expiry_ms=best_expiry,
            hours_to_expiry=(best_expiry - now_ms) / 3600_000.0,
        )
        for m in chosen
    ]
