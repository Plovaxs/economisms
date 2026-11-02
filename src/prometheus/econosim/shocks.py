"""Deterministic exogenous shocks (ECO-14).

A Shock is tagged with the step it arrives at, matching the notation in
section 3.1: z[t+1] = F(z[t], actions[1..N,t], exogenous_shock[t+1]).
ShockGenerator draws shocks from a single numpy Generator (normally one
obtained from core.seeds.SeedHierarchy), so a fixed root seed and a fixed,
ordered list of ShockSpecs reproduces an identical shock sequence on replay.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True, slots=True)
class Shock:
    shock_id: str
    step: int
    kind: str
    magnitude: float
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ShockSpec:
    """A normally-distributed shock of a given `kind` that fires with
    probability `probability` on any given step it is drawn for."""

    kind: str
    mean: float = 0.0
    std: float = 1.0
    probability: float = 1.0

    def __post_init__(self) -> None:
        if self.std < 0:
            raise ValueError("std must be non-negative")
        if not 0.0 <= self.probability <= 1.0:
            raise ValueError("probability must be in [0, 1]")


class ShockGenerator:
    def __init__(self, rng: np.random.Generator, specs: list[ShockSpec]) -> None:
        self._rng = rng
        self._specs = list(specs)
        self._next_seq = 0

    def draw_for_step(self, step: int) -> list[Shock]:
        """Draw at most one shock per configured spec for `step`, in spec
        order -- callers must invoke this once per step, in increasing step
        order, to get a reproducible sequence from a given root seed."""
        shocks: list[Shock] = []
        for spec in self._specs:
            fires = self._rng.random() < spec.probability
            if not fires:
                continue
            magnitude = float(self._rng.normal(spec.mean, spec.std))
            self._next_seq += 1
            shocks.append(
                Shock(
                    shock_id=f"shock-{self._next_seq:06d}",
                    step=step,
                    kind=spec.kind,
                    magnitude=magnitude,
                )
            )
        return shocks
