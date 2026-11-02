from datetime import date

import pytest

from prometheus.evidence.model_card import ModelCard


def _valid_card_kwargs(**overrides):
    kwargs = dict(
        model_id="test-model",
        model_type="MLP",
        framework="PyTorch 2.0",
        version="0.1.0",
        license="MIT",
        content_hash="abc123",
        intended_use="Research only.",
        prohibited_use="Live trading.",
        input_schema_summary="three floats",
        training_data_summary="synthetic GBM paths",
        primary_metrics={"cvar": 1.0},
        metric_uncertainty_note="single seed",
        failure_modes=("not OOD-tested",),
        independent_reviewer=None,
        approval_status="NOT REVIEWED",
        created_at=date(2026, 1, 1),
    )
    kwargs.update(overrides)
    return kwargs


def test_valid_card_constructs() -> None:
    card = ModelCard(**_valid_card_kwargs())
    assert card.approval_status == "NOT REVIEWED"


@pytest.mark.parametrize(
    "field",
    [
        "model_id",
        "model_type",
        "framework",
        "version",
        "license",
        "content_hash",
        "intended_use",
        "prohibited_use",
        "input_schema_summary",
        "training_data_summary",
        "metric_uncertainty_note",
        "approval_status",
    ],
)
def test_empty_required_text_field_rejected(field: str) -> None:
    with pytest.raises(ValueError):
        ModelCard(**_valid_card_kwargs(**{field: ""}))


def test_empty_failure_modes_rejected() -> None:
    with pytest.raises(ValueError):
        ModelCard(**_valid_card_kwargs(failure_modes=()))


def test_empty_primary_metrics_rejected() -> None:
    with pytest.raises(ValueError):
        ModelCard(**_valid_card_kwargs(primary_metrics={}))


def test_invalid_approval_status_rejected() -> None:
    with pytest.raises(ValueError):
        ModelCard(**_valid_card_kwargs(approval_status="SORT OF OK"))


def test_approved_without_reviewer_rejected() -> None:
    with pytest.raises(ValueError):
        ModelCard(
            **_valid_card_kwargs(approval_status="APPROVED", independent_reviewer=None)
        )


def test_approved_with_named_reviewer_succeeds() -> None:
    card = ModelCard(
        **_valid_card_kwargs(approval_status="APPROVED", independent_reviewer="Jane Reviewer")
    )
    assert card.independent_reviewer == "Jane Reviewer"
