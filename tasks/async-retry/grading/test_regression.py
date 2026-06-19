"""Regression tests: pre-existing behavior that must keep working. These test
the stable sibling ``clamp`` (and a trivial import contract true in both the
snapshot and the reference). They pass on the unmodified snapshot AND after a
correct implementation; a change that breaks them fails the regression gate."""

import inspect

import pytest

from aretry import clamp, retry_call


def test_clamp_below_low_returns_low():
    assert clamp(-5, 0, 10) == 0


def test_clamp_above_high_returns_high():
    assert clamp(99, 0, 10) == 10


def test_clamp_within_range_returns_value():
    assert clamp(4, 0, 10) == 4


def test_clamp_at_bounds_is_inclusive():
    assert clamp(0, 0, 10) == 0
    assert clamp(10, 0, 10) == 10


def test_clamp_rejects_inverted_bounds():
    with pytest.raises(ValueError):
        clamp(5, 10, 0)


def test_retry_call_is_a_coroutine_function():
    # Trivial contract true in both snapshot (stub) and reference: the public
    # entry point exists and is async. Calling it is left to the hidden suite.
    assert inspect.iscoroutinefunction(retry_call)
