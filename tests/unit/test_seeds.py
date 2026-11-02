from prometheus.core.seeds import SeedHierarchy


def test_same_root_seed_and_name_reproduce_draws() -> None:
    draws_a = SeedHierarchy(42).stream("economy").standard_normal(5)
    draws_b = SeedHierarchy(42).stream("economy").standard_normal(5)
    assert list(draws_a) == list(draws_b)


def test_different_names_diverge() -> None:
    h = SeedHierarchy(42)
    economy_draws = h.stream("economy").standard_normal(5)
    market_draws = h.stream("market").standard_normal(5)
    assert list(economy_draws) != list(market_draws)


def test_different_root_seeds_diverge() -> None:
    draws_a = SeedHierarchy(1).stream("economy").standard_normal(5)
    draws_b = SeedHierarchy(2).stream("economy").standard_normal(5)
    assert list(draws_a) != list(draws_b)


def test_stream_identity_is_independent_of_request_order() -> None:
    """The crux property: two hierarchies built from the same root seed
    must produce identical per-name draws no matter what order (or how many
    other names) each one requests streams in first."""
    h1 = SeedHierarchy(7)
    h1.stream("market")  # touch market first
    economy_after_market = h1.stream("economy").standard_normal(3)

    h2 = SeedHierarchy(7)
    economy_first = h2.stream("economy").standard_normal(3)  # touch economy first, nothing else

    assert list(economy_after_market) == list(economy_first)


def test_repeated_calls_return_the_same_generator_object() -> None:
    h = SeedHierarchy(1)
    gen_a = h.stream("evaluation")
    gen_b = h.stream("evaluation")
    assert gen_a is gen_b


def test_spawned_names_tracks_requested_streams() -> None:
    h = SeedHierarchy(1)
    h.stream("economy")
    h.stream("market")
    assert set(h.spawned_names()) == {"economy", "market"}
