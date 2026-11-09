"""RECESSIONNET (ECONOSIM-X/PROMETHEUS-X addendum FP-06): calibrated
recession-probability classification on real, point-in-time-safe
monthly market-factor data, benchmarking logistic regression, a
parameter-matched classical MLP and a hybrid quantum classifier
(`prometheus.quantum`) against a trivial base-rate baseline. See
`labels.py`, `dataset.py`, `training.py` and `evaluation.py` for what
each piece does and does not cover.
"""

from __future__ import annotations
