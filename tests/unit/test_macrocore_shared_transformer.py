import torch

from prometheus.macrocore.shared_transformer import (
    LinearMultihorizon,
    SharedMultihorizonMLP,
    SharedMultihorizonTransformer,
)
from prometheus.quantum.models import count_parameters

_WINDOW = 6
_N_FEATURE_SERIES = 5
_N_OUTPUTS = 9
_INPUT_DIM = _WINDOW * _N_FEATURE_SERIES


def test_shared_transformer_produces_the_right_output_shape() -> None:
    model = SharedMultihorizonTransformer(_WINDOW, _N_FEATURE_SERIES, _N_OUTPUTS)
    x = torch.randn(4, _INPUT_DIM)
    output = model(x)
    assert output.shape == (4, _N_OUTPUTS)


def test_shared_transformer_is_a_genuine_shared_encoder_not_separate_per_output_models() -> None:
    """Gradients from EVERY output column must reach the SAME encoder
    weights -- the literal "shared encoder" claim, verified rather than
    assumed from the architecture diagram."""
    model = SharedMultihorizonTransformer(_WINDOW, _N_FEATURE_SERIES, _N_OUTPUTS)
    x = torch.randn(4, _INPUT_DIM)
    for output_index in range(_N_OUTPUTS):
        model.zero_grad()
        output = model(x)
        output[:, output_index].sum().backward()
        assert model.input_proj.weight.grad is not None
        assert torch.any(model.input_proj.weight.grad != 0.0)


def test_shared_transformer_and_classical_mlp_have_a_reasonably_matched_parameter_count() -> None:
    transformer = SharedMultihorizonTransformer(_WINDOW, _N_FEATURE_SERIES, _N_OUTPUTS)
    mlp = SharedMultihorizonMLP(_INPUT_DIM, _N_OUTPUTS)
    transformer_params = count_parameters(transformer)
    mlp_params = count_parameters(mlp)
    assert transformer_params > 0
    assert mlp_params > 0
    ratio = max(transformer_params, mlp_params) / min(transformer_params, mlp_params)
    assert ratio < 1.5


def test_linear_multihorizon_is_a_plain_linear_layer_with_no_hidden_nonlinearity() -> None:
    model = LinearMultihorizon(_INPUT_DIM, _N_OUTPUTS)
    assert count_parameters(model) == _INPUT_DIM * _N_OUTPUTS + _N_OUTPUTS
    x = torch.randn(3, _INPUT_DIM)
    output = model(x)
    assert output.shape == (3, _N_OUTPUTS)
