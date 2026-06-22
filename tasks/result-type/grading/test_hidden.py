"""Hidden tests: the graded correctness signal. Never mounted in the agent
workspace. These fail on the stub (NotImplementedError) and pass only with a
correct Result implementation, including map's no-op-without-calling-fn
behavior on err results."""

import pytest

from resultkit import Result


def test_ok_is_ok_true():
    assert Result.ok(5).is_ok is True


def test_err_is_ok_false():
    assert Result.err("boom").is_ok is False


def test_ok_unwrap_returns_value():
    assert Result.ok("hello").unwrap() == "hello"


def test_err_unwrap_raises_value_error():
    with pytest.raises(ValueError):
        Result.err("boom").unwrap()


def test_err_unwrap_or_returns_default():
    assert Result.err("boom").unwrap_or(7) == 7


def test_ok_unwrap_or_returns_value():
    assert Result.ok(3).unwrap_or(99) == 3


def test_ok_map_transforms_value():
    r = Result.ok(10).map(lambda x: x + 1)
    assert r.is_ok is True
    assert r.unwrap() == 11


def test_err_map_stays_err_without_calling_fn():
    calls = []

    def fn(x):
        calls.append(x)
        return x

    r = Result.err("boom").map(fn)
    assert r.is_ok is False
    assert calls == []
    assert r.unwrap_or("fallback") == "fallback"


def test_ok_with_falsy_value_unwraps_to_that_value():
    # unwrap_or must branch on ok-ness, not on the truthiness of the value:
    # ok(0)/ok(None)/ok(False) are successes and must return the stored value.
    assert Result.ok(0).unwrap_or(99) == 0
    assert Result.ok(None).unwrap() is None
    assert Result.ok(False).unwrap_or("default") is False
