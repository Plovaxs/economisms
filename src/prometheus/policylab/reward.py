"""The declared POLICYLAB-RL reward: a stability-penalizing quadratic loss
over inflation/output deviations and rate changes, matching the blueprint's
own wording for this subsystem ("a declared reward measuring simulated
inflation/output deviations and stability").

    reward = -(inflation_gap**2 + output_gap**2 + lambda_rate * (rate - prev_rate)**2)

Lower squared deviations and smaller rate changes both score higher
(closer to zero); this is the only formula this package uses for reward,
in training and in evaluation alike, so a policy cannot be scored by a
different measure than the one it was trained against.
"""

from __future__ import annotations


def policy_reward(
    inflation_gap: float, output_gap: float, rate: float, prev_rate: float, lambda_rate: float
) -> float:
    if lambda_rate < 0:
        raise ValueError("lambda_rate must be non-negative")
    rate_change = rate - prev_rate
    return -(inflation_gap**2 + output_gap**2 + lambda_rate * rate_change**2)
