from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.stats import norm

from options.surface import IVSlice


def _black_call(F: float, K: float, T: float, sigma: float, r: float = 0.0) -> float:
    """Black-76 call price."""
    if sigma <= 0 or T <= 0 or K <= 0 or F <= 0:
        return max(F - K, 0.0)
    sqrt_T = math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * sigma ** 2 * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    return math.exp(-r * T) * (F * norm.cdf(d1) - K * norm.cdf(d2))


@dataclass
class RiskNeutralDistribution:
    """
    Risk-neutral density f^Q(K) extracted via Breeden-Litzenberger (1978):

        f^Q(K) = e^{rT} * d²C/dK²

    Attributes
    ----------
    strikes        : strike grid (not log-moneyness)
    density        : f^Q(K), unnormalised numerical second derivative
    cdf            : cumulative distribution F^Q(K) = P^Q(S_T <= K)
    mean           : E^Q[S_T]  (approximated from density)
    variance       : Var^Q[S_T]
    skewness       : third standardised moment
    kurtosis       : excess kurtosis (fourth standardised moment - 3)
    is_valid       : True if density passes positivity and normalisation checks
    """
    strikes: np.ndarray
    density: np.ndarray
    cdf: np.ndarray
    mean: float
    variance: float
    skewness: float
    kurtosis: float
    is_valid: bool

    def tail_prob(self, K: float, side: str = "left") -> float:
        """
        P^Q(S_T <= K)  if side='left'
        P^Q(S_T >= K)  if side='right'
        """
        if side == "left":
            return float(np.interp(K, self.strikes, self.cdf))
        return 1.0 - float(np.interp(K, self.strikes, self.cdf))


def extract_risk_neutral_distribution(
    slice_: IVSlice,
    r: float = 0.0,
    n_strikes: int = 200,
    moneyness_range: tuple[float, float] = (-1.5, 1.5),
) -> RiskNeutralDistribution:
    """
    Extract the risk-neutral density for a single expiry slice via
    Breeden-Litzenberger numerical differentiation.

    Steps
    -----
    1. Build a dense strike grid in log-moneyness space.
    2. Evaluate call prices on the grid using the interpolated IV spline.
    3. Numerically differentiate twice: d²C/dK².
    4. Apply e^{rT} scaling and validate.

    Parameters
    ----------
    slice_          : calibrated IVSlice with a valid spline
    r               : risk-free rate (annualised); 0 for crypto
    n_strikes       : number of points in the dense strike grid
    moneyness_range : (m_min, m_max) in log-moneyness units
    """
    if slice_._spline is None:
        raise ValueError(f"IVSlice for expiry {slice_.expiry_ts} has no fitted spline")

    F = slice_.forward
    T = slice_.T

    m_min, m_max = moneyness_range
    m_grid = np.linspace(m_min, m_max, n_strikes)
    K_grid = F * np.exp(m_grid)

    # Call prices on the dense grid
    call_prices = np.array([
        _black_call(F, K, T, iv, r)
        if (iv := slice_.iv_at(m)) is not None
        else _black_call(F, K, T, float(slice_._spline(np.clip(m, m_min, m_max))), r)
        for K, m in zip(K_grid, m_grid)
    ])

    # Second derivative d²C/dK² via central differences
    dK = np.diff(K_grid)
    dK_mid = 0.5 * (dK[:-1] + dK[1:])   # spacing at interior points

    d2C_dK2 = np.diff(call_prices, 2) / (dK_mid ** 2)

    # Trim grid to interior points
    K_inner = K_grid[1:-1]
    density_raw = math.exp(r * T) * d2C_dK2

    # Validation
    negative_frac = np.mean(density_raw < 0)
    density_clipped = np.maximum(density_raw, 0.0)

    total_mass = np.trapz(density_clipped, K_inner)
    is_valid = negative_frac < 0.05 and 0.7 < total_mass < 1.3

    density_norm = density_clipped / total_mass if total_mass > 0 else density_clipped

    cdf = np.concatenate([[0.0], np.cumsum(density_norm * np.diff(K_inner, prepend=K_inner[0]))])
    cdf = np.clip(cdf, 0.0, 1.0)

    # Moments
    mean = float(np.trapz(K_inner * density_norm, K_inner))
    variance = float(np.trapz((K_inner - mean) ** 2 * density_norm, K_inner))
    std = math.sqrt(max(variance, 1e-12))
    skewness = float(np.trapz(((K_inner - mean) / std) ** 3 * density_norm, K_inner))
    kurtosis = float(np.trapz(((K_inner - mean) / std) ** 4 * density_norm, K_inner)) - 3.0

    return RiskNeutralDistribution(
        strikes=K_inner,
        density=density_norm,
        cdf=cdf,
        mean=mean,
        variance=variance,
        skewness=skewness,
        kurtosis=kurtosis,
        is_valid=is_valid,
    )
