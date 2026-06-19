"""Regression tests: pre-existing behavior that must keep working. These pass on
the unmodified snapshot AND after a correct fix; a change that breaks them fails
the regression gate (G=0). They exercise only the stable sibling ``is_blank``."""

from htmlesc import is_blank


def test_is_blank_empty():
    assert is_blank("") is True


def test_is_blank_spaces():
    assert is_blank("   ") is True


def test_is_blank_whitespace_chars():
    assert is_blank("\t\n") is True


def test_is_blank_false():
    assert is_blank(" x ") is False
