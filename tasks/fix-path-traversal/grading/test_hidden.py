"""Hidden tests: the graded correctness signal. Never mounted in the agent
workspace. The escape cases fail with the naive posixpath.join snapshot and pass
only with an implementation that enforces containment under ``base``."""

import posixpath

import pytest

from safepath import safe_join


def test_normal_nested_join():
    assert safe_join("/srv/data", "reports", "q1.csv") == "/srv/data/reports/q1.csv"


def test_dotdot_escape_raises():
    with pytest.raises(ValueError):
        safe_join("/srv/data", "../etc/passwd")


def test_absolute_component_raises():
    with pytest.raises(ValueError):
        safe_join("/srv/data", "/etc/passwd")


def test_deep_dotdot_escape_raises():
    with pytest.raises(ValueError):
        safe_join("/srv/data", "reports", "..", "..", "etc", "passwd")


def test_dotdot_within_base_allowed():
    # "reports/../public" normalizes to "public", which is still under base.
    result = safe_join("/srv/data", "reports", "..", "public", "index.html")
    assert result == "/srv/data/public/index.html"


def test_trailing_and_leading_slashes_handled():
    result = safe_join("/srv/data/", "reports/", "/q1.csv".lstrip("/"))
    assert result == "/srv/data/reports/q1.csv"


def test_result_is_always_under_base():
    base = "/srv/data"
    result = safe_join(base, "a", "b", "c.txt")
    norm_base = posixpath.normpath(base)
    norm_result = posixpath.normpath(result)
    assert norm_result == norm_base or norm_result.startswith(norm_base + "/")


def test_prefix_collision_sibling_raises():
    # A sibling directory sharing a name prefix ("/srv/data-other") is NOT under
    # "/srv/data". A startswith(base) check WITHOUT a trailing separator is the
    # bug this catches.
    with pytest.raises(ValueError):
        safe_join("/srv/data", "x", "..", "..", "data-other", "file.txt")


def test_root_base_allows_absolute_descendants():
    # base "/" contains every absolute path; joining under it must not raise.
    assert safe_join("/", "usr", "local", "bin") == "/usr/local/bin"
    assert safe_join("/", "etc", "passwd") == "/etc/passwd"
