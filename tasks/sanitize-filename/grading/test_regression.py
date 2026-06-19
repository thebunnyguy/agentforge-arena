"""Regression tests: pre-existing behavior that must keep working. These pass on
the unmodified snapshot AND after a correct fix; a change that breaks them fails
the regression gate (G=0). They exercise only the stable sibling
``has_extension``."""

from safename import has_extension


def test_has_extension_simple():
    assert has_extension("report.txt", "txt") is True


def test_has_extension_with_leading_dot():
    assert has_extension("report.txt", ".txt") is True


def test_has_extension_case_insensitive():
    assert has_extension("Report.TXT", "txt") is True


def test_has_extension_false():
    assert has_extension("report.txt", "csv") is False
