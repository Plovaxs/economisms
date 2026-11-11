"""MGR-02: "Document conceptual soundness and theoretical
assumptions"; acceptance criterion: "independent reviewer evaluates
mathematical logic."

`THEORETICAL_ASSUMPTIONS` compiles, per subsystem, the REAL theoretical
assumption already documented in that subsystem's own module -- a
pointer to existing documentation, not new theory invented here, the
same "aggregate, don't re-derive" role `evidence.model_validation_report`
(MGR-04) already plays for backtest/calibration evidence.
`verify_theoretical_assumptions` confirms every cited module still
imports, so a stale citation to a renamed/removed module fails loudly
rather than silently.

"Independent reviewer evaluates mathematical logic" draws on the SAME
real evidence as EXP-14's `evidence.replication_digest`: PR-162's
AI-assisted audit pass hand-checked `pde_solvers`' residual loss and
deep-BSDE Delta identity term-by-term against the real Black-Scholes
PDE, and found and fixed a real mathematical-logic defect in HDG-14's
REINFORCE agent (using the differentiable `rsample()` instead of the
detached `sample()` silently zeroed the policy gradient identically) --
a genuine evaluation of mathematical logic, not merely a numeric
rerun. `reviewer_type` is honestly `"internal_ai_assisted"` on every
record, the same disclosed gap as EXP-14: this repository has no
external or independent human reviewer.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AssumptionRecord:
    subsystem: str
    subsystem_module: str
    theoretical_assumption: str
    documented_in: str
    mathematical_logic_evaluated: bool
    reviewer_type: str

    def __post_init__(self) -> None:
        for name, value in (
            ("subsystem", self.subsystem),
            ("subsystem_module", self.subsystem_module),
            ("theoretical_assumption", self.theoretical_assumption),
            ("documented_in", self.documented_in),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must not be empty")


THEORETICAL_ASSUMPTIONS: tuple[AssumptionRecord, ...] = (
    AssumptionRecord(
        subsystem="Black-Scholes/Merton closed-form pricing",
        subsystem_module="prometheus.volterra.black_scholes",
        theoretical_assumption=(
            "Geometric Brownian motion under a constant risk-free rate and "
            "constant volatility, European exercise, and a constant "
            "dividend yield -- the standard Black-Scholes/Merton closed-form "
            "assumptions this module's own pricer and Greeks rely on."
        ),
        documented_in="prometheus.volterra.black_scholes module docstring",
        mathematical_logic_evaluated=True,
        reviewer_type="internal_ai_assisted",
    ),
    AssumptionRecord(
        subsystem="PDE solvers (grid / deep-BSDE / PINN)",
        subsystem_module="prometheus.pde_solvers.benchmark",
        theoretical_assumption=(
            "A deep-BSDE/PINN/grid solution must satisfy the real "
            "Black-Scholes PDE and its own Delta identity in the continuum "
            "limit. This was independently hand-checked term-by-term "
            "against the real PDE and re-derived numerically during PR-162's "
            "audit pass; see evidence.replication_digest's PDE record."
        ),
        documented_in="prometheus.pde_solvers.benchmark module docstring",
        mathematical_logic_evaluated=True,
        reviewer_type="internal_ai_assisted",
    ),
    AssumptionRecord(
        subsystem="Hedging (REINFORCE policy gradient)",
        subsystem_module="prometheus.hedging.rl_agent",
        theoretical_assumption=(
            "A REINFORCE (score-function) policy gradient requires the "
            "sampled action used in the log-probability term to be DETACHED "
            "from the policy parameters (dist.sample(), not dist.rsample()) "
            "-- otherwise the reparameterized sample's own dependence on the "
            "policy mean exactly cancels log_prob's dependence on it, "
            "zeroing the gradient identically. This assumption was violated "
            "in this repository's own code and silently broke the gradient "
            "until PR-162's audit pass caught it; see "
            "evidence.replication_digest's MAR record for the sibling check "
            "that confirmed MAR's own PPO update does NOT share this bug."
        ),
        documented_in="prometheus.hedging.rl_agent module docstring",
        mathematical_logic_evaluated=True,
        reviewer_type="internal_ai_assisted",
    ),
)


class AssumptionCoverageError(ValueError):
    """Raised by `verify_theoretical_assumptions` when a cited
    subsystem_module no longer imports -- a stale citation to code
    that was since renamed or removed."""


def verify_theoretical_assumptions(
    records: tuple[AssumptionRecord, ...] = THEORETICAL_ASSUMPTIONS,
) -> None:
    for record in records:
        try:
            importlib.import_module(record.subsystem_module)
        except ImportError as exc:
            raise AssumptionCoverageError(
                f"{record.subsystem}: subsystem_module "
                f"{record.subsystem_module!r} no longer imports"
            ) from exc
