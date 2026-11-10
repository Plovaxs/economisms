"""Model registry states, a code-enforced transition policy, and a
promotion gate (MLO-08: "create registry states: candidate/evaluated/
approved/staged/retired"; acceptance criterion: "transition policy
enforced by code and audit trail". MLO-10: "block deployment for
missing provenance or validation"; acceptance criterion: "promotion
gate test denies incomplete candidates". AUD-06: "capture all model
registry and promotion transitions"; acceptance criterion: "identity,
approval, previous state and hash recorded").

`ModelRegistryEntry` holds exactly the five states MLO-08 names and a
complete, append-only `history` of every `StateTransition` it has ever
undergone -- AUD-06's own four named fields, each literally present:
`actor` (identity), `approved_by` (approval -- a separate, REQUIRED
field with no default, since a silently-defaulted approver would not
be a deliberate declaration), `from_state` (previous state, already
part of every `StateTransition`), and `content_hash` (hash, optional
since not every transition has a packaged artifact to hash yet, but
REQUIRED specifically on a promotion to `approved` -- the one
transition AUD-06 names by name, "promotion transitions"). The
transition policy itself (`is_allowed_transition`) is a pure function,
not merely documented in prose: `candidate -> evaluated -> approved ->
staged -> retired` is the only forward path, and any non-retired state
may additionally move directly to `retired` (an emergency pull is
legitimate at any stage); every other transition, including any
backward move, is rejected with `IllegalTransitionError`.

`promote_to_approved` layers MLO-10's gate ON TOP of that same
transition policy rather than duplicating it: it still calls
`entry.transition("approved", ...)`, so an entry not already in the
`evaluated` state is rejected by the policy exactly as any other
illegal transition would be, but it ADDITIONALLY requires a
`training_provenance.TrainingProvenanceManifest` (reused from AUD-03),
a passing validation result, and now a `model_package.ModelPackage`
(reused from MLO-07) whose `content_hash` is recorded on the resulting
transition -- "block deployment for missing provenance or validation,"
checked directly, not assumed from the state machine alone.

`promote_to_approved` ALSO now enforces CIQ-08's "two-person approval"
at the one identity-distinctness check this registry can honestly make:
`approved_by == actor` is rejected with `SinglePersonApprovalError`
before the transition is even attempted, so a promotion can no longer
be silently self-approved by the same recorded identity that performed
it. This is NOT real second-human authentication -- this repository has
no multi-user identity system behind model-registry actors (contrast
`service.auth.CredentialStore`, which DOES authenticate real distinct
principals for the job API and dashboard), so one person could still
type two different strings -- but the enforcement itself, and the
rejection of a same-identity promotion, is real and tested, not merely
documented as a convention nobody checks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from prometheus.evidence.model_package import ModelPackage
from prometheus.experiments.training_provenance import TrainingProvenanceManifest

RegistryState = Literal["candidate", "evaluated", "approved", "staged", "retired"]

_FORWARD_TRANSITION: dict[str, str] = {
    "candidate": "evaluated",
    "evaluated": "approved",
    "approved": "staged",
    "staged": "retired",
}


class IllegalTransitionError(ValueError):
    """Raised for any transition `is_allowed_transition` rejects."""


class SinglePersonApprovalError(IllegalTransitionError):
    """CIQ-08: raised by `promote_to_approved` when `approved_by`
    equals `actor` -- the real, enforced half of "two-person approval"
    this registry can honestly make (see this module's own docstring
    for exactly what is, and is not, claimed by this check)."""


def is_allowed_transition(from_state: RegistryState, to_state: RegistryState) -> bool:
    if from_state == "retired":
        return False
    if to_state == "retired":
        return True
    return _FORWARD_TRANSITION.get(from_state) == to_state


@dataclass(frozen=True, slots=True)
class StateTransition:
    from_state: RegistryState
    to_state: RegistryState
    actor: str
    approved_by: str
    at: date
    reason: str
    content_hash: str | None = None


@dataclass(slots=True)
class ModelRegistryEntry:
    model_id: str
    state: RegistryState = field(default="candidate", init=False)
    history: list[StateTransition] = field(default_factory=list, init=False)

    def transition(
        self,
        to_state: RegistryState,
        actor: str,
        at: date,
        reason: str,
        *,
        approved_by: str,
        content_hash: str | None = None,
    ) -> None:
        if not actor:
            raise ValueError("actor must not be empty")
        if not approved_by:
            raise ValueError("approved_by must not be empty")
        if not reason:
            raise ValueError("reason must not be empty -- every transition is documented")
        if not is_allowed_transition(self.state, to_state):
            raise IllegalTransitionError(
                f"{self.model_id}: {self.state!r} -> {to_state!r} is not an allowed transition"
            )
        self.history.append(
            StateTransition(
                self.state, to_state, actor, approved_by, at, reason, content_hash
            )
        )
        self.state = to_state


def promote_to_approved(
    entry: ModelRegistryEntry,
    actor: str,
    approved_by: str,
    at: date,
    provenance: TrainingProvenanceManifest | None,
    validation_passed: bool | None,
    package: ModelPackage,
) -> None:
    if approved_by == actor:
        raise SinglePersonApprovalError(
            f"{entry.model_id}: approved_by must be a distinct identity from actor "
            f"(both were {actor!r}) -- a promotion cannot be self-approved"
        )
    missing = []
    if provenance is None:
        missing.append("training provenance manifest")
    if validation_passed is None:
        missing.append("validation result")
    elif not validation_passed:
        missing.append("a passing validation result (validation failed)")
    if missing:
        raise IllegalTransitionError(
            f"{entry.model_id}: cannot promote to approved, missing: {', '.join(missing)}"
        )
    entry.transition(
        "approved",
        actor,
        at,
        reason="training provenance and a passing validation are present",
        approved_by=approved_by,
        content_hash=package.content_hash,
    )
