"""Regression tests: pre-existing behavior that must keep working. These pass on
the unmodified snapshot AND after a correct implementation; a change that breaks
them fails the regression gate (G=0).

They exercise only the stable sibling ``contains`` and trivial ``merge``
contracts true in both the stub and the reference."""

from intervalkit import merge, contains


def test_contains_point_inside():
    assert contains((1, 5), 3) is True


def test_contains_endpoints_inclusive():
    assert contains((1, 5), 1) is True
    assert contains((1, 5), 5) is True


def test_contains_point_outside():
    assert contains((1, 5), 0) is False
    assert contains((1, 5), 6) is False


def test_merge_returns_list():
    assert isinstance(merge([(1, 3)]), list)


def test_merge_empty_is_empty():
    assert merge([]) == []
