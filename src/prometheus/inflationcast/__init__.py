"""INFLATIONCAST (ECONOSIM-X/PROMETHEUS-X final-project addendum,
FP-07: "INFLATIONCAST respects mixed-frequency release timing").

Real monthly US CPI-U nowcasting: at the end of month M, before that
month's own CPI figure has actually been released (the real BLS
release lag is about two weeks into month M+1), predict what it will
turn out to be -- using only macro series that are genuinely already
public by that point. "Mixed-frequency" because the available
predictors update at different real cadences and lags (daily/weekly
Fed funds rate and NASDAQ returns, weekly unemployment claims and M2,
quarterly GDP, monthly CPI itself) and "information-release masks"
because every feature's availability at the decision date is computed
from the real `econosim.pit.PointInTimeStore` predicate, not assumed --
CPI for the CURRENT target month is always masked out by construction,
the same way a real nowcaster could never see it either.

See `data.py` for the dataset builder and its point-in-time guarantees,
`models.py` for the four candidate architectures (naive, linear,
hybrid-quantum, and a genuinely sequential GRU -- the one candidate
here that is a different architecture class from RECESSIONNET/
Q-MACRO's flattened-window MLP/quantum pair, and the one that reports
a calibrated uncertainty band, not just a point forecast), and
`evaluation.py` for the benchmark report and calibration test.
"""
