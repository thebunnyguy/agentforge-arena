"""Regression tests: pre-existing behavior that must keep working. These cover
the already-correct stable sibling ``is_number`` and pass on the unmodified
snapshot AND after a correct implementation of ``evaluate``; a change that
breaks them fails the regression gate (G=0)."""

from calckit import is_number


def test_is_number_accepts_integer():
    assert is_number("42") is True


def test_is_number_accepts_float():
    assert is_number("1.5") is True


def test_is_number_accepts_signed():
    assert is_number("-3") is True
    assert is_number("+0.25") is True


def test_is_number_rejects_non_numeric():
    assert is_number("abc") is False
    assert is_number("1+2") is False
    assert is_number("") is False
