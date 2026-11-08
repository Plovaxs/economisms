import numpy as np
import pytest
import torch

from prometheus.evidence.reproducible_inference import (
    InputContract,
    ReferenceCase,
    verify_reproducible_inference,
)
from prometheus.hedging.deep_hedge import HedgePolicyMLP


def _real_policy_infer_fn():
    """A real trained (seeded, deterministic) HedgePolicyMLP, not a
    stub -- the same policy class `evidence.model_package`'s own test
    file grounds its content-hashing demonstration in."""
    torch.manual_seed(0)
    policy = HedgePolicyMLP()
    policy.eval()

    def infer(features: np.ndarray) -> float:
        with torch.no_grad():
            tensor = torch.tensor(features, dtype=torch.float32).unsqueeze(0)
            return float(policy(tensor).item())

    return infer


def _contract() -> InputContract:
    return InputContract(
        "hedge_policy_v0", ("log_moneyness", "remaining_fraction", "prior_holding")
    )


def test_input_contract_rejects_an_empty_model_id() -> None:
    with pytest.raises(ValueError, match="model_id"):
        InputContract("", ("a",))


def test_input_contract_rejects_empty_feature_names() -> None:
    with pytest.raises(ValueError, match="feature_names"):
        InputContract("m1", ())


def test_input_contract_validate_rejects_a_wrong_feature_count() -> None:
    contract = _contract()
    with pytest.raises(ValueError, match="expected 3 features"):
        contract.validate(np.array([1.0, 2.0]))


def test_input_contract_validate_accepts_a_matching_shape() -> None:
    contract = _contract()
    contract.validate(np.array([1.0, 2.0, 3.0]))  # must not raise


def test_a_real_trained_policy_reproduces_its_own_recorded_outputs() -> None:
    """MLO-11's own acceptance criterion: "same reference inputs produce
    approved outputs," grounded in a real, deterministically-seeded
    `HedgePolicyMLP` -- the reference outputs are recorded by actually
    running inference once, not fabricated numbers, then confirmed
    reproducible on a SECOND, independent run."""
    infer = _real_policy_infer_fn()
    contract = _contract()
    sample_inputs = [(0.0, 1.0, 0.0), (0.05, 0.5, 0.3), (-0.1, 0.1, -0.5)]
    reference_cases = [
        ReferenceCase(inputs=inp, approved_output=infer(np.array(inp))) for inp in sample_inputs
    ]

    # a second, independently constructed (same-seed) policy instance
    second_infer = _real_policy_infer_fn()
    mismatches = verify_reproducible_inference(second_infer, contract, reference_cases)
    assert mismatches == []


def test_a_tampered_approved_output_is_reported_as_a_mismatch() -> None:
    """The discriminating half: an approved output that does NOT match
    what the model actually produces must be caught, with the exact
    input, approved and actual values -- not silently accepted."""
    infer = _real_policy_infer_fn()
    contract = _contract()
    real_output = infer(np.array([0.05, 0.5, 0.3]))
    tampered_case = ReferenceCase(inputs=(0.05, 0.5, 0.3), approved_output=real_output + 1.0)

    mismatches = verify_reproducible_inference(infer, contract, [tampered_case])
    assert len(mismatches) == 1
    assert mismatches[0].approved_output == pytest.approx(real_output + 1.0)
    assert mismatches[0].actual_output == pytest.approx(real_output)


def test_reference_cases_with_the_wrong_shape_are_rejected_before_inference() -> None:
    infer = _real_policy_infer_fn()
    contract = _contract()
    bad_case = ReferenceCase(inputs=(1.0, 2.0), approved_output=0.0)
    with pytest.raises(ValueError, match="expected 3 features"):
        verify_reproducible_inference(infer, contract, [bad_case])


def test_an_empty_reference_case_list_reports_no_mismatches() -> None:
    infer = _real_policy_infer_fn()
    contract = _contract()
    assert verify_reproducible_inference(infer, contract, []) == []
