"""Scientific evaluation infrastructure (section 10).

Current scope (PR-008): paired bootstrap confidence intervals, a
reproducibility manifest with a content hash, and a first benchmark that
compares the delta-hedging baseline against a trained MLP hedging policy
across several independent held-out seeds. This is one slice of the
blueprint's factorial economy x market x hedge matrix (EXP-02), not the
whole thing -- see hedge_benchmark.py's module docstring for exactly what
is and is not varied.
"""
