from __future__ import annotations

import pytest

from prometheus.dashboard.experiment_comparison import (
    REAL_COMPARISON_LOG,
    ExperimentComparisonRow,
    render_experiment_comparison,
)


def test_a_row_requires_non_empty_experiment_verdict_and_source() -> None:
    with pytest.raises(ValueError, match="verdict"):
        ExperimentComparisonRow(
            experiment="x",
            metric_name="m",
            champion_value="a",
            challenger_value="b",
            ci_or_spread="c",
            verdict="",
            source_pr="PR-1",
        )


def test_the_real_comparison_log_includes_at_least_one_not_significant_finding() -> None:
    """UIX-07's own acceptance wording: "no cherry-picked score-only
    presentations by default" -- confirmed by checking the log itself
    is not all wins."""
    verdicts = [row.verdict for row in REAL_COMPARISON_LOG]
    assert any("NOT SIGNIFICANT" in v for v in verdicts)
    assert any("GENUINE IMPROVEMENT" in v for v in verdicts)


def test_every_real_log_row_cites_a_real_pr_and_a_confidence_interval_or_spread() -> None:
    for row in REAL_COMPARISON_LOG:
        assert row.source_pr.startswith("PR-")
        assert row.ci_or_spread  # never blank -- a point estimate alone is not enough


def test_render_always_prints_the_verdict_for_every_row_including_null_results() -> None:
    html = render_experiment_comparison()
    for row in REAL_COMPARISON_LOG:
        assert row.verdict in html
        assert row.source_pr in html


def test_render_carries_a_real_data_provenance_badge() -> None:
    """FP-21/UIX-08: the rendered page actually carries the real-data
    badge in production, not just the bare `real_data_badge` function
    existing unexercised -- this view's own data is a REAL comparison
    log, not a simulation, so it must say so."""
    html = render_experiment_comparison()
    assert "REAL DATA" in html
    assert "docs/RESULTS_AND_LIMITATIONS.md" in html
