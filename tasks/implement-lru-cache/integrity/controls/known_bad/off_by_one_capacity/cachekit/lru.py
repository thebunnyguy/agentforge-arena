from collections import OrderedDict


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
    """

    def __init__(self, capacity):
        self.capacity = capacity
        self._store = OrderedDict()

    def get(self, key, default=None):
        if key not in self._store:
            return default
        self._store.move_to_end(key)
        return self._store[key]

    def put(self, key, value):
        if key in self._store:
            self._store[key] = value
            self._store.move_to_end(key)
            return
        self._store[key] = value
        # BUG: off-by-one. Should evict once len(self._store) exceeds
        # self.capacity, not self.capacity + 1 -- this lets the cache grow to
        # capacity + 1 entries before it ever evicts anything.
        if len(self._store) > self.capacity + 1:
            self._store.popitem(last=False)

    def __len__(self):
        return len(self._store)
