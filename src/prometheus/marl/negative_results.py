"""MAR-14: "Document failure to converge and unidentifiable solutions --
Negative result log maintained with triggering configurations."

Both entries below are REAL, independently reproduced findings from this
package's own development, not speculative placeholders -- each is
backed by a test in `test_mar_negative_results.py` that re-runs the
exact triggering configuration and confirms the documented failure mode
still occurs. If a future change to this package fixes one of these
(changes the actual observed behavior), the corresponding test will
fail, and this log must be updated to match reality rather than left
stale -- the same discipline `CHECKLIST_STATUS.md` applies to the
repository's own narrative sections.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NegativeResultEntry:
    finding_id: str
    triggering_configuration: str
    observed_failure: str
    detection_method: str
    resolution: str


NEGATIVE_RESULT_LOG: tuple[NegativeResultEntry, ...] = (
    NegativeResultEntry(
        finding_id="mar-reward-degenerate-optimum",
        triggering_configuration=(
            "env.run_rollout's original household reward (per-step log(1 + consumption) only, "
            "no term valuing ending net worth)"
        ),
        observed_failure=(
            "A direct sweep over fixed consumption fractions 0.1..1.0 found total utility "
            "STRICTLY INCREASING in the consumption fraction, maximized at fraction=1.0 "
            "(37.30) -- a degenerate, uninteresting optimum with no real intertemporal "
            "trade-off for MAR-04's 'improvement checked against rule-based counterfactuals' "
            "to actually demonstrate; an RL policy 'learning' to spend more would not have "
            "been evidence of anything."
        ),
        detection_method=(
            "Direct numeric sweep over fixed fractions, run before training.py's PPO trainer "
            "was exercised on the original reward design -- not caught by a training run "
            "'looking reasonable', caught by checking the reward landscape itself first."
        ),
        resolution=(
            "Added a bequest_weight * log(1 + ending_net_worth) term on the final step only "
            "(env.py, training.py, DEFAULT_BEQUEST_WEIGHT=1.0); the same sweep with this term "
            "now shows a genuine interior optimum near fraction~0.75-0.8, and the trained PPO "
            "policy discovers a qualitatively different, better-performing time-varying "
            "strategy (near-full consumption on non-terminal steps, conservative only on the "
            "final/bequest step) that strictly beats every fixed-fraction baseline tested."
        ),
    ),
    NegativeResultEntry(
        finding_id="mar-ppo-learning-rate-collapse",
        triggering_configuration=(
            "train_joint_ppo(seed=0, n_epochs=25, episodes_per_epoch=8, n_steps=6, "
            "learning_rate=5.0, train_household=True, firm_fixed_rule=FixedWageRule(0.5)) "
            "-- all other arguments at this module's own defaults"
        ),
        observed_failure=(
            "PPO epoch loss collapses to ~0 (order 1e-8, i.e. the optimizer stops producing "
            "any meaningful gradient) by epoch 14 and stays there; the resulting deterministic "
            "policy degenerates to a CONSTANT 0.5 consumption fraction at every observation "
            "tried, regardless of cash balance or step -- i.e. the network's alpha/beta heads "
            "saturate to identical values, collapsing the Beta policy to its symmetric mean "
            "and making it unresponsive to its own input. Evaluated utility (40.31) is "
            "measurably worse than both the properly-trained policy (42.07, learning_rate=0.02) "
            "and the best fixed-fraction baseline (41.20 at fraction=0.8) -- a real, "
            "measurable regression, not merely 'slower to converge'."
        ),
        detection_method=(
            "Deliberately re-ran training at a 250x larger learning rate than this module's "
            "own default (0.02) specifically to probe for a convergence failure mode, the same "
            "'engineer a stress configuration and check what actually happens' approach "
            "`neural_sde.training`'s own NSD-12 test uses."
        ),
        resolution=(
            "Not resolved by relaxing the trainer -- this is treated as an out-of-range "
            "hyperparameter choice, not a bug: `train_joint_ppo`'s own `learning_rate` default "
            "(0.02) is the recommended value and is what every other test in this package "
            "actually trains with. Documented here, with a reproducing test, rather than "
            "silently working around or hiding it."
        ),
    ),
)
