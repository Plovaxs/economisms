from dataclasses import replace
from fractions import Fraction

import pytest

from prometheus.orchestration.recipes import (
    RUNNERS,
    ResourceLimitError,
    ResourceLimits,
    default_recipe,
    prepare_recipe,
)


@pytest.mark.parametrize("kind", sorted(RUNNERS))
def test_every_default_recipe_is_typed_canonical_and_admitted(kind):
    raw = default_recipe(kind)
    plan = prepare_recipe(kind, raw, limits=ResourceLimits())
    again = prepare_recipe(kind, plan.config, limits=ResourceLimits())
    assert plan == again and plan.estimate.steps > 0
    modified = plan.config
    modified["seed"] = 123
    assert plan.config["seed"] != 123
    assert (
        prepare_recipe(kind, modified, limits=ResourceLimits()).recipe_sha256 != plan.recipe_sha256
    )


@pytest.mark.parametrize("kind", sorted(RUNNERS))
def test_all_runner_decoders_reject_missing_or_extra_fields(kind):
    raw = default_recipe(kind)
    del raw["seed"]
    with pytest.raises(ValueError):
        prepare_recipe(kind, raw, limits=ResourceLimits())
    raw = default_recipe(kind)
    raw["unknown"] = 1
    with pytest.raises(ValueError):
        prepare_recipe(kind, raw, limits=ResourceLimits())


def test_large_cardinalities_are_rejected_before_decoder_or_training_import(monkeypatch):
    import prometheus.orchestration.recipes as module

    raw = {"n_steps": 10**12}

    def forbidden(*args):
        pytest.fail("resource preflight must precede the runner import")

    monkeypatch.setattr(module, "_config_class", forbidden)
    with pytest.raises(ResourceLimitError, match="n_steps"):
        prepare_recipe("economy", raw, limits=ResourceLimits())


def test_crossed_work_and_nested_resampling_are_bounded_even_when_each_axis_fits():
    raw = default_recipe("mixture_study")
    plan = prepare_recipe("mixture_study", raw, limits=ResourceLimits())
    assert plan.estimate.fitted_models == 6
    assert plan.estimate.training_macro_banks == 3
    assert plan.estimate.bootstrap_work > 100_000_000
    with pytest.raises(ResourceLimitError, match="bootstrap_work"):
        prepare_recipe(
            "mixture_study", raw, limits=replace(ResourceLimits(), max_bootstrap_work=100)
        )


def test_encoded_fraction_precision_and_raw_structure_have_preflight_limits():
    raw = default_recipe("economy")
    raw["productivity"] = Fraction(1, 2**100)
    with pytest.raises(ResourceLimitError, match="precision"):
        prepare_recipe("economy", raw, limits=ResourceLimits())
    with pytest.raises(ResourceLimitError, match="depth"):
        prepare_recipe(
            "economy", {"a": {"b": {"c": 1}}}, limits=replace(ResourceLimits(), max_depth=1)
        )


def test_unknown_runner_cannot_become_an_arbitrary_module_import():
    with pytest.raises(ValueError, match="unsupported"):
        prepare_recipe("os.system", {})


def test_economic_work_is_bounded_when_individual_shape_limits_fit():
    raw = default_recipe("economy")
    raw["n_households"] = 1000
    with pytest.raises(ResourceLimitError, match="economic_work"):
        prepare_recipe("economy", raw, limits=replace(ResourceLimits(), max_economic_work=100))


def test_runner_allowlist_is_immutable():
    with pytest.raises(TypeError):
        RUNNERS["unknown"] = RUNNERS["economy"]


def test_object_cardinality_is_checked_before_expanding_the_traversal_stack():
    with pytest.raises(ResourceLimitError, match="node budget"):
        prepare_recipe(
            "economy",
            {str(n): 0 for n in range(100)},
            limits=replace(ResourceLimits(), max_nodes=10),
        )
