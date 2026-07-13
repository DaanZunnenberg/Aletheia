from __future__ import annotations

# Placeholder for parametric volatility surface calibration.
#
# Planned implementations:
#
#   SVIParams   — Gatheral's Stochastic Volatility Inspired parameterisation
#                 w(k) = a + b*(rho*(k-m) + sqrt((k-m)^2 + sigma^2))
#                 where w = sigma_impl^2 * T, k = log(K/F)
#
#   SABRParams  — Hagan et al. (2002) SABR alpha/beta/rho/nu
#
# Each calibration routine should accept an IVSlice and return typed parameter
# objects. Calibration is performed via scipy.optimize.minimize with a chi-squared
# loss on mid IV.
#
# Interface:
#   calibrate_svi(slice: IVSlice) -> SVIParams
#   calibrate_sabr(slice: IVSlice, beta: float = 0.5) -> SABRParams
#
# Arbitrage-free SVI (Zeliade 2012) should be enforced via constraints on the
# butterfly and calendar spread no-arbitrage conditions before use in
# risk_neutral_distribution.py.
