import dataclasses

import pytest

from prometheus.evidence.tamper_evident_log import TamperEvidenceError, TamperEvidentLog


def test_append_returns_a_sequential_entry() -> None:
    log = TamperEvidentLog()
    entry = log.append({"action": "credential_added", "subject": "alice"})
    assert entry.seq == 1
    assert entry.previous_sha256 == "0" * 64


def test_a_second_entry_chains_to_the_first() -> None:
    log = TamperEvidentLog()
    first = log.append({"action": "credential_added", "subject": "alice"})
    second = log.append({"action": "credential_removed", "subject": "bob"})
    assert second.seq == 2
    assert second.previous_sha256 == first.event_sha256


def test_verify_passes_on_an_untouched_access_control_and_privileged_action_log() -> None:
    """AUD-07's own framing: a real sequence of access-control changes
    and privileged actions, chained and verified."""
    log = TamperEvidentLog()
    log.append({"action": "credential_added", "subject": "alice", "scopes": ["read", "write"]})
    log.append({"action": "credential_removed", "subject": "bob"})
    log.append({"action": "job_cancelled", "actor": "admin", "job_id": "job-42"})
    head = log.verify()
    assert len(head) == 64


def test_verify_is_deterministic_for_the_same_sequence_of_events() -> None:
    def build() -> TamperEvidentLog:
        log = TamperEvidentLog()
        log.append({"action": "credential_added", "subject": "alice"})
        log.append({"action": "credential_removed", "subject": "bob"})
        return log

    assert build().verify() == build().verify()


def test_verify_detects_a_direct_tamper_of_a_middle_entrys_event() -> None:
    """The discriminating half -- "tamper-evident," proven, not
    assumed: directly replacing a stored entry's event content (as an
    attacker editing history would, bypassing `append` entirely) must
    be caught by re-deriving hashes from scratch, not by trusting the
    stored `event_sha256` values."""
    log = TamperEvidentLog()
    log.append({"action": "credential_added", "subject": "alice"})
    log.append({"action": "credential_removed", "subject": "bob"})
    log.append({"action": "job_cancelled", "actor": "admin", "job_id": "job-42"})

    log.entries[1] = dataclasses.replace(
        log.entries[1], event={"action": "credential_removed", "subject": "NOT_BOB"}
    )
    with pytest.raises(TamperEvidenceError, match="seq=2"):
        log.verify()


def test_verify_detects_a_forged_hash_that_matches_the_tampered_content() -> None:
    """A more sophisticated tamper: the attacker also recomputes
    `event_sha256` to match the forged content (so the entry looks
    internally consistent on its own) -- must still be caught, because
    it no longer chains correctly from the PRECEDING entry's real hash."""
    log = TamperEvidentLog()
    log.append({"action": "credential_added", "subject": "alice"})
    log.append({"action": "credential_removed", "subject": "bob"})

    forged = TamperEvidentLog()
    forged_entry = forged.append({"action": "credential_removed", "subject": "NOT_BOB"})
    log.entries[1] = dataclasses.replace(log.entries[1], event=forged_entry.event)
    # restamp with a self-consistent (but chain-inconsistent) hash of the forged content
    log.entries[1] = dataclasses.replace(
        log.entries[1], event_sha256=forged_entry.event_sha256
    )
    with pytest.raises(TamperEvidenceError, match="seq=2"):
        log.verify()


def test_truncating_the_log_changes_the_verified_head() -> None:
    """Deleting the most recent entries (another way to tamper with
    retention) is detectable as a different, shorter chain with a
    different head -- a caller comparing against a previously recorded
    head would notice."""
    log = TamperEvidentLog()
    log.append({"action": "credential_added", "subject": "alice"})
    full_head = log.verify()
    log.entries.pop()
    assert log.verify() != full_head


def test_an_empty_log_verifies_to_the_genesis_hash() -> None:
    log = TamperEvidentLog()
    assert log.verify() == "0" * 64
