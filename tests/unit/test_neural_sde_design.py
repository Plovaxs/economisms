import pytest

from prometheus.neural_sde.design import (
    DEFAULT_DESIGN_SPEC,
    NeuralSDEDesignSpec,
    design_record_text,
)


def test_default_spec_has_matching_series_and_unit_lengths() -> None:
    assert len(DEFAULT_DESIGN_SPEC.state_series_ids) == len(DEFAULT_DESIGN_SPEC.state_units)
    assert len(DEFAULT_DESIGN_SPEC.regime_series_ids) == len(DEFAULT_DESIGN_SPEC.regime_units)
    assert DEFAULT_DESIGN_SPEC.state_dim == 2
    assert DEFAULT_DESIGN_SPEC.regime_dim == 3


def test_mismatched_state_lengths_rejected() -> None:
    with pytest.raises(ValueError, match="same length"):
        NeuralSDEDesignSpec(
            state_series_ids=("A", "B"),
            state_units=("pct",),
            regime_series_ids=(),
            regime_units=(),
            time_unit="months",
        )


def test_empty_state_series_rejected() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        NeuralSDEDesignSpec(
            state_series_ids=(),
            state_units=(),
            regime_series_ids=(),
            regime_units=(),
            time_unit="months",
        )


def test_design_record_text_lists_every_series_unit_and_constraint() -> None:
    text = design_record_text(DEFAULT_DESIGN_SPEC)
    for series_id in DEFAULT_DESIGN_SPEC.state_series_ids + DEFAULT_DESIGN_SPEC.regime_series_ids:
        assert series_id in text
    for unit in DEFAULT_DESIGN_SPEC.state_units + DEFAULT_DESIGN_SPEC.regime_units:
        assert unit in text
    for constraint in DEFAULT_DESIGN_SPEC.constraints:
        assert constraint in text
    assert "Time unit" in text
