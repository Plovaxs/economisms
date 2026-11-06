"""Deploy manifests, config and feature flags (CIQ-11: "store complete
deploy manifests, config and feature flags"; acceptance criterion:
"any deployment can be recreated from recorded artifacts").

`capture_deploy_manifest` bundles the real `service.application.
ServicePolicy` an instance of this service was actually configured
with (serialized via `dataclasses.asdict`, not re-described by hand),
a `feature_flags` mapping (this repository has no feature-flag system
of its own yet, so this is honestly empty, `{}`, in every deployment
this codebase can actually produce today -- the field is present and
captured per the acceptance criterion, not omitted merely because
nothing currently sets one), and `environment` (reusing `experiments.
manifest.runtime_provenance`, the same convention `experiments.
training_provenance`/`holdout_manifest` already use). `manifest_id` is
a `compute_result_hash` over all three.

"Any deployment can be recreated from recorded artifacts" is
demonstrated directly, not assumed from the manifest merely storing a
dict: `recreate_service_policy` reconstructs a `ServicePolicy` from a
captured manifest's own stored fields, and this module's own test file
confirms the reconstructed policy is equal, field for field, to the
ORIGINAL policy instance the manifest was captured from -- including a
non-default configuration, not just the all-defaults case, which could
otherwise pass trivially even if capture or reconstruction silently
dropped a field.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from prometheus.experiments.manifest import compute_result_hash, runtime_provenance
from prometheus.service.application import ServicePolicy


@dataclass(frozen=True, slots=True)
class DeployManifest:
    service_policy: Mapping[str, Any]
    feature_flags: Mapping[str, bool]
    environment: Mapping[str, Any]
    manifest_id: str


def capture_deploy_manifest(
    policy: ServicePolicy, feature_flags: Mapping[str, bool] | None = None
) -> DeployManifest:
    flags = dict(feature_flags) if feature_flags is not None else {}
    policy_dict = dataclasses.asdict(policy)
    environment = runtime_provenance()
    manifest_id = compute_result_hash(
        {"service_policy": policy_dict, "feature_flags": flags, "environment": environment}
    )
    return DeployManifest(
        service_policy=policy_dict,
        feature_flags=flags,
        environment=environment,
        manifest_id=manifest_id,
    )


def recreate_service_policy(manifest: DeployManifest) -> ServicePolicy:
    """Reconstructs a `ServicePolicy` from `manifest`'s own stored
    fields -- the actual "recreate a deployment from recorded
    artifacts" step, not merely a claim that the stored dict suffices."""
    return ServicePolicy(**manifest.service_policy)
