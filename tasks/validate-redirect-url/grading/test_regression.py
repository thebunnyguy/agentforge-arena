"""Regression tests: pre-existing behavior that must keep working. These pass on
the unmodified snapshot AND after a correct fix; a change that breaks them fails
the regression gate (G=0). They exercise only the stable sibling ``is_https``."""

from saferedirect import is_https


def test_is_https_true():
    assert is_https("https://example.com/x") is True


def test_is_https_false_for_http():
    assert is_https("http://example.com/x") is False


def test_is_https_false_for_relative():
    assert is_https("/relative") is False
