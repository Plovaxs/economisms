"""Model classes for the FP-08 ablation: a small GRU `TemporalEncoder`
(mirroring `inflationcast.models.InflationGRU`'s own GRU-encoder-plus-
head style) feeding either ONE shared pair of task heads (the "shared"
condition) or being independently instantiated once per task (the
"independent" condition) -- both conditions use the identical encoder
architecture, so a fair, matched-capacity comparison only requires
checking that every encoder instance has the same parameter count,
which `tests/unit/test_shared_encoder_ablation.py` does directly.
"""

from __future__ import annotations

import torch
from torch import nn

from prometheus.quantum.models import count_parameters

__all__ = [
    "InflationHead",
    "RecessionHead",
    "SharedEncoderModel",
    "SingleTaskModel",
    "TemporalEncoder",
    "count_parameters",
]


class TemporalEncoder(nn.Module):
    """`H_t = Encoder_theta(X_[t-L:t])`: a GRU over the trailing window
    of the 5 shared macro series, final hidden state as the latent
    representation. Identical in both the shared and independent
    conditions -- only how many of them exist, and whether their
    gradients are pooled across tasks, differs."""

    def __init__(self, n_series: int, hidden_size: int = 16, n_layers: int = 1) -> None:
        super().__init__()
        self.n_series = n_series
        self.hidden_size = hidden_size
        self.gru = nn.GRU(
            input_size=n_series, hidden_size=hidden_size, num_layers=n_layers, batch_first=True
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """`x` has shape (batch, window, n_series). Returns H_t, shape
        (batch, hidden_size)."""
        _, hidden = self.gru(x)
        last_hidden: torch.Tensor = hidden[-1]
        return last_hidden


class RecessionHead(nn.Module):
    """Linear probe producing a recession LOGIT (paired with
    `nn.BCEWithLogitsLoss`, the same convention `recessionnet.training`
    uses, rather than a sigmoid baked into the head)."""

    def __init__(self, hidden_size: int) -> None:
        super().__init__()
        self.linear = nn.Linear(hidden_size, 1)

    def forward(self, h: torch.Tensor) -> torch.Tensor:
        out: torch.Tensor = self.linear(h).squeeze(-1)
        return out


class InflationHead(nn.Module):
    """Linear probe producing a point CPI_YOY forecast (paired with
    `nn.MSELoss` -- point estimate only; INFLATIONCAST's own calibrated
    (mean, log-variance) framing is that module's separate concern, not
    duplicated here)."""

    def __init__(self, hidden_size: int) -> None:
        super().__init__()
        self.linear = nn.Linear(hidden_size, 1)

    def forward(self, h: torch.Tensor) -> torch.Tensor:
        out: torch.Tensor = self.linear(h).squeeze(-1)
        return out


class SingleTaskModel(nn.Module):
    """The "independent" condition's building block: one encoder, one
    head, trained on one task alone. Used twice (once per task) with
    two separately-initialized encoders."""

    def __init__(self, encoder: TemporalEncoder, head: nn.Module) -> None:
        super().__init__()
        self.encoder = encoder
        self.head = head

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out: torch.Tensor = self.head(self.encoder(x))
        return out


class SharedEncoderModel(nn.Module):
    """The "shared" condition: ONE encoder feeding BOTH heads, trained
    jointly on the multi-task objective
    `L = lambda_r * L_recession + lambda_i * L_inflation`."""

    def __init__(
        self, encoder: TemporalEncoder, recession_head: RecessionHead, inflation_head: InflationHead
    ) -> None:
        super().__init__()
        self.encoder = encoder
        self.recession_head = recession_head
        self.inflation_head = inflation_head

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        h = self.encoder(x)
        return self.recession_head(h), self.inflation_head(h)
