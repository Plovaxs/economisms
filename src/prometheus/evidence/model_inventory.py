"""Enterprise model inventory (MGR-01: "maintain enterprise model
inventory with tier/materiality"; acceptance criterion: "every active
model has business purpose and owner").

`ModelInventoryEntry` is a frozen, validated record -- `business_purpose`
and `owner` are required, non-optional fields (an inventory row with a
silently-missing purpose or owner is exactly the gap this item exists to
close, so the dataclass itself cannot construct one). `MODEL_INVENTORY`
is populated from the real trained-model families that actually exist in
this repository today, read from each subsystem's own real entry point
(`recessionnet.training`, `macrocore.quantum_benchmark`,
`neural_sde.training`, `hedging.deep_hedge`) -- not an aspirational list
of models that might exist someday. `active_inventory()`/`verify_inventory`
are the real, tested behavior: every entry is checked for a non-empty
purpose and owner, so "every active model has business purpose and
owner" is a checked invariant, not merely a populated table that could
silently drift.

Materiality tiers (`"research"` here for every current entry, since
nothing in this repository is a production decisioning model -- see
README.md's own NO-GO gate status) follow this project's own honest
self-assessment, not a regulatory materiality framework this repository
has no authority to apply.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

MaterialityTier = Literal["research", "production-candidate", "production"]
_VALID_TIERS: frozenset[str] = frozenset({"research", "production-candidate", "production"})


@dataclass(frozen=True, slots=True)
class ModelInventoryEntry:
    model_id: str
    business_purpose: str
    owner: str
    materiality_tier: MaterialityTier
    active: bool
    source_module: str
    authorized_applications: tuple[str, ...] = ("research",)
    """MGR-11: "restrict model usage to intended applications" -- the
    closed set of applications this model may be used for. Every
    current entry is `("research",)` only, since nothing in this
    repository is authorized for production use (see README.md's own
    NO-GO gate status) -- `authorize_model_usage` below is the real
    enforcement point, not just a descriptive label."""

    def __post_init__(self) -> None:
        for name, value in (
            ("model_id", self.model_id),
            ("business_purpose", self.business_purpose),
            ("owner", self.owner),
            ("source_module", self.source_module),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must not be empty")
        if self.materiality_tier not in _VALID_TIERS:
            raise ValueError(f"materiality_tier must be one of {sorted(_VALID_TIERS)}")
        if not self.authorized_applications:
            raise ValueError("authorized_applications must not be empty")


MODEL_INVENTORY: tuple[ModelInventoryEntry, ...] = (
    ModelInventoryEntry(
        model_id="recessionnet",
        business_purpose=(
            "Point-in-time-safe US recession classification research; compares base-rate, "
            "logistic regression, classical MLP and hybrid-quantum candidates"
        ),
        owner="project maintainer",
        materiality_tier="research",
        active=True,
        source_module="prometheus.recessionnet",
    ),
    ModelInventoryEntry(
        model_id="qmacro",
        business_purpose=(
            "h-months-ahead real-market-factor (Mkt-RF) regression research; compares "
            "persistence, AR(3), classical MLP and hybrid-quantum candidates"
        ),
        owner="project maintainer",
        materiality_tier="research",
        active=True,
        source_module="prometheus.macrocore",
    ),
    ModelInventoryEntry(
        model_id="neural-sde",
        business_purpose=(
            "Neural stochastic differential equation research for real US macro series "
            "(NASDAQ/GDP YoY), benchmarked against GBM/GARCH and evaluated OOD on the "
            "real 2020 COVID shock"
        ),
        owner="project maintainer",
        materiality_tier="research",
        active=True,
        source_module="prometheus.neural_sde",
    ),
    ModelInventoryEntry(
        model_id="deep-hedge",
        business_purpose=(
            "CVaR-trained neural hedging policy research, benchmarked against classical "
            "delta/no-trade-band baselines under transaction costs"
        ),
        owner="project maintainer",
        materiality_tier="research",
        active=True,
        source_module="prometheus.hedging",
    ),
    ModelInventoryEntry(
        model_id="pde-solvers",
        business_purpose=(
            "PINN and deep-BSDE neural solvers for the Black-Scholes PDE, benchmarked "
            "against the closed-form pricer and Monte Carlo for accuracy and compute cost"
        ),
        owner="project maintainer",
        materiality_tier="research",
        active=True,
        source_module="prometheus.pde_solvers",
    ),
)


class InventoryValidationError(ValueError):
    """Raised by `verify_inventory` when an active entry is missing a
    required field -- should be unreachable given `ModelInventoryEntry`'s
    own `__post_init__`, but checked independently rather than assumed,
    the same defense-in-depth this project applies elsewhere (e.g.
    `evidence.model_card.ModelCard` vs. its own callers)."""


def active_inventory(
    inventory: tuple[ModelInventoryEntry, ...] = MODEL_INVENTORY,
) -> tuple[ModelInventoryEntry, ...]:
    return tuple(e for e in inventory if e.active)


def verify_inventory(inventory: tuple[ModelInventoryEntry, ...] = MODEL_INVENTORY) -> None:
    for entry in active_inventory(inventory):
        if not entry.business_purpose.strip() or not entry.owner.strip():
            raise InventoryValidationError(
                f"{entry.model_id}: active inventory entry missing business_purpose or owner"
            )


class UnauthorizedModelUsageError(PermissionError):
    """Raised by `authorize_model_usage` when `requested_application`
    is not in the model's own `authorized_applications` -- MGR-11's
    real enforcement point. `dashboard.app` wires this into a live,
    rejectable HTTP route (not just a library call nobody invokes)."""


def authorize_model_usage(
    model_id: str,
    requested_application: str,
    inventory: tuple[ModelInventoryEntry, ...] = MODEL_INVENTORY,
) -> ModelInventoryEntry:
    entry = next((e for e in inventory if e.model_id == model_id), None)
    if entry is None:
        raise UnauthorizedModelUsageError(f"{model_id!r} is not a known inventoried model")
    if requested_application not in entry.authorized_applications:
        raise UnauthorizedModelUsageError(
            f"{model_id!r} is not authorized for application {requested_application!r} "
            f"(authorized: {sorted(entry.authorized_applications)})"
        )
    return entry
