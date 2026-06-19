"""Regression tests: pre-existing behavior that must keep working. These cover
the stable sibling ``pair_sum`` (already correct in the snapshot) plus trivial
contracts true in both the snapshot and the reference. They pass on the
unmodified snapshot AND after a correct implementation."""

from twosum import pair_sum


def test_pair_sum_basic():
    assert pair_sum(2, 3) == 5


def test_pair_sum_negative():
    assert pair_sum(-4, 1) == -3


def test_pair_sum_zero():
    assert pair_sum(0, 0) == 0


def test_pair_sum_commutes():
    assert pair_sum(7, 11) == pair_sum(11, 7)
