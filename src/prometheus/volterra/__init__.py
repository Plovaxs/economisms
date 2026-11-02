"""VOLTERRA: risk-neutral (Q) derivative pricing.

Current scope (PR-005): European call/put pricing via the Black-Scholes
closed form, analytical Greeks cross-checked against central finite
differences, put-call parity, and a Monte Carlo pricer with an optional
control variate. Every entry point requires an explicit, structurally
enforced Q-measure market snapshot (see market.MarketSnapshot) -- SDE-09:
"Distinguish physical P and risk-neutral Q model instances. Explicit
measure field required in every engine call." Do not pass a physical-
measure (real-world drift mu) path simulation into anything here; the
Monte Carlo pricer always simulates under Q (drift = risk_free_rate -
dividend_yield), never under an agent's or calibration's physical mu.
"""
