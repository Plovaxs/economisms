"""The shock transmission map: the response and the channel decomposition, and the page that draws
them."""

from __future__ import annotations

import numpy as np
import pytest

from prometheus.dashboard.transmission_view import (
    render_diagram,
    render_transmission,
    transmission_as_json,
)
from prometheus.worldsim.config import connected_scenario, scenario
from prometheus.worldsim.impulse import OUTCOMES
from prometheus.worldsim.transmission import (
    CHANNELS,
    MAX_SEEDS,
    SHOCK_ORIGIN,
    channel_effects,
    response_paths,
    shock_available,
    transmission_map,
)

SEEDS = [0, 1, 2, 3]


@pytest.fixture(scope="module")
def equity_crash() -> dict:
    return transmission_map(connected_scenario("stressed_connected"), "equity_crash", None, SEEDS)


def test_every_shock_has_an_origin_sector_and_every_channel_connects_two_sectors() -> None:
    sectors = {
        "markets",
        "banks",
        "households",
        "firms",
        "government",
        "foreign",
        "central_bank",
        "economy",
    }
    assert set(SHOCK_ORIGIN.values()) <= sectors
    for channel in CHANNELS:
        assert channel.source in sectors and channel.target in sectors
        assert channel.source != channel.target


def test_shocks_that_cannot_act_say_why() -> None:
    assert shock_available(scenario("volatile"), "equity_crash") is None
    assert "connected" in str(shock_available(scenario("volatile"), "sovereign_default"))
    assert "foreign" in str(shock_available(scenario("volatile"), "fx_crash"))
    assert "households" in str(shock_available(scenario("volatile"), "demand_shock"))
    with pytest.raises(ValueError):
        shock_available(scenario("volatile"), "meteor")
    result = transmission_map(scenario("volatile"), "sovereign_default", None, SEEDS)
    assert result["unavailable"] and result["response"] is None and result["channels"] == {}


def test_an_equity_crash_reaches_output_through_household_demand(equity_crash: dict) -> None:
    assert equity_crash["origin"] == "markets"
    outcomes = equity_crash["response"]["outcomes"]
    assert set(outcomes) == set(OUTCOMES)
    assert outcomes["output_gap"]["excludes_zero"] and outcomes["output_gap"]["estimate"] < 0.0
    demand = equity_crash["channels"]["demand"]["outcomes"]["output_gap"]
    assert demand["excludes_zero"]
    # nearly all of the output response is carried by that one loop
    assert abs(demand["estimate"]) > 0.5 * abs(outcomes["output_gap"]["estimate"])


def test_the_response_paths_start_flat_and_move_after_the_shock(equity_crash: dict) -> None:
    response = equity_crash["response"]
    months = response["months"]
    assert months[0] == -6 and months[-1] == 36 and months.index(0) == 6
    before = response["paths"]["output_gap"][: months.index(0)]
    assert all(abs(v) < 1e-12 for v in before)  # nothing happens before the shock
    assert min(response["paths"]["output_gap"]) < -0.2
    assert set(response["context"]) == {"banks_failed_at_shock", "crisis_at_shock_share"}


def test_a_world_without_links_has_only_the_two_always_on_channels() -> None:
    effects = channel_effects(scenario("calm"), "equity_crash", 0.30, SEEDS)
    assert set(effects) == {"fire_sales", "credit_crunch"}


def test_the_map_is_deterministic_and_seed_count_is_bounded(equity_crash: dict) -> None:
    again = transmission_map(connected_scenario("stressed_connected"), "equity_crash", None, SEEDS)
    assert again["response"]["paths"] == equity_crash["response"]["paths"]
    with pytest.raises(ValueError):
        transmission_map(scenario("calm"), "equity_crash", None, [0, 1])
    with pytest.raises(ValueError):
        transmission_map(scenario("calm"), "equity_crash", None, list(range(MAX_SEEDS + 1)))


def test_response_paths_reject_a_world_too_short_for_the_window() -> None:
    short = scenario("calm")
    from dataclasses import replace

    with pytest.raises(ValueError):
        response_paths(replace(short, n_months=120), "equity_crash", 0.3, SEEDS)


def test_the_page_draws_the_map_and_repeats_its_numbers_in_a_table() -> None:
    html = render_transmission(name="stressed_connected", shock="equity_crash", seeds=3)
    assert "SYNTHETIC" in html and "shock transmission map" in html
    assert (
        'data-channel="demand"' in html and "<table>" in html and "What each link carries" in html
    )
    assert html.count("<h1>") == 1
    json = transmission_as_json(name="stressed_connected", shock="equity_crash", seeds=3)
    assert json["synthetic"] is True and json["origin"] == "markets"
    diagram = render_diagram(json, "output_gap")
    assert diagram.startswith("<svg") and diagram.count("<circle") == 8


def test_the_page_rejects_unknown_inputs_and_explains_unavailable_shocks() -> None:
    with pytest.raises(ValueError):
        render_transmission(name="nope", seeds=3)
    with pytest.raises(ValueError):
        render_transmission(shock="meteor", seeds=3)
    with pytest.raises(ValueError):
        render_transmission(focus="vibes", seeds=3)
    with pytest.raises(ValueError):
        render_transmission(seeds=1)
    page = render_transmission(name="volatile", shock="sovereign_default", seeds=3)
    assert "Nothing to show" in page and "connected" in page


def test_the_effect_of_a_channel_is_the_full_response_minus_the_response_without_it() -> None:
    config = connected_scenario("stressed_connected")
    effects = channel_effects(config, "equity_crash", 0.30, SEEDS)
    full = response_paths(config, "equity_crash", 0.30, SEEDS)["outcomes"]["output_gap"]["estimate"]
    from dataclasses import replace

    off = replace(config, links=replace(config.links, demand_coupling=0.0))
    reduced = response_paths(off, "equity_crash", 0.30, SEEDS)["outcomes"]["output_gap"]["estimate"]
    assert effects["demand"]["output_gap"]["estimate"] == pytest.approx(full - reduced, abs=1e-9)
    assert np.isfinite(effects["demand"]["output_gap"]["low"])
