class LRUCache:
    """A fixed-capacity cache that evicts the least-recently-used entry.

    Contract:
      * ``LRUCache(capacity)`` holds at most ``capacity`` entries.
      * ``get(key, default=None)`` returns the stored value, or ``default`` if
        the key is absent. A successful ``get`` counts as a use and refreshes
        the key's recency.
      * ``put(key, value)`` inserts/updates a key. It counts as a use and
        refreshes recency. When inserting a NEW key would exceed capacity, the
        least-recently-used entry is evicted first.

    STUB: methods are not implemented yet. The backing store keeps no recency
    information and performs no eviction, so the cache grows without bound.
    """

    def __init__(self, capacity):
        self.capacity = capacity
        self._store = {}

    def get(self, key, default=None):
        raise NotImplementedError("LRUCache.get is not implemented yet")

    def put(self, key, value):
        raise NotImplementedError("LRUCache.put is not implemented yet")

    def __len__(self):
        return len(self._store)
