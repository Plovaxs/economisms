from datetime import date

from prometheus.core.calendar import BusinessDayCalendar
from prometheus.core.money import Money
from prometheus.core.seeds import SeedHierarchy
from prometheus.econosim.economy import Economy
from prometheus.econosim.pit import MacroObservation, PointInTimeStore
from prometheus.econosim.shocks import ShockGenerator, ShockSpec
from prometheus.econosim.time_engine import MacroTimeEngine


def _build_engine(seed: int = 1) -> MacroTimeEngine:
    economy = Economy()
    bank = economy.add_bank("bank-1", max_leverage=10.0)
    bank.capitalize(Money(1_000_000_00, "USD"))
    economy.add_household("hh-1")

    store = PointInTimeStore()
    store.record(
        MacroObservation(
            series_id="CPI",
            observation_at=date(2026, 1, 1),
            published_at=date(2026, 2, 10),
            value=3.0,
        )
    )
    store.record(
        MacroObservation(
            series_id="CPI",
            observation_at=date(2026, 3, 1),
            published_at=date(2026, 4, 10),
            value=3.2,
        )
    )

    shock_gen = ShockGenerator(
        SeedHierarchy(seed).stream("economy"),
        [ShockSpec(kind="productivity", mean=0.0, std=0.01, probability=1.0)],
    )

    return MacroTimeEngine(
        economy=economy,
        calendar=BusinessDayCalendar(),
        start=date(2026, 1, 1),
        shock_generator=shock_gen,
        point_in_time_store=store,
    )


def test_clock_advances_one_month_per_step_snapped_to_business_day() -> None:
    engine = _build_engine()
    assert engine.clock.current_date == date(2026, 1, 1)  # already a business day (Thursday)

    result_1 = engine.advance_step()
    assert result_1.step == 1
    assert result_1.step_date == date(2026, 2, 2)  # Feb 1 2026 is a Sunday -> snaps to Monday

    result_2 = engine.advance_step()
    assert result_2.step == 2
    assert result_2.step_date == date(2026, 3, 2)  # Mar 1 2026 is a Sunday -> snaps to Monday


def test_economy_step_index_tracks_clock() -> None:
    engine = _build_engine()
    engine.advance_step()
    engine.advance_step()
    assert engine.economy.step_index == engine.clock.step_index == 2


def test_point_in_time_data_is_not_visible_before_its_publication_step() -> None:
    """The CPI observation published 2026-04-10 must not be visible at step
    1 (date 2026-02-02) but must be visible once the clock reaches it."""
    engine = _build_engine()

    result_1 = engine.advance_step()  # date 2026-02-02
    released_series_1 = {o.series_id for o in result_1.released}
    assert "CPI" not in released_series_1  # first CPI obs not published until 2026-02-10

    result_2 = engine.advance_step()  # date 2026-03-02
    released_series_2 = {(o.series_id, o.observation_at) for o in result_2.released}
    assert ("CPI", date(2026, 1, 1)) in released_series_2
    assert ("CPI", date(2026, 3, 1)) not in released_series_2  # published 2026-04-10, still future

    result_3 = engine.advance_step()  # date 2026-04-02 (Apr 1 2026 is a Wednesday)
    released_series_3 = {(o.series_id, o.observation_at) for o in result_3.released}
    assert ("CPI", date(2026, 3, 1)) not in released_series_3  # still before 2026-04-10

    result_4 = engine.advance_step()  # date 2026-05-04 (Mon; May 2 is a Saturday)
    released_series_4 = {(o.series_id, o.observation_at) for o in result_4.released}
    assert ("CPI", date(2026, 3, 1)) in released_series_4  # now published


def test_shocks_are_tagged_with_the_arriving_step() -> None:
    engine = _build_engine()
    result = engine.advance_step()
    assert len(result.shocks) == 1
    assert result.shocks[0].step == 1
    assert result.shocks[0].kind == "productivity"
    assert engine.shock_log == list(result.shocks)


def test_state_hash_is_reproducible_across_independent_replays() -> None:
    def run() -> str:
        engine = _build_engine(seed=123)
        hh = engine.economy.households["hh-1"]
        bank = engine.economy.banks["bank-1"]
        engine.advance_step()
        bank.originate_loan(hh, Money(500_00, "USD"))
        result = engine.advance_step()
        return result.state_hash

    assert run() == run()


def test_state_hash_diverges_for_different_economic_history() -> None:
    def run(loan_amount_cents: int) -> str:
        engine = _build_engine(seed=123)
        hh = engine.economy.households["hh-1"]
        bank = engine.economy.banks["bank-1"]
        engine.advance_step()
        bank.originate_loan(hh, Money(loan_amount_cents, "USD"))
        result = engine.advance_step()
        return result.state_hash

    assert run(500_00) != run(600_00)
