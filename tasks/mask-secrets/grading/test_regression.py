"""Regression tests: pre-existing behavior that must keep working. These pass on
the unmodified snapshot AND after the feature is implemented; a change that
breaks them fails the regression gate (G=0). They exercise only the stable
sibling ``count_lines``."""

from maskkit import count_lines


def test_count_lines_empty():
    assert count_lines("") == 0


def test_count_lines_single():
    assert count_lines("a") == 1


def test_count_lines_two():
    assert count_lines("a\nb") == 2


def test_count_lines_trailing_newline():
    assert count_lines("a\nb\n") == 2
