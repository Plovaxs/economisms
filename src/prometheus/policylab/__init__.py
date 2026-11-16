"""POLICYLAB-RL (FP-15): a central-bank, policy-RATE-setting agent.

Not the same subsystem as `prometheus.marl` (household/firm consumption/
labor policies under the original blueprint's MAR category). This package
trains a constrained PPO policy that sets a short-term policy rate inside a
small reduced-form macro environment (`environment.py`), compared against a
genuine Taylor-rule baseline (`taylor_rule.py`) that the repository did not
previously have -- `econosim.policy_rate.PolicyRateRule` is a mean-reverting
process with no inflation/output feedback at all, a different, pre-existing
primitive left untouched by this package.
"""
