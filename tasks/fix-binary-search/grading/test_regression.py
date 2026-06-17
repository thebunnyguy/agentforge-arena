"""Regression tests: pre-existing behavior that must keep working. These pass on
the unmodified snapshot AND after a correct fix; a change that breaks them fails
the regression gate (G=0). They exercise only the stable sibling is_sorted and a
trivial contract (return type) true in both snapshot and reference."""

from searchkit import bisect_left, is_sorted


def test_is_sorted_on_sorted():
    assert is_sorted([1, 2, 2, 3, 5]) is True


def test_is_sorted_on_unsorted():
    assert is_sorted([3, 1, 2]) is False


def test_is_sorted_on_empty_and_single():
    assert is_sorted([]) is True
    assert is_sorted([42]) is True


def test_bisect_left_returns_int():
    assert isinstance(bisect_left([1, 2, 3], 2), int)
