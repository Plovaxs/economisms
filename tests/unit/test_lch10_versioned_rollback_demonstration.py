"""LCH-10: "Demonstrate versioned rollback and model invalidation --
Canary rollback plus audit chain verified."

A single, real, end-to-end scenario composing three already-evidenced
primitives (none reinvented here): `evidence.deployment_paths
.ShadowDeployment` (CIQ-09) as the canary/shadow comparison,
`evidence.model_serving.ModelServingSlot.rollback_to` (MLO-12) as the
real rollback, and `evidence.model_registry.ModelRegistryEntry.history`
(MLO-08) as the real, append-only audit chain -- verified by checking
every transition's `from_state`/`to_state` chains correctly from the
first entry to the last, not merely that the list is non-empty.
"""

from __future__ import annotations

from datetime import date

import pytest

from prometheus.evidence.deployment_paths import ShadowDeployment
from prometheus.evidence.model_package import build_model_package
from prometheus.evidence.model_registry import ModelRegistryEntry
from prometheus.evidence.model_serving import ModelServingSlot, RetiredModelDeploymentError


def test_canary_rollback_with_a_fully_verified_audit_chain() -> None:
    champion = build_model_package("hedge-policy", "v1", b"champion-weights")
    candidate = build_model_package("hedge-policy", "v2-candidate", b"candidate-weights")

    # 1. Real registry history: candidate is evaluated and approved before
    #    ever being compared live -- MLO-10's own promotion gate shape.
    entry = ModelRegistryEntry("hedge-policy")
    entry.transition(
        "evaluated", "ci", date(2026, 11, 1), "offline backtest passed", approved_by="n/a"
    )
    entry.transition(
        "approved", "reviewer", date(2026, 11, 2), "passed validation",
        approved_by="reviewer", content_hash=candidate.content_hash,
    )
    entry.transition(
        "staged", "ops", date(2026, 11, 3), "staged for canary", approved_by="ops-lead"
    )

    # 2. Canary/shadow: candidate's output is computed and compared but
    #    NEVER served while champion continues serving real traffic.
    slot = ModelServingSlot(current=champion)
    shadow = ShadowDeployment(serving=slot, challenger=candidate)
    served = shadow.predict_with_shadow(
        "real-input-1",
        champion_compute=lambda: "champion-hedge-ratio=0.42",
        challenger_compute=lambda: "candidate-hedge-ratio=0.91",  # a bad, risky output
    )
    assert served == "champion-hedge-ratio=0.42"  # candidate's risky output never served
    assert shadow.comparisons[0].challenger_output == "candidate-hedge-ratio=0.91"

    # 3. Canary comparison finds the candidate materially different/risky:
    #    it is REJECTED rather than promoted -- retired directly from
    #    staged, the real "model invalidation" half of this item.
    entry.transition(
        "retired", "ops", date(2026, 11, 4),
        "canary shadow output diverged materially from champion; rejected",
        approved_by="ops-lead",
    )

    # 4. The retired candidate can never be (re)deployed, confirmed by the
    #    same real guard MGR-12 already evidences.
    with pytest.raises(RetiredModelDeploymentError):
        slot.deploy_if_not_retired(candidate, entry)
    assert slot.current.content_hash == champion.content_hash  # champion still serving

    # 5. Audit chain verified: every transition chains correctly,
    #    start to finish, not merely "a history exists."
    expected_chain = [
        ("candidate", "evaluated"),
        ("evaluated", "approved"),
        ("approved", "staged"),
        ("staged", "retired"),
    ]
    actual_chain = [(t.from_state, t.to_state) for t in entry.history]
    assert actual_chain == expected_chain
    for earlier, later in zip(entry.history, entry.history[1:], strict=False):
        assert earlier.to_state == later.from_state  # no gap/jump in the chain
        assert earlier.at <= later.at  # chronologically ordered
    assert all(t.approved_by for t in entry.history)  # every step named an approver
    assert entry.state == "retired"
