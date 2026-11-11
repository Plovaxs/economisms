"""The INFLATIONCAST live demo view: the final-project deep-learning
subsystem rendered as a REAL, server-rendered dashboard page -- not the
separate Claude-Artifact project-status page, and explicitly not an
Artifact at all for this one (the user's own requirement for this
deliverable). Reuses `orchestration.inflationcast_run.run_inflationcast_
demo`/`InflationcastRunConfig` UNCHANGED -- the identical real-training
pipeline the CLI runs end to end, triggered here by an HTTP GET instead
of a terminal invocation, against the same real committed BLS CPI-U and
Kaggle macro snapshots. Every number on this page (MAE/RMSE/MASE, the
bar chart, the actual-vs-predicted line chart, the calibration
indicator, the bootstrap CI) comes from that one real run; nothing here
is a placeholder or a canned result.

The 0.05 calibration-pass threshold below is this VIEW's own
illustrative choice for the indicator's pass/fail color, not a claim
that `evaluation.gaussian_interval_coverage_test` is itself a pass/fail
gate -- its own docstring is explicit that a p-value is a diagnostic,
and the full p-value is always printed alongside the indicator so a
reader is never limited to the simplified color."""

from __future__ import annotations

from prometheus.dashboard.charts import bar_chart, calibration_indicator, line_chart
from prometheus.dashboard.html import page, table
from prometheus.dashboard.provenance import real_data_badge
from prometheus.data_ingestion.kaggle_macro import load_kaggle_us_macro_observations
from prometheus.inflationcast.data import load_cpi_observations
from prometheus.orchestration.inflationcast_run import (
    DEFAULT_CPI_CSV_PATH,
    DEFAULT_MACRO_CSV_PATH,
    InflationcastRunConfig,
    run_inflationcast_demo,
)

_CALIBRATION_PASS_P_VALUE = 0.05

_VERDICT_TEXT: dict[str, str] = {
    "gru_better": "The GRU significantly improved on its best classical challenger.",
    "classical_better": "The best classical challenger significantly beat the GRU.",
    "inconclusive": (
        "No statistically significant difference between the GRU and its "
        "best classical challenger."
    ),
}


def render_inflationcast(
    *,
    seed: int = 0,
    max_epochs: int = 150,
    patience: int = 15,
    bootstrap_resamples: int = 300,
) -> str:
    config = InflationcastRunConfig(
        seed=seed, max_epochs=max_epochs, patience=patience, bootstrap_resamples=bootstrap_resamples
    )
    cpi_observations = load_cpi_observations(DEFAULT_CPI_CSV_PATH)
    macro_observations = load_kaggle_us_macro_observations(DEFAULT_MACRO_CSV_PATH)
    result = run_inflationcast_demo([*cpi_observations, *macro_observations], config)
    report = result.report

    metric_rows = [
        [
            name,
            f"{m.mae:.3f}",
            f"{m.rmse:.3f}",
            f"{m.mase:.3f}",
            str(report.parameter_counts[name]),
            f"{report.train_seconds[name]:.3f}s",
        ]
        for name, m in report.metrics.items()
    ]
    bars = bar_chart([(name, m.mae) for name, m in report.metrics.items()], unit=" pp MAE")

    x_labels = [str(i) for i in range(len(report.test_targets))]
    chart = line_chart(
        x_labels,
        {
            "actual CPI YoY": report.test_targets,
            "gru": report.predictions["gru"],
            report.best_point_challenger: report.predictions[report.best_point_challenger],
        },
        unit="%",
    )

    calibration = report.gru_calibration
    indicator = calibration_indicator(
        passed=calibration.p_value >= _CALIBRATION_PASS_P_VALUE,
        label="GRU calibration (90% interval coverage)",
        detail=(
            f"observed {calibration.observed_coverage:.1%} vs. nominal "
            f"{calibration.nominal_coverage:.0%} coverage (p={calibration.p_value:.2e}, "
            f"n={calibration.n_observations})"
        ),
    )

    bootstrap = report.gru_vs_best_classical
    body = (
        real_data_badge("BLS Public Data API (CPI-U, CUUR0000SA0) + Kaggle US macro indicators")
        + "<p>Train/validation/test: "
        f"{result.n_train_samples}/{result.n_validation_samples}/{result.n_test_samples} real "
        f"monthly examples. Validation split {config.validation_split_date.isoformat()}, "
        f"test split {config.test_split_date.isoformat()}, seed={seed}.</p>"
        + "<h2>Point-forecast accuracy by candidate</h2>"
        + bars
        + table(["candidate", "MAE", "RMSE", "MASE", "parameters", "train time"], metric_rows)
        + "<h2>Actual vs. predicted CPI YoY, test period</h2>"
        + chart
        + "<h2>GRU uncertainty calibration</h2>"
        + indicator
        + "<h2>GRU vs. best classical challenger</h2>"
        + f"<p>{_VERDICT_TEXT[result.verdict]} 95% CI for the mean squared-error difference: "
        f"[{bootstrap.ci_low:.3f}, {bootstrap.ci_high:.3f}] "
        f"(point estimate {bootstrap.point_estimate:.3f}, {bootstrap.n_resamples} resamples).</p>"
    )
    return page(
        "INFLATIONCAST",
        "INFLATIONCAST: CPI nowcasting -- classical vs. deep learning vs. hybrid quantum",
        body,
    )
