"""Regression tests: pre-existing behavior that must keep working. These cover
the stable sibling ``is_sorted_desc`` (already correct in the snapshot). They
pass on the unmodified snapshot AND after a correct implementation."""

from topk import is_sorted_desc


def test_descending_is_sorted():
    assert is_sorted_desc([5, 3, 3, 1]) is True


def test_strictly_descending():
    assert is_sorted_desc([9, 4, 0, -2]) is True


def test_ascending_is_not_sorted_desc():
    assert is_sorted_desc([1, 2, 3]) is False


def test_empty_is_sorted():
    assert is_sorted_desc([]) is True


def test_single_is_sorted():
    assert is_sorted_desc([42]) is True


def test_equal_elements_are_sorted_desc():
    assert is_sorted_desc([7, 7, 7]) is True
