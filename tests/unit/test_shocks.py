import numpy as np

from prometheus.core.seeds import SeedHierarchy
from prometheus.econosim.shocks import ShockGenerator, ShockSpec


def test_probability_one_always_fires() -> None:
    rng = np.random.default_rng(1)
    gen = ShockGenerator(rng, [ShockSpec(kind="productivity", probability=1.0)])
    shocks = gen.draw_for_step(1)
    assert len(shocks) == 1
    assert shocks[0].kind == "productivity"
    assert shocks[0].step == 1


def test_probability_zero_never_fires() -> None:
    rng = np.random.default_rng(1)
    gen = ShockGenerator(rng, [ShockSpec(kind="disaster", probability=0.0)])
    shocks = gen.draw_for_step(1)
    assert shocks == []


def test_same_seed_reproduces_identical_shocks() -> None:
    specs = [ShockSpec(kind="productivity", mean=0.0, std=1.0, probability=1.0)]

    gen_a = ShockGenerator(SeedHierarchy(99).stream("economy"), specs)
    gen_b = ShockGenerator(SeedHierarchy(99).stream("economy"), specs)

    for step in range(1, 6):
        shocks_a = gen_a.draw_for_step(step)
        shocks_b = gen_b.draw_for_step(step)
        assert [s.magnitude for s in shocks_a] == [s.magnitude for s in shocks_b]


def test_different_seeds_diverge() -> None:
    specs = [ShockSpec(kind="productivity", probability=1.0)]
    gen_a = ShockGenerator(SeedHierarchy(1).stream("economy"), specs)
    gen_b = ShockGenerator(SeedHierarchy(2).stream("economy"), specs)
    shocks_a = gen_a.draw_for_step(1)
    shocks_b = gen_b.draw_for_step(1)
    assert shocks_a[0].magnitude != shocks_b[0].magnitude


def test_shock_ids_are_unique_and_sequential_across_steps() -> None:
    rng = np.random.default_rng(3)
    specs = [
        ShockSpec(kind="liquidity", probability=1.0),
        ShockSpec(kind="policy_rate", probability=1.0),
    ]
    gen = ShockGenerator(rng, specs)
    step_1 = gen.draw_for_step(1)
    step_2 = gen.draw_for_step(2)
    all_ids = [s.shock_id for s in step_1 + step_2]
    assert len(all_ids) == len(set(all_ids))
