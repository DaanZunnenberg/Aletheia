from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np

from data.market_state import MarketState


@dataclass
class PhysicalDistribution:
    """
    Estimated physical (real-world) distribution P_t(S_T).

    Represented as a discrete density on a strike grid so it is directly
    comparable to RiskNeutralDistribution from the same grid.
    """
    strikes: np.ndarray    # same grid convention as RiskNeutralDistribution
    density: np.ndarray    # normalised density on strikes
    cdf: np.ndarray
    mean: float
    variance: float
    skewness: float
    kurtosis: float
    model_name: str

    def tail_prob(self, K: float, side: str = "left") -> float:
        if side == "left":
            return float(np.interp(K, self.strikes, self.cdf))
        return 1.0 - float(np.interp(K, self.strikes, self.cdf))


class PhysicalDistributionModel(ABC):
    """
    Interface for all physical distribution estimators.

    Subclass this and implement predict(). The framework calls predict() with
    a fresh MarketState and a horizon in years, and expects a PhysicalDistribution
    defined on the same strike grid used by the risk-neutral extraction.
    """

    @abstractmethod
    def predict(
        self,
        state: MarketState,
        horizon: float,
        strike_grid: np.ndarray,
    ) -> PhysicalDistribution:
        """
        Parameters
        ----------
        state        : current market snapshot
        horizon      : time horizon T in years
        strike_grid  : strike grid to evaluate density on (matches RND grid)

        Returns
        -------
        PhysicalDistribution on strike_grid
        """


class LogNormalHistoricalModel(PhysicalDistributionModel):
    """
    Baseline physical distribution: lognormal parameterised by historical
    realised volatility and zero drift.

    sigma_hist is estimated from recent log-returns of the index price.
    Drift is set to zero (risk-neutral under physical measure for unbiased baseline).

    This is the simplest possible model — purely for establishing a benchmark.
    Replace with GARCH or stochastic vol once the pipeline is validated.
    """

    def __init__(self, returns: np.ndarray) -> None:
        """
        Parameters
        ----------
        returns : array of log-returns at some frequency (e.g., 5-minute or hourly)
        """
        if len(returns) < 10:
            raise ValueError("Need at least 10 observations to estimate realised vol")
        self._sigma_daily = float(np.std(returns, ddof=1))
        self._n_obs_per_year: float | None = None

    def set_frequency(self, obs_per_year: float) -> None:
        """Annualise the per-observation sigma. Call before predict()."""
        self._n_obs_per_year = obs_per_year

    def predict(
        self,
        state: MarketState,
        horizon: float,
        strike_grid: np.ndarray,
    ) -> PhysicalDistribution:
        if self._n_obs_per_year is None:
            raise RuntimeError("Call set_frequency() before predict()")

        S0 = state.spot_price
        sigma_ann = self._sigma_daily * np.sqrt(self._n_obs_per_year)
        sigma_T = sigma_ann * np.sqrt(horizon)
        mu_T = -0.5 * sigma_T ** 2    # risk-neutral drift under lognormal

        log_K = np.log(strike_grid / S0)
        density_raw = (
            np.exp(-0.5 * ((log_K - mu_T) / sigma_T) ** 2)
            / (strike_grid * sigma_T * np.sqrt(2 * np.pi))
        )

        total = np.trapz(density_raw, strike_grid)
        density = density_raw / max(total, 1e-12)
        cdf = np.concatenate([[0.0], np.cumsum(density * np.diff(strike_grid, prepend=strike_grid[0]))])
        cdf = np.clip(cdf, 0.0, 1.0)

        mean = float(np.trapz(strike_grid * density, strike_grid))
        variance = float(np.trapz((strike_grid - mean) ** 2 * density, strike_grid))
        std = float(np.sqrt(max(variance, 1e-12)))
        skewness = float(np.trapz(((strike_grid - mean) / std) ** 3 * density, strike_grid))
        kurtosis = float(np.trapz(((strike_grid - mean) / std) ** 4 * density, strike_grid)) - 3.0

        return PhysicalDistribution(
            strikes=strike_grid,
            density=density,
            cdf=cdf,
            mean=mean,
            variance=variance,
            skewness=skewness,
            kurtosis=kurtosis,
            model_name="lognormal_historical",
        )
