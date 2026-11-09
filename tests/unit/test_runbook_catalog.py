import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from prometheus.evidence.numerical_event_monitor import monitor_call
from prometheus.evidence.runbook_catalog import (
    DrillStep,
    run_credential_compromise_drill,
    run_numerical_integrity_drill,
)
from prometheus.service.auth import CredentialStore

OLD_TOKEN = "a" * 43
NEW_TOKEN = "b" * 43


class _Clock:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> datetime:
        self.calls += 1
        return datetime(2026, 1, 1) + timedelta(seconds=self.calls)


def test_drill_step_rejects_an_empty_name() -> None:
    with pytest.raises(ValueError, match="name"):
        DrillStep(name="", at=datetime(2026, 1, 1), detail="x")


def test_drill_step_rejects_an_empty_detail() -> None:
    with pytest.raises(ValueError, match="detail"):
        DrillStep(name="x", at=datetime(2026, 1, 1), detail="")


def test_a_recovering_numerical_integrity_drill_passes_with_a_real_timeline() -> None:
    state = {"calls": 0}

    def flaky() -> None:
        state["calls"] += 1
        if state["calls"] <= 1:
            raise RuntimeError("transient failure")

    event = monitor_call(flaky, owner="quant-oncall")
    assert event is not None

    clock = _Clock()
    report = run_numerical_integrity_drill(event, flaky, clock=clock)

    assert report.category == "solver_failure"
    assert report.passed is True
    assert [step.name for step in report.timeline] == ["isolate", "invalidate", "re_evaluate"]
    timestamps = [step.at for step in report.timeline]
    assert timestamps == sorted(timestamps)


def test_a_persistently_failing_numerical_integrity_drill_does_not_pass() -> None:
    def always_fails() -> None:
        raise RuntimeError("the solver diverged")

    event = monitor_call(always_fails, owner="quant-oncall")
    assert event is not None
    clock = _Clock()
    report = run_numerical_integrity_drill(event, always_fails, clock=clock)
    assert report.passed is False


def _auth_entry(token: str, owner: str) -> dict:
    return {
        "subject": owner,
        "owner": owner,
        "scopes": ["read", "write"],
        "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
    }


def _write_credentials(path: Path, *entries: dict) -> None:
    path.write_text(json.dumps({"schema_version": 1, "credentials": list(entries)}))
    path.chmod(0o600)


def test_a_real_credential_compromise_drill_passes_with_a_real_timeline(tmp_path: Path) -> None:
    path = tmp_path / "credentials.json"
    _write_credentials(path, _auth_entry(OLD_TOKEN, "alice"))
    store = CredentialStore(path)
    clock = _Clock()

    report = run_credential_compromise_drill(
        store,
        path,
        old_token_sha256=hashlib.sha256(OLD_TOKEN.encode()).hexdigest(),
        new_subject="alice",
        new_owner="alice",
        new_scopes=["read", "write"],
        new_token_sha256=hashlib.sha256(NEW_TOKEN.encode()).hexdigest(),
        old_authorization_header=f"Bearer {OLD_TOKEN}",
        new_authorization_header=f"Bearer {NEW_TOKEN}",
        clock=clock,
    )

    assert report.category == "credential_compromise"
    assert report.passed is True
    assert [step.name for step in report.timeline] == [
        "isolate_and_rotate", "verify_old_rejected", "verify_new_accepted",
    ]
    timestamps = [step.at for step in report.timeline]
    assert timestamps == sorted(timestamps)
    assert len(set(timestamps)) == len(timestamps)

    # Direct confirmation the rotation genuinely happened.
    assert store.authenticate(f"Bearer {NEW_TOKEN}").owner == "alice"


def test_a_credential_compromise_drill_checked_against_the_wrong_new_token_does_not_pass(
    tmp_path: Path,
) -> None:
    """The discriminating half: `passed` is a real outcome, not a
    constant -- verifying against a token that was never actually
    provisioned must fail the drill."""
    path = tmp_path / "credentials.json"
    _write_credentials(path, _auth_entry(OLD_TOKEN, "alice"))
    store = CredentialStore(path)
    clock = _Clock()
    never_provisioned_token = "z" * 43

    report = run_credential_compromise_drill(
        store,
        path,
        old_token_sha256=hashlib.sha256(OLD_TOKEN.encode()).hexdigest(),
        new_subject="alice",
        new_owner="alice",
        new_scopes=["read", "write"],
        new_token_sha256=hashlib.sha256(NEW_TOKEN.encode()).hexdigest(),
        old_authorization_header=f"Bearer {OLD_TOKEN}",
        new_authorization_header=f"Bearer {never_provisioned_token}",
        clock=clock,
    )
    assert report.passed is False
