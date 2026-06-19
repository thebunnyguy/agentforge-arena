"""Regression tests: pre-existing behavior that must keep working. These test
the stable sibling ``is_positive`` (and a trivial import contract true in both
the snapshot and the reference). They pass on the unmodified snapshot AND after
a correct implementation; a change that breaks them fails the regression gate."""

import inspect

from atimeout import is_positive, with_timeout


def test_is_positive_true_for_positive():
    assert is_positive(3) is True


def test_is_positive_false_for_zero():
    assert is_positive(0) is False


def test_is_positive_false_for_negative():
    assert is_positive(-2) is False


def test_is_positive_handles_floats():
    assert is_positive(0.001) is True
    assert is_positive(-0.001) is False


def test_with_timeout_is_a_coroutine_function():
    # Trivial contract true in both snapshot (stub) and reference: the public
    # entry point exists and is async. Calling it is left to the hidden suite.
    assert inspect.iscoroutinefunction(with_timeout)
