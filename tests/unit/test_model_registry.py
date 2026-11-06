from datetime import date

import pytest

from prometheus.evidence.model_package import build_model_package
from prometheus.evidence.model_registry import (
    IllegalTransitionError,
    ModelRegistryEntry,
    is_allowed_transition,
    promote_to_approved,
)
from prometheus.experiments.training_provenance import capture_training_provenance


def _manifest():
    return capture_training_provenance({"lr": 0.01}, seed=0)


def _package():
    return build_model_package("m1", "v1", b"model weights go here")


def test_a_new_entry_starts_as_candidate() -> None:
    entry = ModelRegistryEntry("m1")
    assert entry.state == "candidate"
    assert entry.history == []


@pytest.mark.parametrize(
    ("from_state", "to_state"),
    [
        ("candidate", "evaluated"),
        ("evaluated", "approved"),
        ("approved", "staged"),
        ("staged", "retired"),
    ],
)
def test_the_full_forward_path_is_allowed(from_state: str, to_state: str) -> None:
    assert is_allowed_transition(from_state, to_state)  # type: ignore[arg-type]


@pytest.mark.parametrize("from_state", ["candidate", "evaluated", "approved", "staged"])
def test_retirement_is_allowed_from_every_non_retired_state(from_state: str) -> None:
    """An emergency pull is legitimate at any stage, not only at the
    end of the normal forward path."""
    assert is_allowed_transition(from_state, "retired")  # type: ignore[arg-type]


def test_retired_is_terminal() -> None:
    assert not is_allowed_transition("retired", "evaluated")
    assert not is_allowed_transition("retired", "candidate")


@pytest.mark.parametrize(
    ("from_state", "to_state"),
    [
        ("candidate", "approved"),  # skips evaluated
        ("approved", "candidate"),  # backward
        ("staged", "candidate"),  # backward, skipping states
        ("evaluated", "staged"),  # skips approved
    ],
)
def test_illegal_transitions_are_rejected(from_state: str, to_state: str) -> None:
    """The discriminating half: skipping a state or moving backward is
    NOT allowed, distinguishing a real policy from one that merely
    permits everything."""
    assert not is_allowed_transition(from_state, to_state)  # type: ignore[arg-type]


def test_entry_transition_records_an_audit_trail_entry() -> None:
    entry = ModelRegistryEntry("m1")
    entry.transition(
        "evaluated", actor="alice", at=date(2026, 1, 1), reason="backtest complete",
        approved_by="alice",
    )
    assert entry.state == "evaluated"
    assert len(entry.history) == 1
    record = entry.history[0]
    assert record.from_state == "candidate"
    assert record.to_state == "evaluated"
    assert record.actor == "alice"
    assert record.reason == "backtest complete"


def test_entry_transition_raises_for_an_illegal_move() -> None:
    entry = ModelRegistryEntry("m1")
    with pytest.raises(IllegalTransitionError, match="not an allowed transition"):
        entry.transition(
            "approved", actor="alice", at=date(2026, 1, 1), reason="skip ahead",
            approved_by="alice",
        )


def test_entry_transition_rejects_an_empty_reason() -> None:
    entry = ModelRegistryEntry("m1")
    with pytest.raises(ValueError, match="reason"):
        entry.transition(
            "evaluated", actor="alice", at=date(2026, 1, 1), reason="", approved_by="alice"
        )


def test_entry_transition_rejects_an_empty_actor() -> None:
    entry = ModelRegistryEntry("m1")
    with pytest.raises(ValueError, match="actor"):
        entry.transition(
            "evaluated", actor="", at=date(2026, 1, 1), reason="x", approved_by="alice"
        )


def test_entry_transition_rejects_an_empty_approver() -> None:
    """AUD-06's own acceptance criterion: "identity, approval, previous
    state and hash recorded" -- approval is a required, non-empty field
    in its own right, not an afterthought to actor."""
    entry = ModelRegistryEntry("m1")
    with pytest.raises(ValueError, match="approved_by"):
        entry.transition(
            "evaluated", actor="alice", at=date(2026, 1, 1), reason="x", approved_by=""
        )


def test_a_rejected_transition_does_not_mutate_state_or_history() -> None:
    """A failed `transition()` call must leave the entry exactly as it
    was -- no partial/corrupted state update."""
    entry = ModelRegistryEntry("m1")
    with pytest.raises(IllegalTransitionError):
        entry.transition(
            "approved", actor="alice", at=date(2026, 1, 1), reason="skip ahead",
            approved_by="alice",
        )
    assert entry.state == "candidate"
    assert entry.history == []


def test_the_full_lifecycle_produces_a_complete_ordered_audit_trail() -> None:
    entry = ModelRegistryEntry("m1")
    entry.transition(
        "evaluated", "alice", date(2026, 1, 1), "backtest complete", approved_by="alice"
    )
    promote_to_approved(
        entry, "alice", "carol", date(2026, 1, 2), _manifest(), True, _package()
    )
    entry.transition(
        "staged", "bob", date(2026, 1, 3), "deployed to staging", approved_by="bob"
    )
    entry.transition("retired", "bob", date(2026, 1, 4), "superseded", approved_by="bob")
    assert entry.state == "retired"
    assert [(t.from_state, t.to_state) for t in entry.history] == [
        ("candidate", "evaluated"),
        ("evaluated", "approved"),
        ("approved", "staged"),
        ("staged", "retired"),
    ]


def test_every_transition_records_identity_approval_previous_state_and_hash() -> None:
    """AUD-06, stated explicitly across a full lifecycle: every one of
    its four named fields -- identity (actor), approval (approved_by,
    a genuinely DIFFERENT person here), previous state (from_state) and
    hash (content_hash, on the promotion specifically) -- is present on
    the transitions where each applies."""
    entry = ModelRegistryEntry("m1")
    entry.transition(
        "evaluated", "alice", date(2026, 1, 1), "backtest complete", approved_by="alice"
    )
    package = _package()
    promote_to_approved(entry, "alice", "carol", date(2026, 1, 2), _manifest(), True, package)

    evaluated_transition, approved_transition = entry.history
    assert evaluated_transition.actor == "alice"
    assert evaluated_transition.approved_by == "alice"
    assert evaluated_transition.from_state == "candidate"
    assert evaluated_transition.content_hash is None  # no package exists yet at this stage

    assert approved_transition.actor == "alice"
    assert approved_transition.approved_by == "carol"  # a genuinely distinct approver
    assert approved_transition.from_state == "evaluated"
    assert approved_transition.content_hash == package.content_hash


def test_promote_to_approved_denies_a_candidate_missing_provenance() -> None:
    """MLO-10's own acceptance criterion: "promotion gate test denies
    incomplete candidates" -- missing provenance alone must block."""
    entry = ModelRegistryEntry("m1")
    entry.transition(
        "evaluated", "alice", date(2026, 1, 1), "backtest complete", approved_by="alice"
    )
    with pytest.raises(IllegalTransitionError, match="training provenance manifest"):
        promote_to_approved(
            entry, "alice", "carol", date(2026, 1, 2), None, True, _package()
        )
    assert entry.state == "evaluated"  # unchanged


def test_promote_to_approved_denies_a_candidate_with_no_validation_result() -> None:
    entry = ModelRegistryEntry("m1")
    entry.transition(
        "evaluated", "alice", date(2026, 1, 1), "backtest complete", approved_by="alice"
    )
    with pytest.raises(IllegalTransitionError, match="validation result"):
        promote_to_approved(
            entry, "alice", "carol", date(2026, 1, 2), _manifest(), None, _package()
        )


def test_promote_to_approved_denies_a_candidate_that_failed_validation() -> None:
    entry = ModelRegistryEntry("m1")
    entry.transition(
        "evaluated", "alice", date(2026, 1, 1), "backtest complete", approved_by="alice"
    )
    with pytest.raises(IllegalTransitionError, match="failed"):
        promote_to_approved(
            entry, "alice", "carol", date(2026, 1, 2), _manifest(), False, _package()
        )
    assert entry.state == "evaluated"


def test_promote_to_approved_still_enforces_the_underlying_state_machine() -> None:
    """A complete, passing manifest+validation does NOT bypass the
    transition policy itself -- a candidate that was never evaluated
    must still be denied."""
    entry = ModelRegistryEntry("m1")
    with pytest.raises(IllegalTransitionError, match="not an allowed transition"):
        promote_to_approved(
            entry, "alice", "carol", date(2026, 1, 1), _manifest(), True, _package()
        )
    assert entry.state == "candidate"


def test_promote_to_approved_succeeds_when_everything_is_present() -> None:
    entry = ModelRegistryEntry("m1")
    entry.transition(
        "evaluated", "alice", date(2026, 1, 1), "backtest complete", approved_by="alice"
    )
    promote_to_approved(
        entry, "alice", "carol", date(2026, 1, 2), _manifest(), True, _package()
    )
    assert entry.state == "approved"
    assert entry.history[-1].to_state == "approved"
