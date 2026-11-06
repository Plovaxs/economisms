"""Early stopping using validation only (MLO-06: "implement early
stopping using validation only"; acceptance criterion: "test set never
used for hyperparameter selection").

`EarlyStopper.step` requires its caller to declare, EVERY call, which
`experiments.holdout_manifest.Regime` the metric it is reporting came
from -- reused directly, not reinvented, from EXP-04's own regime
vocabulary. A call reporting anything other than `"validation"` raises
`NonValidationRegimeError` immediately: "test set never used for
hyperparameter selection" is enforced structurally, at the single
choke point every stopping decision must pass through, not merely a
convention callers are trusted to follow. Demonstrated against a real
`HoldoutManifest` (this module's own test file builds one and uses
`regime_for_date` to determine, from an actual calendar date, which
regime each simulated epoch's evaluation belongs to) rather than a
caller simply typing the string `"validation"` by hand every time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from prometheus.experiments.holdout_manifest import Regime

Mode = Literal["min", "max"]


class NonValidationRegimeError(ValueError):
    """Raised when `EarlyStopper.step` is given a metric from any
    regime other than `"validation"`."""


@dataclass(frozen=True, slots=True)
class EarlyStoppingDecision:
    stop: bool
    best_epoch: int
    best_value: float


@dataclass(slots=True)
class EarlyStopper:
    patience: int
    mode: Mode = "min"
    best_value: float = field(init=False)
    best_epoch: int = field(default=-1, init=False)
    _epochs_without_improvement: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if self.patience < 1:
            raise ValueError("patience must be at least 1")
        if self.mode not in ("min", "max"):
            raise ValueError(f"mode must be 'min' or 'max', got {self.mode!r}")
        self.best_value = float("inf") if self.mode == "min" else float("-inf")

    def step(self, epoch: int, validation_metric: float, regime: Regime) -> EarlyStoppingDecision:
        if regime != "validation":
            raise NonValidationRegimeError(
                f"early stopping must only consult the validation regime, got {regime!r} at "
                f"epoch {epoch} -- the test set must never be used for hyperparameter/stopping "
                "selection"
            )
        improved = (
            validation_metric < self.best_value
            if self.mode == "min"
            else validation_metric > self.best_value
        )
        if improved:
            self.best_value = validation_metric
            self.best_epoch = epoch
            self._epochs_without_improvement = 0
        else:
            self._epochs_without_improvement += 1
        stop = self._epochs_without_improvement >= self.patience
        return EarlyStoppingDecision(
            stop=stop, best_epoch=self.best_epoch, best_value=self.best_value
        )
