"""PDE/BSDE numerical option-pricing methods (PDE-01..PDE-12).

Three independent ways to solve the SAME pricing problem -- a classical
finite-difference grid solver (`grid`), a physics-informed neural
network (`pinn`), and a deep BSDE solver (`deep_bsde`) -- cross-checked
against VOLTERRA's existing closed-form Black-Scholes solution
(`prometheus.volterra.black_scholes`) as ground truth, and against each
other once the problem is extended to a basket option where no closed
form exists. `benchmark` runs and reports the comparison; `problem`
defines the shared PDE/BSDE specification (domain, terminal and
boundary conditions) both solvers are built from, so neither grid nor
PINN nor deep BSDE can silently drift from a different problem
definition than the one being reported on.
"""
