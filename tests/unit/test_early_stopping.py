from datetime import date

import pytest

from prometheus.experiments.early_stopping import EarlyStopper, NonValidationRegimeError
from prometheus.experiments.holdout_manifest import (
    DataSplit,
    build_holdout_manifest,
    regime_for_date,
)


def _manifest():
    return build_holdout_manifest(
        [
            DataSplit("train", "train", date(2024, 1, 1), date(2024, 6, 30)),
            DataSplit("val", "validation", date(2024, 7, 1), date(2024, 9, 30)),
            DataSplit("test", "test", date(2024, 10, 1), date(2024, 12, 31)),
        ]
    )


def test_rejects_a_non_positive_patience() -> None:
    with pytest.raises(ValueError, match="patience"):
        EarlyStopper(patience=0)


def test_rejects_an_unknown_mode() -> None:
    with pytest.raises(ValueError, match="mode"):
        EarlyStopper(patience=2, mode="sideways")  # type: ignore[arg-type]


def test_min_mode_tracks_the_lowest_value_seen() -> None:
    stopper = EarlyStopper(patience=5, mode="min")
    stopper.step(0, 1.0, "validation")
    decision = stopper.step(1, 0.5, "validation")
    assert decision.best_value == 0.5
    assert decision.best_epoch == 1


def test_max_mode_tracks_the_highest_value_seen() -> None:
    stopper = EarlyStopper(patience=5, mode="max")
    stopper.step(0, 0.5, "validation")
    decision = stopper.step(1, 0.9, "validation")
    assert decision.best_value == 0.9
    assert decision.best_epoch == 1


def test_stops_exactly_after_patience_epochs_with_no_improvement() -> None:
    stopper = EarlyStopper(patience=2, mode="min")
    losses = [1.0, 0.8, 0.75, 0.74, 0.74, 0.74]
    decisions = [stopper.step(e, loss, "validation") for e, loss in enumerate(losses)]
    assert [d.stop for d in decisions] == [False, False, False, False, False, True]
    assert decisions[-1].best_epoch == 3
    assert decisions[-1].best_value == pytest.approx(0.74)


def test_an_improvement_resets_the_patience_counter() -> None:
    """The discriminating half: a late improvement must reset the
    no-improvement streak, not just be recorded as the new best while
    stopping anyway."""
    stopper = EarlyStopper(patience=2, mode="min")
    stopper.step(0, 1.0, "validation")  # improve
    stopper.step(1, 1.0, "validation")  # no improve (1/2)
    decision = stopper.step(2, 0.5, "validation")  # improve again -- resets
    assert decision.stop is False
    assert decision.best_epoch == 2
    stopper.step(3, 0.5, "validation")  # no improve (1/2)
    decision = stopper.step(4, 0.5, "validation")  # no improve (2/2) -- now stop
    assert decision.stop is True


def test_rejects_a_metric_reported_from_the_train_regime() -> None:
    stopper = EarlyStopper(patience=2)
    with pytest.raises(NonValidationRegimeError, match="validation regime"):
        stopper.step(0, 0.5, "train")


def test_rejects_a_metric_reported_from_the_test_regime() -> None:
    """MLO-06's own acceptance criterion, literally: "test set never
    used for hyperparameter selection" -- enforced, not merely
    documented, at the single choke point every stopping decision
    passes through."""
    stopper = EarlyStopper(patience=2)
    with pytest.raises(NonValidationRegimeError, match="'test'"):
        stopper.step(0, 0.5, "test")


def test_a_rejected_step_does_not_mutate_the_stoppers_state() -> None:
    stopper = EarlyStopper(patience=2, mode="min")
    stopper.step(0, 0.9, "validation")
    with pytest.raises(NonValidationRegimeError):
        stopper.step(1, 0.1, "test")
    decision = stopper.step(2, 0.9, "validation")
    assert decision.best_value == pytest.approx(0.9)
    assert decision.best_epoch == 0


def test_early_stopping_driven_by_a_real_holdout_manifest_regime_lookup() -> None:
    """Grounded in a real `HoldoutManifest`/`regime_for_date` lookup,
    not a caller simply typing "validation" by hand: every epoch's
    regime is determined from an actual calendar date."""
    manifest = _manifest()
    stopper = EarlyStopper(patience=2, mode="min")
    losses = [1.0, 0.8, 0.75, 0.74, 0.74, 0.74]
    eval_dates = [
        date(2024, 7, 1), date(2024, 7, 15), date(2024, 8, 1),
        date(2024, 8, 15), date(2024, 9, 1), date(2024, 9, 15),
    ]
    stop_epoch = None
    for epoch, (loss, eval_date) in enumerate(zip(losses, eval_dates, strict=True)):
        regime = regime_for_date(manifest, eval_date)
        decision = stopper.step(epoch, loss, regime)
        if decision.stop:
            stop_epoch = epoch
            break
    assert stop_epoch == 5
    assert decision.best_epoch == 3


def test_an_evaluation_date_that_resolves_to_the_test_regime_is_rejected() -> None:
    """The real-world leakage scenario this module exists to prevent:
    an evaluation accidentally run on a date that falls in the test
    split must be caught by `step` itself, via a genuine
    `regime_for_date` lookup, not a hand-typed string."""
    manifest = _manifest()
    stopper = EarlyStopper(patience=2)
    test_regime = regime_for_date(manifest, date(2024, 10, 5))
    assert test_regime == "test"
    with pytest.raises(NonValidationRegimeError):
        stopper.step(0, 0.5, test_regime)
