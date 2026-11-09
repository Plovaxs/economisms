"""NSD-03/NSD-04: the drift/diffusion network and its by-construction
guarantees.

NSD-03 ("every sampled covariance eigenvalue within numeric tolerance")
is enforced by parameterizing the diffusion output as a Cholesky factor
L (lower-triangular, strictly positive diagonal via a bounded softplus)
and returning Sigma = L @ L^T. A matrix constructed this way is PSD for
ANY finite L -- there is no "adversarial" finite input that can produce
a negative eigenvalue, which is why this module's tests check many
random/extreme inputs rather than trying to enumerate counterexamples.

NSD-04 ("control variance and price positivity by construction") is
written for a price-like state variable; this package's actual state
variables (see `neural_sde.design`) are YoY growth-rate series that are
negative in the real data (real GDP YoY fell to -7.69% in 2020-05, its
most negative value in the entire 1981-2023 sample -- see
`neural_sde.ood`), so a literal positivity constraint would be false of
the system being modeled. The honest substitute enforced here -- and disclosed, not
silently substituted -- is BOUNDEDNESS: both the drift and the diffusion
Cholesky entries are passed through a bounded squashing function
(tanh/sigmoid) scaled by a fixed constant, so no finite input, however
extreme, can produce an unbounded or non-finite output. A separate
explicit guard (`_reject_non_finite_input`) rejects non-finite (NaN/Inf)
*inputs* outright rather than relying on the squashing functions'
behavior at infinity (tanh(inf) is finite, but a NaN propagates through
every op unchanged, so it must be caught before, not after).
"""

from __future__ import annotations

import torch
from torch import nn

DRIFT_BOUND = 5.0
"""Hard cap (in state units per unit time) on |drift| -- a generously
wide bound relative to the real data (the largest single-month real
NASDAQ_YOY swing seen in training data is well under this), chosen so
the bound is a genuine safety rail, not a binding constraint under
normal conditions."""

DIFFUSION_SCALE = 10.0
MIN_DIFFUSION_DIAGONAL = 1e-4
"""Added to every Cholesky diagonal entry so Sigma is always strictly
positive definite (eigenvalues > 0, not merely >= 0) -- avoids a
degenerate zero-variance transition density that would make the
Gaussian log-likelihood loss in `neural_sde.training` blow up to
+inf."""


def _reject_non_finite_input(x: torch.Tensor, context: str) -> None:
    if not torch.all(torch.isfinite(x)):
        raise ValueError(f"{context}: input contains NaN or Inf -- refusing to evaluate")


class DriftDiffusionNet(nn.Module):
    """mu_theta, Sigma_theta = f_theta(t, X_t, regime_t).

    Input: concatenation of [t_scaled (1), state (state_dim), regime
    (regime_dim)]. Output: drift (state_dim,) and a Cholesky factor L
    (state_dim, state_dim) with Sigma = L @ L^T.

    Only state_dim in {1, 2} is exercised by this package's tests and
    callers; the Cholesky construction below generalizes to any
    state_dim, but is only validated at those sizes.
    """

    def __init__(self, state_dim: int, regime_dim: int, hidden_size: int = 16) -> None:
        super().__init__()
        if state_dim < 1:
            raise ValueError("state_dim must be >= 1")
        if regime_dim < 0:
            raise ValueError("regime_dim must be >= 0")
        self.state_dim = state_dim
        self.regime_dim = regime_dim
        input_dim = 1 + state_dim + regime_dim
        n_chol_entries = state_dim * (state_dim + 1) // 2
        self._tril_rows, self._tril_cols = torch.tril_indices(state_dim, state_dim)
        self._diag_mask = self._tril_rows == self._tril_cols

        self.encoder = nn.Sequential(
            nn.Linear(input_dim, hidden_size),
            nn.Tanh(),
            nn.Linear(hidden_size, hidden_size),
            nn.Tanh(),
        )
        self.drift_head = nn.Linear(hidden_size, state_dim)
        self.chol_head = nn.Linear(hidden_size, n_chol_entries)

    def forward(
        self, t_scaled: torch.Tensor, state: torch.Tensor, regime: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """t_scaled: (batch, 1). state: (batch, state_dim). regime:
        (batch, regime_dim). Returns (drift (batch, state_dim), Sigma
        (batch, state_dim, state_dim))."""
        _reject_non_finite_input(t_scaled, "DriftDiffusionNet.forward: t_scaled")
        _reject_non_finite_input(state, "DriftDiffusionNet.forward: state")
        _reject_non_finite_input(regime, "DriftDiffusionNet.forward: regime")
        if t_scaled.shape[-1] != 1:
            raise ValueError("t_scaled must have a trailing dimension of size 1")
        if state.shape[-1] != self.state_dim:
            raise ValueError(f"state must have trailing dimension {self.state_dim}")
        if regime.shape[-1] != self.regime_dim:
            raise ValueError(f"regime must have trailing dimension {self.regime_dim}")

        x = torch.cat([t_scaled, state, regime], dim=-1)
        hidden = self.encoder(x)

        raw_drift = self.drift_head(hidden)
        drift = DRIFT_BOUND * torch.tanh(raw_drift)

        raw_chol = self.chol_head(hidden)
        batch_shape = raw_chol.shape[:-1]
        L = torch.zeros(*batch_shape, self.state_dim, self.state_dim, dtype=raw_chol.dtype)
        diag_entries = raw_chol[..., self._diag_mask]
        offdiag_entries = raw_chol[..., ~self._diag_mask]
        diag_values = MIN_DIFFUSION_DIAGONAL + DIFFUSION_SCALE * torch.sigmoid(diag_entries)
        offdiag_values = DIFFUSION_SCALE * torch.tanh(offdiag_entries)

        diag_rows = self._tril_rows[self._diag_mask]
        diag_cols = self._tril_cols[self._diag_mask]
        offdiag_rows = self._tril_rows[~self._diag_mask]
        offdiag_cols = self._tril_cols[~self._diag_mask]
        L[..., diag_rows, diag_cols] = diag_values
        if offdiag_rows.numel() > 0:
            L[..., offdiag_rows, offdiag_cols] = offdiag_values

        sigma = L @ L.transpose(-2, -1)
        # NSD-12: a NaN/Inf PARAMETER (not input -- that is guarded above)
        # would otherwise flow silently through tanh/sigmoid (both of
        # which pass NaN through unchanged, unlike their behavior at
        # infinity) into a silently-corrupted drift/sigma. Guarding the
        # output, not just the input, is what lets `training._check_integrity`
        # catch a corrupted MODEL, not only a corrupted loss/gradient.
        _reject_non_finite_input(drift, "DriftDiffusionNet.forward: drift output")
        _reject_non_finite_input(sigma, "DriftDiffusionNet.forward: sigma output")
        return drift, sigma
