from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.interpolate import CubicSpline

from data.market_state import MarketState, OptionQuote


@dataclass
class IVSlice:
    """IV smile for a single expiry, normalised to log-moneyness."""
    expiry_ts: int
    T: float                    # time to expiry in years
    forward: float              # forward price used for normalisation
    moneyness: np.ndarray       # m = log(K/F), sorted ascending
    strikes: np.ndarray         # raw strikes, same order
    iv: np.ndarray              # mid IV (annualised fraction), same order
    _spline: CubicSpline | None = None

    def __post_init__(self) -> None:
        if len(self.moneyness) >= 4:
            self._spline = CubicSpline(self.moneyness, self.iv, extrapolate=False)

    def iv_at(self, moneyness: float) -> float | None:
        """Interpolated IV at log-moneyness m = log(K/F). Returns None outside range."""
        if self._spline is None:
            return None
        val = float(self._spline(moneyness))
        if math.isnan(val):
            return None
        return max(val, 1e-6)

    def iv_at_strike(self, K: float) -> float | None:
        if self.forward <= 0:
            return None
        return self.iv_at(math.log(K / self.forward))


@dataclass
class IVSurface:
    """Collection of IV slices across all available expiries."""
    currency: str
    timestamp: float
    slices: list[IVSlice]

    def slice_for(self, expiry_ts: int) -> IVSlice | None:
        for s in self.slices:
            if s.expiry_ts == expiry_ts:
                return s
        return None

    def expiries(self) -> list[int]:
        return [s.expiry_ts for s in self.slices]


def _mid_iv(opt: OptionQuote) -> float | None:
    if opt.bid_iv is not None and opt.ask_iv is not None and opt.bid_iv > 0 and opt.ask_iv > 0:
        return (opt.bid_iv + opt.ask_iv) / 2.0
    if opt.mark_iv > 0:
        return opt.mark_iv
    return None


def build_surface(state: MarketState) -> IVSurface:
    """
    Build an IV surface from a MarketState snapshot.

    Each expiry becomes one IVSlice. Strikes are normalised to log-moneyness
    using the dated forward if available, else the spot price.

    Options with no usable IV (zero mark_iv, no bid/ask) are excluded.
    Slices with fewer than 3 valid strikes are excluded.
    """
    now_ms = state.timestamp
    slices: list[IVSlice] = []

    for expiry_ts in state.expiries():
        T = max((expiry_ts - now_ms) / (1000 * 365.25 * 86400), 1e-6)

        forward = state.forward(expiry_ts)
        if forward is None or forward <= 0:
            forward = state.spot_price

        calls = state.calls(expiry_ts)
        rows: list[tuple[float, float, float]] = []   # (strike, moneyness, iv)

        for opt in calls:
            iv = _mid_iv(opt)
            if iv is None or iv <= 0:
                continue
            m = math.log(opt.strike / forward)
            rows.append((opt.strike, m, iv))

        if len(rows) < 3:
            continue

        rows.sort(key=lambda r: r[1])
        strikes = np.array([r[0] for r in rows])
        moneyness = np.array([r[1] for r in rows])
        iv_arr = np.array([r[2] for r in rows])

        slices.append(IVSlice(
            expiry_ts=expiry_ts,
            T=T,
            forward=forward,
            moneyness=moneyness,
            strikes=strikes,
            iv=iv_arr,
        ))

    return IVSurface(currency=state.currency, timestamp=state.timestamp, slices=slices)
