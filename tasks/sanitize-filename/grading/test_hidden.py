"""Hidden tests: the graded correctness signal. Never mounted in the agent
workspace. The rejection cases fail with the pass-through snapshot and pass only
with an implementation that rejects unsafe filenames."""

import pytest

from safename import safe_name


def test_plain_name_unchanged():
    assert safe_name("report.txt") == "report.txt"


def test_other_plain_name_unchanged():
    assert safe_name("data.csv") == "data.csv"


def test_traversal_raises():
    with pytest.raises(ValueError):
        safe_name("../etc/passwd")


def test_separator_raises():
    with pytest.raises(ValueError):
        safe_name("a/b")


def test_backslash_separator_raises():
    with pytest.raises(ValueError):
        safe_name("a\\b")


def test_empty_raises():
    with pytest.raises(ValueError):
        safe_name("")


def test_dotdot_raises():
    with pytest.raises(ValueError):
        safe_name("..")


def test_single_dot_raises():
    with pytest.raises(ValueError):
        safe_name(".")


def test_null_byte_raises():
    with pytest.raises(ValueError):
        safe_name("x\x00y")
