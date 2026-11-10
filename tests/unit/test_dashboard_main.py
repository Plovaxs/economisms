"""Only the `init-auth` path is unit-tested here -- `serve` starts a
real uvicorn network listener, which this repository's hermetic test
discipline deliberately does not do in `pytest` (the same reason
`service.__main__`'s own `serve` subcommand has no dedicated test
file either); `serve` was instead verified by actually running it
(`python -m prometheus.dashboard serve --demo`) and hitting every real
route with a real HTTP client before this PR was recorded -- see
`CHECKLIST_STATUS.md`'s PR-161 entry for the real bug that real run
caught (a missing ASGI lifespan handler) that no unit test alone
would have found.
"""

from __future__ import annotations

import json

import pytest

from prometheus.dashboard.__main__ import main


def test_init_auth_writes_real_credential_and_token_files(tmp_path) -> None:
    credentials = tmp_path / "auth.json"
    token_file = tmp_path / "token"
    exit_code = main(
        [
            "init-auth",
            "--credentials", str(credentials),
            "--token-file", str(token_file),
            "--owner", "demo-viewer",
        ]
    )
    assert exit_code == 0
    assert credentials.exists()
    assert token_file.exists()
    config = json.loads(credentials.read_text())
    assert config["credentials"][0]["owner"] == "demo-viewer"
    assert config["credentials"][0]["scopes"] == ["read"]
    token = token_file.read_text().strip()
    assert len(token) > 20  # a real random token, not a placeholder


def test_init_auth_refuses_to_overwrite_existing_credentials(tmp_path) -> None:
    credentials = tmp_path / "auth.json"
    token_file = tmp_path / "token"
    main(
        [
            "init-auth",
            "--credentials", str(credentials),
            "--token-file", str(token_file),
            "--owner", "demo-viewer",
        ]
    )
    with pytest.raises(SystemExit):
        main(
            [
                "init-auth",
                "--credentials", str(credentials),
                "--token-file", str(token_file),
                "--owner", "someone-else",
            ]
        )
