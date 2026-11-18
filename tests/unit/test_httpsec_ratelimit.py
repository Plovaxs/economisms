from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from prometheus.httpsec.ratelimit import TokenBucketLimiter, client_key


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def limiter(clock: _Clock, **kw) -> TokenBucketLimiter:
    params = {"rate_per_second": 1.0, "burst": 3, "max_keys": 4096, "clock": clock}
    params.update(kw)
    return TokenBucketLimiter(**params)  # type: ignore[arg-type]


def test_a_fresh_client_gets_its_whole_burst_then_is_denied() -> None:
    clock = _Clock()
    lim = limiter(clock)
    assert [lim.acquire("a").allowed for _ in range(5)] == [True, True, True, False, False]


def test_the_denial_says_how_long_until_one_token_exists() -> None:
    clock = _Clock()
    lim = limiter(clock, rate_per_second=2.0)
    for _ in range(3):
        lim.acquire("a")
    denied = lim.acquire("a")
    assert denied.allowed is False
    assert denied.retry_after_seconds == pytest.approx(0.5)
    clock.now += denied.retry_after_seconds
    assert lim.acquire("a").allowed is True


def test_tokens_refill_continuously_but_never_beyond_the_burst() -> None:
    clock = _Clock()
    lim = limiter(clock)
    for _ in range(3):
        lim.acquire("a")
    clock.now += 1000.0
    assert [lim.acquire("a").allowed for _ in range(5)] == [True, True, True, False, False]


def test_clients_are_independent() -> None:
    clock = _Clock()
    lim = limiter(clock)
    for _ in range(3):
        lim.acquire("a")
    assert lim.acquire("a").allowed is False
    assert lim.acquire("b").allowed is True


def test_a_clock_that_goes_backwards_never_mints_tokens() -> None:
    clock = _Clock()
    clock.now = 100.0
    lim = limiter(clock)
    for _ in range(3):
        lim.acquire("a")
    clock.now = 50.0
    assert lim.acquire("a").allowed is False


@pytest.mark.parametrize(
    "kwargs",
    [
        {"rate_per_second": 0},
        {"rate_per_second": -1},
        {"rate_per_second": float("inf")},
        {"rate_per_second": float("nan")},
        {"rate_per_second": True},
        {"burst": 0},
        {"burst": 1.5},
        {"max_keys": 0},
    ],
)
def test_constructor_rejects_nonsense(kwargs) -> None:
    with pytest.raises(ValueError):
        limiter(_Clock(), **kwargs)


def test_memory_is_bounded_and_overflow_clients_share_one_bucket() -> None:
    clock = _Clock()
    lim = limiter(clock, max_keys=3)
    for key in ("a", "b", "c"):
        assert lim.acquire(key).allowed is True
    assert len(lim) == 3
    # The table is full of ACTIVE clients: every further new address shares the
    # overflow bucket instead of being allocated its own entry.
    results = [lim.acquire(f"new-{i}").allowed for i in range(8)]
    assert len(lim) == 3, "a full table must not grow"
    assert results.count(True) == 3, "the shared overflow bucket spends only one burst"
    assert results[3:] == [False] * 5


def test_idle_clients_are_reclaimed_so_new_ones_get_their_own_bucket_again() -> None:
    clock = _Clock()
    lim = limiter(clock, max_keys=2)
    lim.acquire("a")
    lim.acquire("b")
    clock.now += 10.0  # both fully refilled == indistinguishable from brand new
    lim.acquire("c")
    assert len(lim) <= 2
    assert "c" in lim._buckets


def test_the_reclaim_scan_runs_at_most_once_a_second() -> None:
    clock = _Clock()
    lim = limiter(clock, max_keys=2)
    lim.acquire("a")
    lim.acquire("b")
    lim.acquire("x")  # table full, nothing idle yet: sweep runs and finds nothing
    sweep_at = lim._next_sweep
    for i in range(50):
        lim.acquire(f"flood-{i}")
    assert lim._next_sweep == sweep_at, "a flood must not trigger a scan per request"


@given(
    st.lists(
        st.tuples(st.integers(0, 12), st.floats(0, 3, allow_nan=False)),
        min_size=1,
        max_size=300,
    )
)
@settings(max_examples=200, deadline=None)
def test_property_memory_and_token_bounds_hold_under_any_traffic(ops) -> None:
    clock = _Clock()
    lim = limiter(clock, rate_per_second=2.0, burst=5, max_keys=4)
    for key_id, step in ops:
        clock.now += step
        decision = lim.acquire(f"k{key_id}")
        assert len(lim) <= 4
        for tokens, _ in lim._buckets.values():
            assert -1e-9 <= tokens <= 5.0 + 1e-9
        if not decision.allowed:
            assert decision.retry_after_seconds > 0


@given(
    st.lists(
        st.tuples(st.integers(0, 3), st.floats(0, 3, allow_nan=False)),
        min_size=1,
        max_size=300,
    )
)
@settings(max_examples=200, deadline=None)
def test_property_a_client_never_exceeds_burst_plus_rate_times_elapsed(ops) -> None:
    """The defining token-bucket bound, exact (no slack): with no more clients
    than table slots, nothing is evicted or shared, so for EVERY client the
    number of admitted requests in any run is <= burst + rate * duration."""
    clock = _Clock()
    lim = limiter(clock, rate_per_second=2.0, burst=5, max_keys=4)
    admitted: dict[int, list[float]] = {}
    for key_id, step in ops:
        clock.now += step
        if lim.acquire(f"k{key_id}").allowed:
            admitted.setdefault(key_id, []).append(clock.now)
    for times in admitted.values():
        assert len(times) <= 5 + 2.0 * (times[-1] - times[0]) + 1e-6


def test_client_key_normalization() -> None:
    assert client_key("203.0.113.7") == "203.0.113.7"
    assert client_key("2001:db8:1:2:aaaa:bbbb:cccc:dddd") == "2001:db8:1:2::/64"
    assert client_key("2001:db8:1:2::1") == client_key("2001:db8:1:2:ffff::9")
    assert client_key("2001:db8:1:3::1") != client_key("2001:db8:1:2::1")
    assert client_key("::ffff:203.0.113.7") == "203.0.113.7"
    assert client_key(None) == "unknown"
    assert client_key("") == "unknown"
    assert client_key("/run/gateway.sock") == "/run/gateway.sock"
    assert len(client_key("x" * 500)) == 64
