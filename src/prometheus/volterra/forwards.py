"""Forward contract pricing (cost-of-carry), extending PRI-01.

`forward_price` is the fair delivery price for a BRAND NEW forward
entered today: F = S * exp((r - q) * T) -- the unique delivery price that
makes a freshly-entered contract worth exactly zero.

`forward_contract_value` prices an EXISTING contract (delivery price K
fixed at some point in the past) at its current remaining maturity:

    V = S * exp(-q*T) - K * exp(-r*T)

Cross-checked in tests against the economically equivalent
(F_now - K) * exp(-r*T) formulation -- two different ways of writing the
same no-arbitrage value, and against the structural fact that a freshly
entered contract (K = F_now) is worth exactly zero.
"""

from __future__ import annotations

import math

from prometheus.volterra.instruments import ForwardContract
from prometheus.volterra.market import MarketSnapshot


def forward_price(market: MarketSnapshot, maturity: float) -> float:
    if maturity <= 0:
        raise ValueError("maturity must be positive")
    return market.spot * math.exp((market.risk_free_rate - market.dividend_yield) * maturity)


def forward_contract_value(market: MarketSnapshot, contract: ForwardContract) -> float:
    s, k, r, q, t = (
        market.spot,
        contract.delivery_price,
        market.risk_free_rate,
        market.dividend_yield,
        contract.maturity,
    )
    return s * math.exp(-q * t) - k * math.exp(-r * t)
