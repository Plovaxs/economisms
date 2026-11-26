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
- ``learned_warning``  a logistic early-warning model scored on worlds it has not seen.
- ``calibration`` stylised-fact guard rails, and ``sensitivity`` one-at-a-time parameter swings.

Firms (a leverage cycle), a government (taxes, counter-cyclical spending, debt, a sovereign
spread), a foreign sector (an exchange rate, pass-through, foreign-currency bank debt) and bank
bail-outs are switched on by `config.full_scenario`; with them off the world is exactly the one
Finding 25 used.

`config.connected_scenario` goes one step further and closes the loops (see `LinkParams`):
``households_block`` puts the households inside the world (consumption moves output, taxes and
transfers move the budget, uninsured deposits are lost in a bank failure), deposits are insured by
the state, banks hold its bonds, the state can default, and firm distress raises unemployment.
``impulse`` measures how a one-off shock to one sector travels to all the others, and
``inequality`` holds the wealth-concentration measures.

`calibrated` holds the parameters that real data could estimate (equity regimes, Okun's coefficient,
the macro block, bank-lending growth), estimated in `real_calibration` and fixed in `calibrated`
(Finding 28); everything the data could not speak to keeps its chosen value. `transmission` maps
where a shock enters and which feedback loops carry it.

The world's path does not depend on the households' allocation rule (households are price takers),
so a comparison of rules on the same seed is paired by construction.
"""
