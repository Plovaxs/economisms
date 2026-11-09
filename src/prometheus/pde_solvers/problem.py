"""PDE-01: the shared problem specification every solver in this
package is built from.

The Black-Scholes PDE in (S, t):

    V_t + 0.5*sigma^2*S^2*V_SS + r*S*V_S - r*V = 0,   S in (0, S_max), t in [0, T)
    V(S, T)  = payoff(S)                               terminal condition
    V(0, t)  = boundary_lower(t)                        lower boundary
    V(S_max, t) = boundary_upper(t)                      upper boundary (truncated domain)

`S_max` is a numerical truncation of the true domain (0, infinity) --
`s_max_multiple * strike` is large enough that the option's time value
there is negligible, a standard and disclosed approximation (not a
claim that the PDE's true domain is bounded).

`BasketOptionPDESpec` is the same PDE generalized to `n_assets`
correlated underlyings with payoff max(mean(S) - K, 0) (or the put
analogue): same -r*V term, same risk-neutral drift, now with a
cross-asset diffusion term. It exists to give PDE-07/PDE-12 ("benchmark
error by dimension", "compare neural compute cost") a genuine
higher-dimensional case: `grid` only ever solves the 1-asset case
(a d-dimensional finite-difference grid has M^d nodes -- see
`benchmark.grid_node_count`), `deep_bsde` solves both.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from prometheus.numerics import require_finite

OptionType = Literal["call", "put"]


@dataclass(frozen=True, slots=True)
class BlackScholesPDESpec:
    risk_free_rate: float
    volatility: float
    maturity: float
    strike: float
    option_type: OptionType
    s_max_multiple: float = 4.0

    def __post_init__(self) -> None:
        require_finite(
            risk_free_rate=self.risk_free_rate,
            volatility=self.volatility,
            maturity=self.maturity,
            strike=self.strike,
            s_max_multiple=self.s_max_multiple,
        )
        if self.volatility <= 0:
            raise ValueError("volatility must be positive")
        if self.maturity <= 0:
            raise ValueError("maturity must be positive")
        if self.strike <= 0:
            raise ValueError("strike must be positive")
        if self.option_type not in ("call", "put"):
            raise ValueError(f"option_type must be 'call' or 'put', got {self.option_type!r}")
        if self.s_max_multiple <= 1.0:
            raise ValueError("s_max_multiple must exceed 1.0 to bracket the strike")

    @property
    def s_max(self) -> float:
        return self.strike * self.s_max_multiple

    def payoff(self, s: np.ndarray) -> np.ndarray:
        s = np.asarray(s, dtype=float)
        if self.option_type == "call":
            return np.maximum(s - self.strike, 0.0)
        return np.maximum(self.strike - s, 0.0)

    def boundary_lower(self, time_to_maturity: np.ndarray) -> np.ndarray:
        """Value at S=0. A call is worthless at S=0 for all t (geometric
        diffusion never reaches 0 from above, but the truncated grid's
        S=0 node still needs a boundary value); a put at S=0 is worth
        the discounted strike."""
        tau = np.asarray(time_to_maturity, dtype=float)
        if self.option_type == "call":
            return np.zeros_like(tau)
        return self.strike * np.exp(-self.risk_free_rate * tau)

    def boundary_upper(self, time_to_maturity: np.ndarray) -> np.ndarray:
        """Value at S=S_max. Deep in-the-money, a call's value is
        linear in S (delta -> 1): S - K*exp(-r*tau). A put deep
        out-of-the-money is worth ~0."""
        tau = np.asarray(time_to_maturity, dtype=float)
        if self.option_type == "call":
            return self.s_max - self.strike * np.exp(-self.risk_free_rate * tau)
        return np.zeros_like(tau)


@dataclass(frozen=True, slots=True)
class BasketOptionPDESpec:
    risk_free_rate: float
    volatilities: tuple[float, ...]
    correlation: tuple[tuple[float, ...], ...]
    maturity: float
    strike: float
    option_type: OptionType

    def __post_init__(self) -> None:
        require_finite(
            risk_free_rate=self.risk_free_rate, maturity=self.maturity, strike=self.strike
        )
        n = len(self.volatilities)
        if n < 1:
            raise ValueError("volatilities must be non-empty")
        if any(v <= 0 for v in self.volatilities):
            raise ValueError("every volatility must be positive")
        if len(self.correlation) != n or any(len(row) != n for row in self.correlation):
            raise ValueError(f"correlation must be a {n}x{n} matrix matching n_assets={n}")
        corr = np.asarray(self.correlation, dtype=float)
        if not np.allclose(corr, corr.T, atol=1e-8):
            raise ValueError("correlation matrix is not symmetric")
        if not np.allclose(np.diag(corr), 1.0, atol=1e-8):
            raise ValueError("correlation matrix must have unit diagonal")
        if np.min(np.linalg.eigvalsh(corr)) < -1e-8:
            raise ValueError("correlation matrix is not positive semidefinite")
        if self.maturity <= 0:
            raise ValueError("maturity must be positive")
        if self.strike <= 0:
            raise ValueError("strike must be positive")
        if self.option_type not in ("call", "put"):
            raise ValueError(f"option_type must be 'call' or 'put', got {self.option_type!r}")

    @property
    def n_assets(self) -> int:
        return len(self.volatilities)

    def payoff(self, s_terminal: np.ndarray) -> np.ndarray:
        """s_terminal: shape (n_paths, n_assets). Basket payoff on the
        equal-weighted mean of the terminal prices."""
        s_terminal = np.asarray(s_terminal, dtype=float)
        basket = s_terminal.mean(axis=-1)
        if self.option_type == "call":
            return np.maximum(basket - self.strike, 0.0)
        return np.maximum(self.strike - basket, 0.0)
