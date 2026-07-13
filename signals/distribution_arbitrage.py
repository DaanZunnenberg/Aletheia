from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np

from options.risk_neutral_distribution import RiskNeutralDistribution
from models.physical_distribution import PhysicalDistribution


class Direction(Enum):
    LONG_VOL = "long_vol"       # implied vol cheap vs forecast; buy volatility
    SHORT_VOL = "short_vol"     # implied vol rich vs forecast; sell volatility
    LONG_SKEW = "long_skew"     # Q skew < P skew; buy downside puts relative to calls
    SHORT_SKEW = "short_skew"   # Q skew > P skew; sell downside puts
    NEUTRAL = "neutral"


@dataclass
class DistributionSignal:
    expiry_ts: int
    direction: Direction
    strength: float          # z-score or magnitude; dimensionless
    confidence: float        # ∈ [0, 1]; based on density validity and spread quality
    kl_divergence: float     # KL(P || Q)
    wasserstein: float       # W1 distance
    var_diff: float          # Q variance - P variance (positive = Q overestimates vol)
    skew_diff: float         # Q skewness - P skewness
    tail_diff_left: float    # P^Q(S < K*) - P^P(S < K*) where K* = 0.85 * F
    tail_diff_right: float   # P^Q(S > K*) - P^P(S > K*) where K* = 1.15 * F
    suggested_trade: str


def _kl_divergence(p: np.ndarray, q: np.ndarray, dx: np.ndarray) -> float:
    """KL(P || Q) = ∫ p * log(p/q) dK. Clips near-zero to avoid log(0)."""
    eps = 1e-12
    p = np.maximum(p, eps)
    q = np.maximum(q, eps)
    return float(np.sum(p * np.log(p / q) * dx))


def _wasserstein_1(cdf_p: np.ndarray, cdf_q: np.ndarray, strikes: np.ndarray) -> float:
    """W1 = ∫ |F_P(K) - F_Q(K)| dK."""
    dK = np.diff(strikes, prepend=strikes[0])
    return float(np.sum(np.abs(cdf_p - cdf_q) * dK))


def compare_distributions(
    rnd: RiskNeutralDistribution,
    phys: PhysicalDistribution,
    expiry_ts: int,
    forward: float,
) -> DistributionSignal:
    """
    Compare risk-neutral Q and physical P distributions on a common strike grid.

    The physical distribution is interpolated onto the risk-neutral grid if needed.
    """
    K_q = rnd.strikes
    p_density = np.interp(K_q, phys.strikes, phys.density)
    p_cdf = np.interp(K_q, phys.strikes, phys.cdf)

    dK = np.diff(K_q, prepend=K_q[0])

    kl = _kl_divergence(p_density, rnd.density, dK)
    w1 = _wasserstein_1(p_cdf, rnd.cdf, K_q)

    var_diff = rnd.variance - phys.variance
    skew_diff = rnd.skewness - phys.skewness

    K_left = 0.85 * forward
    K_right = 1.15 * forward
    tail_left = rnd.tail_prob(K_left, "left") - phys.tail_prob(K_left, "left")
    tail_right = rnd.tail_prob(K_right, "right") - phys.tail_prob(K_right, "right")

    confidence = 0.5
    if rnd.is_valid:
        confidence += 0.3
    if len(K_q) >= 100:
        confidence += 0.2
    confidence = min(confidence, 1.0)

    sigma_q = rnd.variance ** 0.5
    sigma_p = phys.variance ** 0.5
    vol_z = (sigma_q - sigma_p) / (sigma_p + 1e-8)

    if abs(vol_z) > 0.15 and abs(skew_diff) < 0.5:
        direction = Direction.SHORT_VOL if vol_z > 0 else Direction.LONG_VOL
        strength = abs(vol_z)
        trade = (
            "Sell ATM straddle, delta-hedge" if vol_z > 0
            else "Buy ATM straddle, delta-hedge"
        )
    elif abs(skew_diff) > 0.5:
        direction = Direction.SHORT_SKEW if skew_diff > 0 else Direction.LONG_SKEW
        strength = abs(skew_diff)
        trade = (
            "Short put spread (sell OTM put, buy further OTM put), delta-hedge"
            if skew_diff > 0
            else "Long put spread (buy OTM put, sell further OTM put), delta-hedge"
        )
    else:
        direction = Direction.NEUTRAL
        strength = 0.0
        trade = "No actionable signal"

    return DistributionSignal(
        expiry_ts=expiry_ts,
        direction=direction,
        strength=strength,
        confidence=confidence,
        kl_divergence=kl,
        wasserstein=w1,
        var_diff=var_diff,
        skew_diff=skew_diff,
        tail_diff_left=tail_left,
        tail_diff_right=tail_right,
        suggested_trade=trade,
    )
