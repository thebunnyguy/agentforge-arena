"""Regression tests: pre-existing behavior that must keep working. These test
the stable sibling ``is_empty`` (and a trivial import contract true in both the
snapshot and the reference). They pass on the unmodified snapshot AND after a
correct implementation; a change that breaks them fails the regression gate."""

import inspect

from afirst import first_success, is_empty


def test_is_empty_true_for_empty_list():
    assert is_empty([]) is True


def test_is_empty_false_for_nonempty_list():
    assert is_empty([1]) is False


def test_is_empty_true_for_empty_tuple():
    assert is_empty(()) is True


def test_is_empty_false_for_nonempty_string():
    assert is_empty("x") is False


def test_first_success_is_a_coroutine_function():
    # Trivial contract true in both snapshot (stub) and reference: the public
    # entry point exists and is async. Calling it is left to the hidden suite.
    assert inspect.iscoroutinefunction(first_success)
