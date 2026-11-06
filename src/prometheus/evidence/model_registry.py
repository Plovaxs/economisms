"""Model registry states, a code-enforced transition policy, and a
promotion gate (MLO-08: "create registry states: candidate/evaluated/
approved/staged/retired"; acceptance criterion: "transition policy
enforced by code and audit trail". MLO-10: "block deployment for
missing provenance or validation"; acceptance criterion: "promotion
gate test denies incomplete candidates").

`ModelRegistryEntry` holds exactly the five states MLO-08 names and a
complete, append-only `history` of every `StateTransition` it has ever
undergone (actor, timestamp and a required `reason` -- the audit trail
half of the acceptance criterion). The transition policy itself
(`is_allowed_transition`) is a pure function, not merely documented in
prose: `candidate -> evaluated -> approved -> staged -> retired` is the
only forward path, and any non-retired state may additionally move
directly to `retired` (an emergency pull is legitimate at any stage);
every other transition, including any backward move, is rejected with
`IllegalTransitionError`.

`promote_to_approved` layers MLO-10's gate ON TOP of that same
transition policy rather than duplicating it: it still calls
`entry.transition("approved", ...)`, so an entry not already in the
`evaluated` state is rejected by the policy exactly as any other
illegal transition would be, but it ADDITIONALLY requires both a
`training_provenance.TrainingProvenanceManifest` (reused from AUD-03,
not reinvented) and a passing validation result before even attempting
that transition -- "block deployment for missing provenance or
validation," checked directly, not assumed from the state machine
alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

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
    at: date
    reason: str


@dataclass(slots=True)
class ModelRegistryEntry:
    model_id: str
    state: RegistryState = field(default="candidate", init=False)
    history: list[StateTransition] = field(default_factory=list, init=False)

    def transition(self, to_state: RegistryState, actor: str, at: date, reason: str) -> None:
        if not actor:
            raise ValueError("actor must not be empty")
        if not reason:
            raise ValueError("reason must not be empty -- every transition is documented")
        if not is_allowed_transition(self.state, to_state):
            raise IllegalTransitionError(
                f"{self.model_id}: {self.state!r} -> {to_state!r} is not an allowed transition"
            )
        self.history.append(StateTransition(self.state, to_state, actor, at, reason))
        self.state = to_state


def promote_to_approved(
    entry: ModelRegistryEntry,
    actor: str,
    at: date,
    provenance: TrainingProvenanceManifest | None,
    validation_passed: bool | None,
) -> None:
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
        "approved", actor, at, reason="training provenance and a passing validation are present"
    )
