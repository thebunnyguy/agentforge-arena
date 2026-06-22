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


def test_inner_dots_allowed():
    # ".." is traversal only as a whole path component; as a substring of an
    # ordinary name it is a legitimate filename and must be returned unchanged
    # (a `".." in name` substring check would wrongly reject these).
    assert safe_name("safe..file") == "safe..file"
    assert safe_name("my..report.txt") == "my..report.txt"
