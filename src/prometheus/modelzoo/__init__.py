"""MODELZOO: small, tested reference implementations of the model families a quantitative-economics
research programme is asked about, each compared with a baseline this project already trusts.

What this package is, and is not:

* Every model here is written from scratch in PyTorch or NumPy at a size that trains on a laptop
CPU in
  seconds to minutes. It is **not** a replication of the cited paper at that paper's scale, and no
  result here says anything about the paper's own numbers.
* A model is in this package only if there is a test for it and a comparison against a baseline
with a
  known answer (a closed form, an exact solution, a plain Monte Carlo, or a classical forecaster).
  The comparison is run once, with the hypotheses written down first, and the verdict is recorded
  whichever way it falls (see the `orchestration.modelzoo_*_study` modules and `docs/numerics/`).
* `registry` lists what is implemented, what already existed elsewhere in the repository and what is
  deliberately not built (Lean theorem provers, many-electron wavefunctions and the like need
  compute or
  software this project does not have), and `graph` links them: which model is a baseline for which,
  which data and finding each one touches, and which model's output feeds which.

Everything here is simulation and research. Nothing is advice and nothing changes the project's
NO-GO
gate for live trading.
"""
