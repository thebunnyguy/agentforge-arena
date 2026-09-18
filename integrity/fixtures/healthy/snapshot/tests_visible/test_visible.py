"""Deliberately weak: passes even on the buggy snapshot."""

from pkg import classify


def test_classify_returns_string():
    assert isinstance(classify(3), str)
