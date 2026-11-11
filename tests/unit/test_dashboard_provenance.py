from __future__ import annotations

import pytest

from prometheus.dashboard.provenance import real_data_badge, synthetic_badge
from prometheus.evidence.constants import SIMULATION_DISCLAIMER, SOURCE_TAG


def test_synthetic_badge_names_itself_synthetic_and_carries_the_real_disclaimer() -> None:
    badge = synthetic_badge()
    assert "SYNTHETIC" in badge
    assert SIMULATION_DISCLAIMER in badge
    assert SOURCE_TAG in badge
    assert 'class="provenance synthetic"' in badge


def test_real_data_badge_names_itself_real_data_and_its_source() -> None:
    badge = real_data_badge("docs/RESULTS_AND_LIMITATIONS.md")
    assert "REAL DATA" in badge
    assert "docs/RESULTS_AND_LIMITATIONS.md" in badge
    assert SOURCE_TAG in badge
    assert 'class="provenance real"' in badge


def test_real_data_badge_rejects_an_empty_source() -> None:
    """FP-21/UIX-08's own point: a real-data badge that could render
    with no named source would let a reader mistake unattributed data
    for something it is not -- this is the real, enforced half of
    "names whether the data is synthetic or real and, if real, where
    it came from", not merely documented as a convention."""
    with pytest.raises(ValueError, match="source"):
        real_data_badge("")
    with pytest.raises(ValueError, match="source"):
        real_data_badge("   ")


def test_the_two_badges_are_never_confusable() -> None:
    """UIX-08's own acceptance wording: synthetic and real-data labels
    must be visibly distinct, not two renderings of the same template
    a reader could mistake for each other at a glance."""
    synthetic = synthetic_badge()
    real = real_data_badge("some real source")
    assert synthetic != real
    assert "SYNTHETIC" not in real
    assert "REAL DATA" not in synthetic


def test_real_data_badge_escapes_an_untrusted_source_string() -> None:
    badge = real_data_badge("<script>alert(1)</script>")
    assert "<script>" not in badge
    assert "&lt;script&gt;" in badge
