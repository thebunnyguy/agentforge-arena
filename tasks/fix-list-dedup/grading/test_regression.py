"""Regression tests: pre-existing behavior that must keep working. These pass on
the unmodified snapshot AND after a correct fix; a change that breaks them fails
the regression gate (G=0)."""

from listkit import dedup, flatten


def test_flatten_unchanged():
    assert flatten([[1, 2], [3], []]) == [1, 2, 3]


def test_dedup_still_removes_duplicates():
    out = dedup([1, 1, 2, 2, 2, 3])
    assert isinstance(out, list)
    assert sorted(out) == [1, 2, 3]
