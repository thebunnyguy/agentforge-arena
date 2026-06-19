"""Visible tests: the agent's feedback signal (NOT scored).

These are deliberately weak — they only touch the happy path of an ok result —
so they say nothing about err behavior, unwrap_or, or map's no-op-on-err
contract. The hidden tests are what actually grade the implementation.
"""

from resultkit import Result


def test_ok_is_ok_true():
    assert Result.ok(1).is_ok is True


def test_ok_unwrap_returns_value():
    assert Result.ok(42).unwrap() == 42
