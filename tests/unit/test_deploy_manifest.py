import dataclasses
from datetime import date

import pytest

from prometheus.service.application import ServicePolicy
from prometheus.service.deploy_manifest import (
    BreakingChangeNotice,
    DeployManifest,
    capture_deploy_manifest,
    recreate_service_policy,
)


def _real_notice(**overrides: object) -> BreakingChangeNotice:
    defaults: dict[str, object] = dict(
        change_description="service.schema API_VERSION bumped to 2.0.0, field X renamed",
        affected_clients=("internal-research-cli", "service.client users"),
        change_log_url="https://github.com/Plovaxs/economisms/blob/main/docs/PR_LEDGER.md",
        maintenance_window_start=date(2026, 12, 1),
        maintenance_window_end=date(2026, 12, 1),
        owner_approved_by="project maintainer",
    )
    defaults.update(overrides)
    return BreakingChangeNotice(**defaults)  # type: ignore[arg-type]


def test_a_breaking_change_notice_requires_at_least_one_affected_client() -> None:
    with pytest.raises(ValueError, match="affected_clients"):
        _real_notice(affected_clients=())


def test_a_breaking_change_notice_requires_change_log_url_and_owner_approval() -> None:
    with pytest.raises(ValueError, match="change_log_url"):
        _real_notice(change_log_url="")
    with pytest.raises(ValueError, match="owner_approved_by"):
        _real_notice(owner_approved_by="")


def test_maintenance_window_end_cannot_precede_its_start() -> None:
    with pytest.raises(ValueError, match="cannot precede"):
        _real_notice(
            maintenance_window_start=date(2026, 12, 5),
            maintenance_window_end=date(2026, 12, 1),
        )


def test_a_valid_breaking_change_notice_constructs_cleanly() -> None:
    notice = _real_notice()
    assert notice.affected_clients == ("internal-research-cli", "service.client users")
    assert notice.owner_approved_by == "project maintainer"


def test_capture_deploy_manifest_defaults_feature_flags_to_empty() -> None:
    """This repository has no feature-flag system of its own yet, so an
    honestly empty mapping is the correct default -- present and
    captured, not omitted."""
    manifest = capture_deploy_manifest(ServicePolicy())
    assert manifest.feature_flags == {}


def test_capture_deploy_manifest_carries_supplied_feature_flags() -> None:
    manifest = capture_deploy_manifest(ServicePolicy(), feature_flags={"new_pricer": True})
    assert manifest.feature_flags == {"new_pricer": True}


def test_capture_deploy_manifest_reports_the_policy_and_environment() -> None:
    policy = ServicePolicy(max_body_bytes=2048, max_inflight=4)
    manifest = capture_deploy_manifest(policy)
    assert manifest.service_policy == dataclasses.asdict(policy)
    assert set(manifest.environment) == {"python", "platform", "dependencies", "source_sha256"}


def test_manifest_is_immutable() -> None:
    manifest = capture_deploy_manifest(ServicePolicy())
    with pytest.raises(dataclasses.FrozenInstanceError):
        manifest.manifest_id = "tampered"  # type: ignore[misc]


def test_manifest_id_is_deterministic_for_an_identical_policy_and_flags() -> None:
    m1 = capture_deploy_manifest(ServicePolicy(max_inflight=4), feature_flags={"a": True})
    m2 = capture_deploy_manifest(ServicePolicy(max_inflight=4), feature_flags={"a": True})
    assert m1.manifest_id == m2.manifest_id


def test_manifest_id_differs_for_a_different_policy() -> None:
    """The discriminating half: the policy is part of what is being
    captured, so changing even one of its fields must change the id."""
    m1 = capture_deploy_manifest(ServicePolicy(max_inflight=4))
    m2 = capture_deploy_manifest(ServicePolicy(max_inflight=5))
    assert m1.manifest_id != m2.manifest_id


def test_manifest_id_differs_for_different_feature_flags() -> None:
    m1 = capture_deploy_manifest(ServicePolicy(), feature_flags={"a": True})
    m2 = capture_deploy_manifest(ServicePolicy(), feature_flags={"a": False})
    assert m1.manifest_id != m2.manifest_id


def test_recreated_default_policy_matches_the_original() -> None:
    policy = ServicePolicy()
    manifest = capture_deploy_manifest(policy)
    assert recreate_service_policy(manifest) == policy


def test_recreated_non_default_policy_matches_the_original() -> None:
    """CIQ-11's own acceptance criterion: "any deployment can be
    recreated from recorded artifacts" -- confirmed against a
    NON-default configuration, not just all-defaults, which could
    otherwise pass trivially even if capture or reconstruction had
    silently dropped a field back to its default."""
    policy = ServicePolicy(
        max_body_bytes=2048,
        max_header_bytes=8192,
        max_headers=32,
        max_inflight=2,
        requests_per_owner=10,
        requests_global=100,
        rate_window_seconds=30.0,
        body_timeout_seconds=5.0,
        allow_loopback_http=False,
    )
    manifest = capture_deploy_manifest(policy, feature_flags={"canary": True})
    recreated = recreate_service_policy(manifest)
    assert recreated == policy
    assert recreated is not policy


def test_deploy_manifest_type_is_constructible_directly() -> None:
    manifest = DeployManifest(
        service_policy={"max_inflight": 8}, feature_flags={}, environment={}, manifest_id="abc"
    )
    assert manifest.manifest_id == "abc"
