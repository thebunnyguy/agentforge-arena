"""Visible tests: the agent's feedback signal (NOT scored).

These are deliberately weak — they only check basic store/retrieve with no
overflow — so they say nothing about eviction order or recency. The hidden
tests are what actually grade the implementation.
"""

from cachekit import LRUCache


def test_put_then_get_returns_value():
    c = LRUCache(2)
    c.put("a", 1)
    assert c.get("a") == 1


def test_get_missing_returns_default():
    c = LRUCache(2)
    assert c.get("nope") is None
