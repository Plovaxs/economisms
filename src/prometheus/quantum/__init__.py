"""Hybrid quantum-classical ML primitives (QUANTUM-LAB addendum,
proposed by the user-supplied "PROMETHEUS-X -- Quantum Deep Learning
Integration Blueprint"; gates Q0 "isolated optional dependencies" and
Q1 "quantum primitives and Torch bridge").

This package is deliberately NOT part of the original 374-item/29-
category master blueprint (that register's extractor requires 3-4
letter category prefixes; nothing here uses one) nor the FP-01..FP-24
ECONOSIM-X final-project addendum checklist by itself -- it is shared
infrastructure `recessionnet` (FP-06) consumes as one of several
competing model architectures. Quantum components are treated as
EXPERIMENTAL CHALLENGERS to the classical baselines already used
elsewhere in this repository, never as a presumed improvement; see
`quantum.layers` and `quantum.models` for what is and is not claimed.

Requires the optional `quantum` dependency group
(`pennylane==0.45.1`, `pennylane-lightning==0.45.0`, both installed
and import-tested against this repository's existing `torch==2.15+cpu`
/ `numpy==2.5` stack before being pinned here -- see
`pyproject.toml`). Nothing in `src/prometheus` outside this package
and `recessionnet` imports PennyLane, so the classical environment and
test suite are completely unaffected if the `quantum` extra is not
installed.
"""

from __future__ import annotations
