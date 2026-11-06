import hashlib
import json
import os

import pytest

from prometheus.service.__main__ import provision_credentials
from prometheus.service.auth import AuthenticationError, CredentialStore, CredentialUnavailable


def binding(token="a" * 43, owner="alice", scopes=None):
    return {
        "subject": owner,
        "owner": owner,
        "scopes": scopes or ["read", "write"],
        "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
    }


def write_credentials(path, entries=None):
    path.write_text(json.dumps({"schema_version": 1, "credentials": entries or [binding()]}))
    path.chmod(0o600)
    return path


def test_private_hash_credentials_scope_and_rotation_without_server_restart(tmp_path):
    path = write_credentials(tmp_path / "auth.json")
    store = CredentialStore(path)
    assert store.authenticate("Bearer " + "a" * 43).owner == "alice"
    replacement = write_credentials(tmp_path / "replacement", [binding("b" * 43, "bob", ["read"])])
    replacement.replace(path)
    with pytest.raises(AuthenticationError):
        store.authenticate("Bearer " + "a" * 43)
    principal = store.authenticate("Bearer " + "b" * 43)
    assert principal.owner == "bob" and principal.scopes == frozenset({"read"})
    assert "a" * 43 not in path.read_text()


@pytest.mark.parametrize(
    "header",
    [
        None,
        "",
        "Basic credentials",
        "Bearer short",
        "Bearer " + "x" * 129,
        "Bearer " + "é" * 43,
        "Bearer " + "b" * 43,
    ],
)
def test_denied_credentials_do_not_appear_in_exception(tmp_path, header):
    store = CredentialStore(write_credentials(tmp_path / "auth"))
    with pytest.raises(AuthenticationError, match="valid bearer credentials") as exc:
        store.authenticate(header)
    assert "credentials" in str(exc.value) and "b" * 43 not in str(exc.value)


def test_credential_reader_rejects_public_files_symlinks_deleted_and_oversized(tmp_path):
    path = write_credentials(tmp_path / "auth")
    path.chmod(0o644)
    with pytest.raises(CredentialUnavailable):
        CredentialStore(path)
    path.chmod(0o600)
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(CredentialUnavailable):
        CredentialStore(link)
    store = CredentialStore(path)
    path.unlink()
    with pytest.raises(CredentialUnavailable):
        store.check_ready()
    path.write_bytes(b" " * 65537)
    path.chmod(0o600)
    with pytest.raises(CredentialUnavailable):
        store.check_ready()


def test_fifo_credentials_are_rejected_without_waiting_for_a_writer(tmp_path):
    path = tmp_path / "fifo"
    os.mkfifo(path, 0o600)
    with pytest.raises(CredentialUnavailable):
        CredentialStore(path)


@pytest.mark.parametrize(
    "change",
    [
        lambda x: x.update(schema_version=True),
        lambda x: x.update(extra="forbidden"),
        lambda x: x.update(credentials=[]),
        lambda x: x["credentials"].append(dict(x["credentials"][0])),
        lambda x: x["credentials"][0].update(scopes=["write"]),
        lambda x: x["credentials"][0].update(scopes=["read", "admin"]),
        lambda x: x["credentials"][0].update(scopes=["read", "read"]),
        lambda x: x["credentials"][0].update(owner="unsafe owner"),
        lambda x: x["credentials"][0].update(token_sha256="not-a-digest"),
    ],
)
def test_credential_schema_fails_closed(tmp_path, change):
    data = {"schema_version": 1, "credentials": [binding()]}
    change(data)
    path = tmp_path / "auth"
    path.write_text(json.dumps(data))
    path.chmod(0o600)
    with pytest.raises(CredentialUnavailable):
        CredentialStore(path)


def test_provisioning_never_clobbers_or_prints_secrets_and_sets_private_modes(tmp_path):
    credentials, token_file = tmp_path / "auth", tmp_path / "token"
    provision_credentials(credentials, token_file, owner="alice", read_only=True)
    token = token_file.read_text().strip()
    assert len(token) == 43
    assert token not in credentials.read_text()
    assert token_file.stat().st_mode & 0o777 == credentials.stat().st_mode & 0o777 == 0o600
    assert CredentialStore(credentials).authenticate("Bearer " + token).scopes == frozenset(
        {"read"}
    )
    with pytest.raises(FileExistsError):
        provision_credentials(credentials, tmp_path / "other-token", owner="alice", read_only=False)
    assert not (tmp_path / "other-token").exists()
    assert token_file.read_text().strip() == token
