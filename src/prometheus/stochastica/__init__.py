"""STOCHASTICA: physical-measure (P) stochastic market dynamics.

Current scope (PR-004): Tier 0 (analytical GBM, exact lognormal transition),
a correlated multi-asset GBM extension, and Tier 1 classical Heston
dynamics with a positivity-preserving discretization. Everything here
simulates under the physical measure P; risk-neutral (Q) pricing is a
separate, later subsystem (VOLTERRA) -- see core.ledger's and this
package's docstrings for why conflating the two is explicitly disallowed
(section 3.3 of the specification, SDE-09).
"""
