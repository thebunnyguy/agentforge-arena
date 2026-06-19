"""Regression tests: pre-existing behavior that must keep working. These cover
the stable sibling ``is_positive_int`` (already correct in the snapshot). They
pass on the unmodified snapshot AND after a correct implementation."""

from gridpaths import is_positive_int


def test_positive():
    assert is_positive_int(5) is True


def test_one_is_positive():
    assert is_positive_int(1) is True


def test_zero_is_not_positive():
    assert is_positive_int(0) is False


def test_negative_is_not_positive():
    assert is_positive_int(-3) is False


def test_bool_is_not_accepted():
    assert is_positive_int(True) is False


def test_non_int_is_not_accepted():
    assert is_positive_int(2.5) is False
