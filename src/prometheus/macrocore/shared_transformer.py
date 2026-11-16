"""FP-05's own missing architecture: a shared Transformer encoder over
one trailing macro window, jointly predicting every (target series,
horizon) pair at once -- the literal "shared Transformer encoder
forecasting GDP, rates AND unemployment across multiple horizons"
wording, not an approximation of it.

`SharedMultihorizonTransformer.forward` takes the SAME flat
`(window * n_feature_series,)` feature vector every other MACROCORE
candidate (`quantum.models.LinearRegressionModel`,
`ClassicalMatchedRegressor`) already consumes -- reshaped internally
back into `(window, n_feature_series)` tokens, one token per month --
so `recessionnet.training.train_classifier_with_early_stopping` needs
no changes to train it: that loop only ever assumes a 2-D
`(n_samples, input_dim)` tensor in, a tensor out, same as every prior
MACROCORE/RECESSIONNET/INFLATIONCAST candidate.

`SharedMultihorizonMLP` is the classical counterpart this project's
own convention always benchmarks a new architecture against: a shared
trunk (not a separate small network per target/horizon) feeding one
joint linear head, the same "one encoder, many outputs" shape as the
Transformer, sized so its parameter count is close to (not forced
exactly equal to -- unlike FP-08's deliberate matched-capacity
ablation, matching here is a reasonable-effort disclosure, not the
comparison's own point) the Transformer's own count. `LinearMultihorizon`
is ordinary multivariate linear regression: one `Linear(input_dim,
n_outputs)`, no nonlinearity, no sharing claim at all -- the simplest
real baseline a joint model must clear.
"""

from __future__ import annotations

import torch
from torch import nn


class SharedMultihorizonTransformer(nn.Module):
    def __init__(
        self,
        window: int,
        n_feature_series: int,
        n_outputs: int,
        *,
        d_model: int = 16,
        nhead: int = 2,
        num_layers: int = 1,
        dim_feedforward: int = 32,
    ) -> None:
        super().__init__()
        self.window = window
        self.n_feature_series = n_feature_series
        self.input_proj = nn.Linear(n_feature_series, d_model)
        self.position_embedding = nn.Parameter(torch.zeros(window, d_model))
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=nhead,
            dim_feedforward=dim_feedforward,
            batch_first=True,
        )
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)
        self.head = nn.Linear(d_model, n_outputs)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        batch_size = x.shape[0]
        tokens = x.view(batch_size, self.window, self.n_feature_series)
        embedded = self.input_proj(tokens) + self.position_embedding
        encoded = self.encoder(embedded)
        most_recent = encoded[:, -1, :]
        output: torch.Tensor = self.head(most_recent)
        return output


class SharedMultihorizonMLP(nn.Module):
    def __init__(self, input_dim: int, n_outputs: int, *, hidden_size: int = 64) -> None:
        super().__init__()
        self.trunk = nn.Sequential(nn.Linear(input_dim, hidden_size), nn.Tanh())
        self.head = nn.Linear(hidden_size, n_outputs)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        output: torch.Tensor = self.head(self.trunk(x))
        return output


class LinearMultihorizon(nn.Module):
    def __init__(self, input_dim: int, n_outputs: int) -> None:
        super().__init__()
        self.linear = nn.Linear(input_dim, n_outputs)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        output: torch.Tensor = self.linear(x)
        return output
