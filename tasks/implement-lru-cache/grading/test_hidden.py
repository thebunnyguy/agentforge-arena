"""Hidden tests: the graded correctness signal. Never mounted in the agent
workspace. These fail on the stub (NotImplementedError / no eviction) and pass
only with a correct LRU implementation where both get and put refresh recency."""

from cachekit import LRUCache


def test_evicts_least_recently_used_on_overflow():
    c = LRUCache(2)
    c.put("a", 1)
    c.put("b", 2)
    c.put("c", 3)  # exceeds capacity -> "a" (LRU) evicted
    assert c.get("a") is None
    assert c.get("b") == 2
    assert c.get("c") == 3


def test_get_refreshes_recency_so_other_key_is_evicted():
    c = LRUCache(2)
    c.put("a", 1)
    c.put("b", 2)
    c.get("a")     # "a" is now most-recently-used
    c.put("c", 3)  # overflow -> "b" (now LRU) evicted, NOT "a"
    assert c.get("a") == 1
    assert c.get("b") is None
    assert c.get("c") == 3


def test_put_existing_key_updates_value_and_recency():
    c = LRUCache(2)
    c.put("a", 1)
    c.put("b", 2)
    c.put("a", 99)  # update value AND refresh recency of "a"
    c.put("c", 3)   # overflow -> "b" (LRU) evicted
    assert c.get("a") == 99
    assert c.get("b") is None
    assert c.get("c") == 3


def test_capacity_one_keeps_only_latest():
    c = LRUCache(1)
    c.put("a", 1)
    c.put("b", 2)  # overflow -> "a" evicted
    assert c.get("a") is None
    assert c.get("b") == 2


def test_get_missing_returns_provided_default():
    c = LRUCache(2)
    assert c.get("missing", "fallback") == "fallback"
    c.put("a", 1)
    assert c.get("a", "fallback") == 1
