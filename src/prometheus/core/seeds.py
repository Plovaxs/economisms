"""Deterministic, order-independent random-number-generator stream hierarchy.

EXP-03: "Specify random seed hierarchy across agent/market/training --
Replay reconstructs nested RNG states and stream allocation."

A naive approach -- lazily calling numpy's SeedSequence.spawn() the first
time each named stream is requested -- is NOT safe here: spawn() assigns
child sequences in call order, so two runs that request streams in a
different order (e.g. "market" before "economy" vs. "economy" before
"market") would silently swap which draws go to which stream, even with an
identical root seed. SeedHierarchy instead derives each named stream from a
SeedSequence keyed by a stable hash of its name, so the stream a name
produces never depends on what else has been requested, or in what order.
"""

from __future__ import annotations

import hashlib

import numpy as np


class SeedHierarchy:
    def __init__(self, root_seed: int) -> None:
        if root_seed < 0:
            raise ValueError("root_seed must be non-negative")
        self.root_seed = root_seed
        self._generators: dict[str, np.random.Generator] = {}

    def _spawn_key(self, name: str) -> int:
        digest = hashlib.sha256(name.encode("utf-8")).digest()[:8]
        return int.from_bytes(digest, "big")

    def stream(self, name: str) -> np.random.Generator:
        """Return the Generator for `name`, creating it deterministically
        (keyed only by root_seed and name) on first access."""
        if name not in self._generators:
            child_sequence = np.random.SeedSequence(
                entropy=self.root_seed, spawn_key=(self._spawn_key(name),)
            )
            self._generators[name] = np.random.default_rng(child_sequence)
        return self._generators[name]

    def spawned_names(self) -> tuple[str, ...]:
        return tuple(self._generators)
