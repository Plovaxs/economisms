"""`dashboard.params` is pure, so it is checked exhaustively: the named
payloads that used to crash or exhaust a dashboard process, and Hypothesis
properties over arbitrary text."""

from __future__ import annotations

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from prometheus.dashboard.params import (
    MAX_QUERY_BYTES,
    FloatRange,
    ParamError,
    float_param,
    int_param,
    parse_query,
    token_param,
    wants_json,
)

PRICE = FloatRange(0.0, 1e7, lo_open=True)
RATE = FloatRange(-0.5, 1.0)


def test_defaults_are_returned_when_a_parameter_is_absent() -> None:
    assert int_param({}, "n", 250, lo=10, hi=100) == 250
    assert float_param({}, "x", 0.2, RATE) == 0.2
    assert token_param({}, "view") == ""
    assert token_param({}, "view", "d") == "d"


def test_ordinary_values_are_parsed() -> None:
    assert int_param({"n": ["42"]}, "n", 0, lo=1, hi=100) == 42
    assert float_param({"x": ["0.25"]}, "x", 0.0, RATE) == 0.25
    assert float_param({"x": ["-0.25"]}, "x", 0.0, RATE) == -0.25
    assert float_param({"x": ["1e-2"]}, "x", 0.0, RATE) == 0.01
    assert float_param({"x": [".5"]}, "x", 0.0, RATE) == 0.5
    assert token_param({"v": ["audit-trail_1.0:x"]}, "v") == "audit-trail_1.0:x"


@pytest.mark.parametrize(
    "value", ["0", "101", "-1", "1.5", "abc", "", " 5", "5 ", "0x10", "1_0", "١٢"]
)
def test_ints_outside_the_range_or_not_plain_decimals_are_400(value: str) -> None:
    with pytest.raises(ParamError) as raised:
        int_param({"n": [value]}, "n", 5, lo=1, hi=100)
    assert raised.value.status == 400
    assert "n must be an integer between 1 and 100" in raised.value.message


@pytest.mark.parametrize(
    "value",
    [
        "nan",
        "NaN",
        "inf",
        "-inf",
        "Infinity",
        "1e999",
        "1_0",
        "0x1",
        "1e",
        "--1",
        "1.2.3",
        "",
        "٣",
        "2",
    ],
)
def test_floats_that_are_not_finite_plain_decimals_in_range_are_400(value: str) -> None:
    with pytest.raises(ParamError):
        float_param({"x": [value]}, "x", 0.0, RATE)


def test_an_open_lower_bound_excludes_the_bound_itself() -> None:
    assert float_param({"x": ["0.0001"]}, "x", 1.0, PRICE) == 0.0001
    with pytest.raises(ParamError, match="greater than 0.0"):
        float_param({"x": ["0"]}, "x", 1.0, PRICE)


def test_the_upper_bound_is_inclusive() -> None:
    assert float_param({"x": ["1"]}, "x", 0.0, RATE) == 1.0
    with pytest.raises(ParamError):
        float_param({"x": ["1.0000001"]}, "x", 0.0, RATE)


@pytest.mark.parametrize("value", ["a b", "a/b", "a;b", "<script>", "é", "a" * 129, "a%20b"])
def test_tokens_are_a_closed_character_set(value: str) -> None:
    with pytest.raises(ParamError):
        token_param({"v": [value]}, "v")


def test_a_repeated_parameter_is_ambiguous_and_refused() -> None:
    with pytest.raises(ParamError, match="at most once"):
        int_param({"n": ["1", "2"]}, "n", 0, lo=0, hi=10)
    with pytest.raises(ParamError, match="at most once"):
        float_param({"x": ["0.1", "0.2"]}, "x", 0.0, RATE)
    with pytest.raises(ParamError, match="at most once"):
        token_param({"v": ["a", "b"]}, "v")


def test_parse_query_accepts_ordinary_queries() -> None:
    assert parse_query(b"") == {}
    assert parse_query(b"format=json&n_steps=3") == {"format": ["json"], "n_steps": ["3"]}
    assert parse_query(b"a=&b=2") == {"a": [""], "b": ["2"]}


@pytest.mark.parametrize(
    ("raw", "status"),
    [
        (b"q=\xc3\xa9", 400),
        (b"noequals", 400),
        (b"a=1&&b=2", 400),
        (b"&".join(b"k%d=1" % i for i in range(40)), 400),
        (b"x=" + b"a" * (MAX_QUERY_BYTES + 1), 414),
    ],
)
def test_malformed_oversized_or_non_ascii_queries_are_refused(raw: bytes, status: int) -> None:
    with pytest.raises(ParamError) as raised:
        parse_query(raw)
    assert raised.value.status == status


def test_wants_json_is_tolerant_of_a_query_too_broken_to_parse() -> None:
    assert wants_json(b"format=json") is True
    assert wants_json(b"n=1") is False
    assert wants_json(b"") is False
    assert wants_json(b"q=\xc3\xa9") is True


@settings(max_examples=500, deadline=None)
@given(st.text(max_size=40), st.integers(-5, 5), st.integers(5, 100))
def test_property_an_int_param_either_raises_param_error_or_lands_in_range(
    text: str, lo: int, hi: int
) -> None:
    try:
        value = int_param({"n": [text]}, "n", lo, lo=lo, hi=hi)
    except ParamError as exc:
        assert exc.status == 400
        return
    assert lo <= value <= hi


@settings(max_examples=500, deadline=None)
@given(st.text(max_size=40))
def test_property_a_float_param_never_returns_nan_inf_or_out_of_range(text: str) -> None:
    try:
        value = float_param({"x": [text]}, "x", 0.0, RATE)
    except ParamError:
        return
    assert math.isfinite(value)
    assert RATE.lo <= value <= RATE.hi


@settings(max_examples=300, deadline=None)
@given(st.binary(max_size=300))
def test_property_parse_query_never_raises_anything_but_param_error(raw: bytes) -> None:
    try:
        result = parse_query(raw)
    except ParamError as exc:
        assert exc.status in (400, 414)
        return
    assert isinstance(result, dict)
