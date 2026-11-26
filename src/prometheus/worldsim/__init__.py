"""WORLDSIM: a volatile, reduced-form world that joins an economy, asset markets, households and
banks.

Everything in this package is a SIMULATION with parameters chosen to look like a plausible real
economy (business-cycle regimes, crises with correlation breakdown, a wealth distribution with a
fat tail, a leveraged banking sector linked by interbank loans), not parameters estimated from
data. Results are statements about the simulator, never forecasts and never advice; the
repository's NO-GO gate is unchanged.

The pieces, one module each:

- ``config``      scenarios (calm, volatile, stressed) and every parameter in one place.
- ``world``       the exogenous path: Markov regimes, output gap, inflation, policy rate (a Taylor
  rule), four asset returns with regime-dependent volatility and correlations, jumps into a crisis,
  and a banking sector whose fire sales feed back into equity prices.
- ``banks``       balance sheets, loan losses, capital rules and interbank clearing (the
  repository's Eisenberg-Noe solver), with contagion defaults counted separately.
- ``allocation``  five asset-allocation rules (equal weight, 60/40, risk parity, minimum variance,
  volatility target).
- ``households``  a wealth distribution, income, unemployment, consumption, saving and portfolio
  rebalancing, and inequality measures.
- ``monitor``     early-warning indicators, alert levels and a scored composite.

The world's path does not depend on the households' allocation rule (households are price takers),
so a comparison of rules on the same seed is paired by construction.
"""
