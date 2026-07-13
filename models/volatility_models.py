from __future__ import annotations

# Placeholder for volatility forecasting models.
#
# Planned implementations:
#
#   GARCHModel        — GARCH(1,1) fitted to log-returns; produces a term-structure
#                       of conditional variance forecasts
#
#   HestonModel       — Calibrated to the IV surface via Heston (1993) characteristic
#                       function; produces a risk-neutral density analytically
#
#   EWMAVolModel      — Exponentially weighted moving average realised vol;
#                       simple baseline for short-horizon forecasts
#
# Interface each model should satisfy (mirrors PhysicalDistributionModel):
#
#   model.fit(returns: np.ndarray) -> None
#   model.forecast_variance(horizon: float) -> float   # annualised variance
#   model.forecast_density(S0, horizon, strike_grid) -> np.ndarray  # density on grid
