import json

import pytest

from prometheus.evidence.contracts import read_evidence_bundle
from prometheus.experiments.manifest import json_default
from prometheus.jobs.__main__ import main
from prometheus.orchestration.recipes import default_recipe


def test_cli_submits_runs_reads_and_exports_an_owned_research_job(tmp_path, capsys):
    root = tmp_path / "state"
    recipe = tmp_path / "recipe.json"
    config = default_recipe("economy")
    config.update(n_steps=2, productivity_shock_step=2)
    recipe.write_text(json.dumps(config, default=json_default))
    prefix = ["--root", str(root)]
    assert (
        main(
            prefix
            + [
                "submit",
                "--owner",
                "alice",
                "--kind",
                "economy",
                "--recipe",
                str(recipe),
                "--idempotency-key",
                "example",
            ]
        )
        == 0
    )
    submitted = json.loads(capsys.readouterr().out)
    assert submitted["status"] == "queued"
    assert "config_json" not in submitted and "lease_token" not in submitted
    assert main(prefix + ["work", "--once", "--worker-id", "one"]) == 0
    completed = json.loads(capsys.readouterr().out)["job"]
    assert completed["status"] == "succeeded"
    assert main(prefix + ["list", "--owner", "alice", "--limit", "1"]) == 0
    assert len(json.loads(capsys.readouterr().out)["jobs"]) == 1
    output = tmp_path / "result.json"
    assert (
        main(
            prefix + ["artifact", submitted["job_id"], "--owner", "alice", "--output", str(output)]
        )
        == 0
    )
    receipt = json.loads(capsys.readouterr().out)
    artifact = read_evidence_bundle(output, require_integrity=True)
    assert artifact["artifact_integrity"]["content_sha256"] == receipt["artifact_sha256"]
    assert artifact["job_context"]["trace_id"] == submitted["trace_id"]
    with pytest.raises(SystemExit):
        main(prefix + ["show", submitted["job_id"], "--owner", "bob"])
    assert "job not found" in capsys.readouterr().err
    assert main(prefix + ["audit"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["valid"]
    assert main(prefix + ["audit", "--expected-head-sha256", report["audit_head_sha256"]]) == 0
    assert json.loads(capsys.readouterr().out)["valid"]
