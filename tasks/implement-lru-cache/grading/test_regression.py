"""Regression tests: pre-existing behavior that must keep working. These pass on
the unmodified snapshot AND after a correct implementation. They exercise the
stable sibling (clamp) plus trivial contracts true in both snapshot and
reference; a change that breaks them fails the regression gate (G=0)."""

from cachekit import LRUCache, clamp


def test_clamp_below_range():
    assert clamp(-5, 0, 10) == 0


def test_clamp_above_range():
    assert clamp(42, 0, 10) == 10


def test_clamp_within_range():
    assert clamp(7, 0, 10) == 7


def test_lrucache_constructs_with_capacity():
    c = LRUCache(3)
    assert c.capacity == 3
    assert len(c) == 0
