"""A validated model card (section 16's "Model card - mandatory sections";
MLO-09, DOC-06). Every mandatory section is a required field; omitting one
or leaving it blank raises at construction time rather than shipping a
card with a silently missing section.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

_VALID_APPROVAL_STATES = {"NOT REVIEWED", "APPROVED", "REJECTED", "CONDITIONAL"}


@dataclass(frozen=True, slots=True)
class ModelCard:
    model_id: str
    model_type: str
    framework: str
    version: str
    license: str
    content_hash: str
    intended_use: str
    prohibited_use: str
    input_schema_summary: str
    training_data_summary: str
    primary_metrics: Mapping[str, float]
    metric_uncertainty_note: str
    failure_modes: tuple[str, ...]
    independent_reviewer: str | None
    approval_status: str
    created_at: date

    def __post_init__(self) -> None:
        required_text_fields = {
            "model_id": self.model_id,
            "model_type": self.model_type,
            "framework": self.framework,
            "version": self.version,
            "license": self.license,
            "content_hash": self.content_hash,
            "intended_use": self.intended_use,
            "prohibited_use": self.prohibited_use,
            "input_schema_summary": self.input_schema_summary,
            "training_data_summary": self.training_data_summary,
            "metric_uncertainty_note": self.metric_uncertainty_note,
            "approval_status": self.approval_status,
        }
        for name, value in required_text_fields.items():
            if not value or not value.strip():
                raise ValueError(f"model card field {name!r} must not be empty")
        if not self.failure_modes:
            raise ValueError("failure_modes must list at least one known limitation")
        if not self.primary_metrics:
            raise ValueError("primary_metrics must not be empty")
        if self.approval_status not in _VALID_APPROVAL_STATES:
            raise ValueError(
                f"approval_status must be one of {sorted(_VALID_APPROVAL_STATES)}, "
                f"got {self.approval_status!r}"
            )
        if self.approval_status == "APPROVED" and not self.independent_reviewer:
            raise ValueError(
                "approval_status cannot be 'APPROVED' without a named independent_reviewer"
            )
