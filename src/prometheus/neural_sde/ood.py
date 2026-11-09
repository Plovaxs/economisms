"""NSD-11: "Evaluate unseen macroeconomic shocks and drift -- OOD risk
vs baseline reported without re-tuning test."

Uses a REAL historical out-of-distribution event present in the
already-ingested `data_cache/kaggle_us_macro_monthly.csv` data (PR-145):
the 2020 COVID shock. Checked directly against the raw CSV (not
assumed -- see `test_neural_sde_ood.py`): `KAGGLE_GDP_YOY` (a state
variable) hits -7.69% in 2020-05, its single most negative value in the
entire 1981-2023 sample, and `KAGGLE_CLAIMS_YOY` (a regime feature) hits
+1146% in the same month, its single most positive value in the entire
sample -- a genuine, verified double extremum, not an arbitrarily chosen
date range. `KAGGLE_NASDAQ_YOY` (the other state variable) does NOT hit
an extreme in this window -- its all-time low (-59.8%) and high (+105.3%
YoY) in this sample both fall in the 2000-2001 dot-com cycle instead,
and it is mildly POSITIVE throughout 2020-02..2020-06 in this derived
monthly YoY series. This asymmetry is disclosed, not smoothed over: the
2020 window tested here is a genuine GDP/labor-market shock in this
dataset, not a NASDAQ-specific one.

"Without re-tuning" is enforced structurally: `evaluate_ood_without_retuning`
takes an ALREADY-TRAINED `TrainedNeuralSDE` (and an already-fit GBM
baseline) and only calls evaluation functions on them -- there is no
training call anywhere in this module, so there is no code path by
which the OOD window's own data could influence either candidate's
parameters.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

from prometheus.neural_sde.benchmark import fit_gbm_constant, predict_candidate
from prometheus.neural_sde.dataset import TransitionExample
from prometheus.neural_sde.scoring import gaussian_log_score
from prometheus.neural_sde.training import TrainedNeuralSDE

COVID_OOD_WINDOW_START = date(2020, 2, 29)
COVID_OOD_WINDOW_END = date(2020, 6, 30)


def split_pre_and_during_covid(
    examples: list[TransitionExample],
) -> tuple[list[TransitionExample], list[TransitionExample]]:
    """Splits by the transition's OWN decision_time, not an index --
    `pre_covid` is everything decided strictly before the window,
    `covid_window` is everything decided inside
    [COVID_OOD_WINDOW_START, COVID_OOD_WINDOW_END]. Examples decided
    after the window are excluded from both (neither "normal" nor
    "the shock itself")."""
    pre_covid = [e for e in examples if e.decision_time < COVID_OOD_WINDOW_START]
    covid_window = [
        e for e in examples if COVID_OOD_WINDOW_START <= e.decision_time <= COVID_OOD_WINDOW_END
    ]
    return pre_covid, covid_window


@dataclass(frozen=True, slots=True)
class OODReport:
    neural_in_distribution_log_score: float
    neural_covid_log_score: float
    neural_degradation: float
    baseline_in_distribution_log_score: float
    baseline_covid_log_score: float
    baseline_degradation: float
    n_in_distribution: int
    n_covid: int


def evaluate_ood_without_retuning(
    trained: TrainedNeuralSDE,
    in_distribution_held_out: list[TransitionExample],
    covid_window: list[TransitionExample],
    train_examples: list[TransitionExample],
) -> OODReport:
    """`train_examples` is used ONLY to fit the frozen GBM baseline's
    constant (mean, covariance) once -- the exact same role
    `in_distribution_held_out`/`covid_window` play for the already-frozen
    neural model. Neither candidate is fit or adjusted using
    `covid_window` at any point."""
    if len(covid_window) == 0:
        raise ValueError("covid_window must be non-empty")
    if len(in_distribution_held_out) == 0:
        raise ValueError("in_distribution_held_out must be non-empty")

    def _score(name: str, examples: list[TransitionExample]) -> float:
        next_state = np.array([e.next_state for e in examples])
        mu, sigma = predict_candidate(
            name,
            examples,
            train_examples,
            neural_model=trained.model,
            state_scaler=trained.state_scaler,
            regime_scaler=trained.regime_scaler,
        )
        return gaussian_log_score(mu, sigma, next_state)

    neural_in_dist = _score("neural_sde", in_distribution_held_out)
    neural_covid = _score("neural_sde", covid_window)
    baseline_in_dist = _score("gbm_constant", in_distribution_held_out)
    baseline_covid = _score("gbm_constant", covid_window)

    return OODReport(
        neural_in_distribution_log_score=neural_in_dist,
        neural_covid_log_score=neural_covid,
        neural_degradation=neural_covid - neural_in_dist,
        baseline_in_distribution_log_score=baseline_in_dist,
        baseline_covid_log_score=baseline_covid,
        baseline_degradation=baseline_covid - baseline_in_dist,
        n_in_distribution=len(in_distribution_held_out),
        n_covid=len(covid_window),
    )


__all__ = [
    "COVID_OOD_WINDOW_START",
    "COVID_OOD_WINDOW_END",
    "split_pre_and_during_covid",
    "OODReport",
    "evaluate_ood_without_retuning",
    "fit_gbm_constant",
]
