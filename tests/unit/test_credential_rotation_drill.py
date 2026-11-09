import hashlib
import json
from pathlib import Path

import pytest

from prometheus.evidence.credential_rotation_drill import (
    RotationDrillResult,
    rotate_credential,
    run_credential_rotation_drill,
)
from prometheus.service.auth import AuthenticationError, CredentialStore

OLD_TOKEN = "a" * 43
NEW_TOKEN = "b" * 43


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


def test_result_passed_requires_both_conditions() -> None:
    assert RotationDrillResult(old_token_rejected=True, new_token_authenticates=True).passed
    assert not RotationDrillResult(old_token_rejected=False, new_token_authenticates=True).passed
    assert not RotationDrillResult(old_token_rejected=True, new_token_authenticates=False).passed


def test_a_real_rotation_rejects_the_old_token_and_accepts_the_new_one(tmp_path: Path) -> None:
    """A REAL end-to-end drill against `service.auth.CredentialStore`:
    the old token works before rotation, is genuinely rejected after
    rotation, and the new token genuinely authenticates."""
    path = tmp_path / "credentials.json"
    _write_credentials(path, _auth_entry(OLD_TOKEN, "alice"))
    store = CredentialStore(path)

    # Sanity: the old token really does authenticate before rotation.
    principal_before = store.authenticate(f"Bearer {OLD_TOKEN}")
    assert principal_before.owner == "alice"

    rotate_credential(
        path,
        old_token_sha256=hashlib.sha256(OLD_TOKEN.encode()).hexdigest(),
        new_subject="alice",
        new_owner="alice",
        new_scopes=["read", "write"],
        new_token_sha256=hashlib.sha256(NEW_TOKEN.encode()).hexdigest(),
    )

    result = run_credential_rotation_drill(
        store,
        old_authorization_header=f"Bearer {OLD_TOKEN}",
        new_authorization_header=f"Bearer {NEW_TOKEN}",
    )
    assert result.passed is True
    assert result.old_token_rejected is True
    assert result.new_token_authenticates is True

    # Direct confirmation, not just the drill's own report.
    with pytest.raises(AuthenticationError):
        store.authenticate(f"Bearer {OLD_TOKEN}")
    assert store.authenticate(f"Bearer {NEW_TOKEN}").owner == "alice"


def test_an_unrotated_credential_fails_the_drill_old_token_still_works(tmp_path: Path) -> None:
    """The discriminating half: without actually rotating, the drill
    must correctly report the old token as NOT rejected -- confirming
    the drill genuinely checks real authentication behavior rather
    than always reporting success."""
    path = tmp_path / "credentials.json"
    _write_credentials(path, _auth_entry(OLD_TOKEN, "alice"))
    store = CredentialStore(path)

    result = run_credential_rotation_drill(
        store,
        old_authorization_header=f"Bearer {OLD_TOKEN}",
        new_authorization_header=f"Bearer {NEW_TOKEN}",
    )
    assert result.old_token_rejected is False
    assert result.new_token_authenticates is False
    assert result.passed is False


def test_rotation_preserves_other_unrelated_credentials(tmp_path: Path) -> None:
    """Rotating alice's credential must not disturb bob's."""
    bob_token = "c" * 43
    path = tmp_path / "credentials.json"
    _write_credentials(path, _auth_entry(OLD_TOKEN, "alice"), _auth_entry(bob_token, "bob"))
    store = CredentialStore(path)

    rotate_credential(
        path,
        old_token_sha256=hashlib.sha256(OLD_TOKEN.encode()).hexdigest(),
        new_subject="alice",
        new_owner="alice",
        new_scopes=["read", "write"],
        new_token_sha256=hashlib.sha256(NEW_TOKEN.encode()).hexdigest(),
    )

    assert store.authenticate(f"Bearer {bob_token}").owner == "bob"
    assert store.authenticate(f"Bearer {NEW_TOKEN}").owner == "alice"
    with pytest.raises(AuthenticationError):
        store.authenticate(f"Bearer {OLD_TOKEN}")


def test_rotate_credential_rejects_a_malformed_credential_file(tmp_path: Path) -> None:
    path = tmp_path / "credentials.json"
    path.write_text(json.dumps({"not": "the right schema"}))
    with pytest.raises(ValueError, match="schema"):
        rotate_credential(
            path,
            old_token_sha256="0" * 64,
            new_subject="a",
            new_owner="a",
            new_scopes=["read"],
            new_token_sha256="1" * 64,
        )
