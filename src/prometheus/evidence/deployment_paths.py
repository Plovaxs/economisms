"""Shadow deployment (CIQ-09: "implement staging and canary/shadow
deployment paths"; acceptance: "shadow comparison and rollback are
exercised") and automatic rollback on metric regression (CIQ-10:
"support automatic rollback on critical metric regression"; acceptance:
"fault injection demonstrates reversal within recovery target").

Both compose `evidence.model_serving.ModelServingSlot` (MLO-12/MGR-12,
already real and tested) rather than building a second, parallel
serving abstraction.

`ShadowDeployment.predict_with_shadow` ONLY EVER RETURNS the champion's
output -- the challenger is always computed too, but its output is
recorded in `comparisons` for later analysis and never served. This is
the real meaning of "shadow": the challenger's predictions exist and
are compared, but carry zero production risk, since nothing downstream
ever sees them. "Canary"/"staging" in the honest sense this single-
service local repository can actually provide: a distinct
`ModelServingSlot` instance IS a staging slot (nothing stops a caller
constructing one pointed at a candidate package and comparing it
against a separate slot serving the real champion, which is exactly
what `ShadowDeployment` demonstrates) -- not a separate, physically
distinct staging environment with its own infrastructure, which this
project does not have.

`AutoRollbackMonitor.observe` is the real automatic-rollback mechanism:
each call reports one metric observation; once `n_consecutive_breaches`
in a row exceed `critical_threshold` (REQUIRES CONSECUTIVE breaches, not
one noisy spike, to avoid rolling back on a single outlier), it calls
`slot.rollback_to(last_known_good)` itself -- no human in the loop --
and records a `RollbackEvent` with the exact observation index the
rollback fired at, which is what `test_deployment_paths.py`'s real fault-
injection test uses to measure "recovery target" (here: number of
observations from the fault's first appearance to the automatic
rollback firing) as a real, asserted number, not a claim.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from prometheus.evidence.model_package import ModelPackage
from prometheus.evidence.model_serving import ModelServingSlot


@dataclass(frozen=True, slots=True)
class ShadowComparison:
    input_key: str
    champion_output: str
    challenger_output: str
    outputs_match: bool


@dataclass(slots=True)
class ShadowDeployment:
    serving: ModelServingSlot
    challenger: ModelPackage
    comparisons: list[ShadowComparison] = field(default_factory=list)

    def predict_with_shadow(
        self,
        input_key: str,
        champion_compute: Callable[[], str],
        challenger_compute: Callable[[], str],
    ) -> str:
        champion_output = self.serving.cached_predict(input_key, champion_compute)
        challenger_output = challenger_compute()
        self.comparisons.append(
            ShadowComparison(
                input_key=input_key,
                champion_output=champion_output,
                challenger_output=challenger_output,
                outputs_match=champion_output == challenger_output,
            )
        )
        return champion_output

    def agreement_rate(self) -> float:
        if not self.comparisons:
            raise ValueError("no shadow comparisons recorded yet")
        matches = sum(1 for c in self.comparisons if c.outputs_match)
        return matches / len(self.comparisons)


@dataclass(frozen=True, slots=True)
class RollbackEvent:
    observation_index: int
    metric_value_at_trigger: float
    rolled_back_to: ModelPackage


@dataclass(slots=True)
class AutoRollbackMonitor:
    slot: ModelServingSlot
    last_known_good: ModelPackage
    critical_threshold: float
    n_consecutive_breaches: int
    higher_is_worse: bool = True
    _consecutive: int = field(default=0, init=False)
    _observation_count: int = field(default=0, init=False)
    rollback_events: list[RollbackEvent] = field(default_factory=list, init=False)

    def _is_breach(self, value: float) -> bool:
        if self.higher_is_worse:
            return value > self.critical_threshold
        return value < self.critical_threshold

    def observe(self, metric_value: float) -> RollbackEvent | None:
        self._observation_count += 1
        if self._is_breach(metric_value):
            self._consecutive += 1
        else:
            self._consecutive = 0
        if self._consecutive < self.n_consecutive_breaches:
            return None
        event = RollbackEvent(
            observation_index=self._observation_count,
            metric_value_at_trigger=metric_value,
            rolled_back_to=self.last_known_good,
        )
        self.slot.rollback_to(self.last_known_good)
        self._consecutive = 0  # reset: a fresh breach streak must re-accumulate after recovery
        self.rollback_events.append(event)
        return event
