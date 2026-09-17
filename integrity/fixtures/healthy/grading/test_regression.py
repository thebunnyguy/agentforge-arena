"""Regression tests: pre-existing behavior that must keep working."""

from pkg import identity


def test_identity():
    assert identity(7) == 7
    assert identity("x") == "x"
