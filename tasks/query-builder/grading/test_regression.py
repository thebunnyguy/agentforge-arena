"""Regression tests: pre-existing behavior that must keep working. These pass on
the unmodified snapshot AND after a correct implementation. They exercise the
stable sibling (quote_ident); a change that breaks them fails the regression
gate (G=0)."""

from qbuild import quote_ident


def test_quote_ident_simple():
    assert quote_ident("a") == '"a"'


def test_quote_ident_escapes_embedded_quote():
    assert quote_ident('a"b') == '"a""b"'


def test_quote_ident_empty():
    assert quote_ident("") == '""'
