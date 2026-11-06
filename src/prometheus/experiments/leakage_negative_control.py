"""Future-data negative control, for leakage diagnosis only (EXP-05:
"add future-data negative control only for leakage diagnosis";
acceptance criterion: "diagnostic clearly isolated from valid model
scoreboard").

The diagnostic itself is simple: score the SAME model twice with two
caller-supplied scoring functions -- one honoring the point-in-time
rule (`valid_score_fn`), one deliberately handed data a real deployment
could never have seen yet (`leaked_score_fn`) -- and report both plus
their gap. A large, suspicious gap is evidence that whatever pipeline
produced `valid_score_fn`'s inputs may itself be leaking in some other,
unintentional way elsewhere (if a model can be made to look much better
just by cheating on purpose, an accidental, smaller leak would look
like genuine improvement, not an error).

"Clearly isolated from valid model scoreboard" is enforced, not merely
asserted: `LeakageNegativeControlResult` is deliberately NOT a
`RunManifest` (`experiments.manifest`) or any other type this
repository's evidence/benchmark modules recognize as a legitimate
scored result, and `assert_scoreboard_is_leakage_clean` is a reusable
guard -- intended to be called by any code assembling a collection of
results into a real scoreboard/report -- that raises if ANY entry in
that collection is (by `isinstance`, not a spoofable string tag)
a `LeakageNegativeControlResult`. A diagnostic result can be computed
and inspected, but cannot be silently folded into a legitimate
scoreboard without the assembling code explicitly bypassing this guard.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TypeVar

_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class LeakageNegativeControlResult:
    metric_name: str
    valid_score: float
    leaked_score: float

    @property
    def leakage_gap(self) -> float:
        """leaked_score - valid_score; positive means seeing the future
        made the score look better, as a genuine leak would."""
        return self.leaked_score - self.valid_score


def run_future_data_negative_control(
    metric_name: str,
    valid_score_fn: Callable[[], float],
    leaked_score_fn: Callable[[], float],
) -> LeakageNegativeControlResult:
    """Runs both scorers and reports the diagnostic result. Neither
    scorer is called more than once; which inputs each one is allowed
    to see is entirely the caller's responsibility to set up correctly
    (this function only orchestrates and reports, it cannot itself
    detect whether `valid_score_fn` was actually kept point-in-time
    clean)."""
    return LeakageNegativeControlResult(
        metric_name=metric_name,
        valid_score=valid_score_fn(),
        leaked_score=leaked_score_fn(),
    )


def assert_scoreboard_is_leakage_clean(entries: Sequence[_T]) -> None:
    """Raises ValueError if any entry is a `LeakageNegativeControlResult`
    -- the isolation half of EXP-05's acceptance criterion, intended to
    be called by whatever code in this repository assembles a
    collection of results into a real scoreboard, benchmark report, or
    model card."""
    leaked = [e for e in entries if isinstance(e, LeakageNegativeControlResult)]
    if leaked:
        raise ValueError(
            f"{len(leaked)} LeakageNegativeControlResult entr"
            f"{'y' if len(leaked) == 1 else 'ies'} found among results being assembled into "
            "a scoreboard -- a future-data negative control is a leakage DIAGNOSTIC, never "
            "a valid scored result, and must not be reported as one"
        )
