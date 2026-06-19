"""Regression tests: pre-existing behavior that must keep working. These pass on
the unmodified snapshot AND after a correct implementation. They exercise the
stable sibling (identity); a change that breaks them fails the regression gate
(G=0)."""

from resultkit import identity


def test_identity_returns_same_int():
    assert identity(7) == 7


def test_identity_returns_same_object():
    obj = object()
    assert identity(obj) is obj


def test_identity_on_list():
    xs = [1, 2, 3]
    assert identity(xs) is xs
