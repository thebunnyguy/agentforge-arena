"""Regression tests: pre-existing behavior that must keep working. These pass on
the unmodified snapshot AND after a correct fix; a change that breaks them fails
the regression gate (G=0). They exercise only the stable sibling ``normalize``
and a trivial contract true in both snapshot and reference."""

from safepath import normalize, safe_join


def test_normalize_collapses_current_dir():
    assert normalize("a/./b/../c") == "a/c"


def test_normalize_collapses_double_slash():
    assert normalize("a//b/") == "a/b"


def test_normalize_leaves_clean_path():
    assert normalize("x/y/z") == "x/y/z"


def test_safe_join_returns_string_for_simple_case():
    assert isinstance(safe_join("/srv/data", "reports"), str)
