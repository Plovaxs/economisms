from __future__ import annotations

from prometheus.dashboard.inflationcast_view import render_inflationcast

_FAST_KWARGS = dict(max_epochs=15, patience=5, bootstrap_resamples=30)


def test_render_inflationcast_carries_a_real_data_provenance_badge() -> None:
    html = render_inflationcast(**_FAST_KWARGS)
    assert "REAL DATA" in html
    assert "BLS Public Data API" in html


def test_render_inflationcast_shows_every_candidate() -> None:
    html = render_inflationcast(**_FAST_KWARGS)
    for name in (
        "naive_persistence", "linear_regression", "classical_matched_mlp",
        "hybrid_quantum", "gru",
    ):
        assert name in html


def test_render_inflationcast_includes_a_bar_chart_and_a_line_chart() -> None:
    html = render_inflationcast(**_FAST_KWARGS)
    assert html.count("<svg") == 2
    assert html.count("<polyline") >= 2  # actual + at least one candidate


def test_render_inflationcast_includes_a_calibration_indicator() -> None:
    html = render_inflationcast(**_FAST_KWARGS)
    assert "indicator-dot" in html
    assert "GRU calibration" in html


def test_render_inflationcast_prints_the_bootstrap_confidence_interval() -> None:
    html = render_inflationcast(**_FAST_KWARGS)
    assert "95% CI" in html


def test_render_inflationcast_is_deterministic_for_a_fixed_seed() -> None:
    """Compares the real MAE/RMSE/MASE table cells, not the whole page
    -- `train_seconds` is real wall-clock timing and legitimately
    varies run to run even for an identical seed."""
    import re

    def metric_rows(html: str) -> list[str]:
        return re.findall(
            r"<tr><td>(\w+)</td><td>([\d.]+)</td><td>([\d.]+)</td><td>([\d.]+)</td>", html
        )

    first = render_inflationcast(seed=0, **_FAST_KWARGS)
    second = render_inflationcast(seed=0, **_FAST_KWARGS)
    assert metric_rows(first) == metric_rows(second)


def test_render_inflationcast_never_leaks_a_nan_or_inf_into_a_numeric_svg_attribute() -> None:
    import re

    html = render_inflationcast(**_FAST_KWARGS)
    bad = re.findall(
        r'(?:width|height|x|y|points|cx|cy)="[^"]*(?:nan|inf)[^"]*"', html, re.IGNORECASE
    )
    assert bad == []
