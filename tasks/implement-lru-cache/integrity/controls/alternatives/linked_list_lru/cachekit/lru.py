class _Node:
    """One entry in the intrusive doubly linked list used for recency order."""

    __slots__ = ("key", "value", "prev", "next")

    def __init__(self, key=None, value=None):
        self.key = key
        self.value = value
        self.prev = None
        self.next = None


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

    Implementation note: recency is tracked with a hand-rolled doubly linked
    list (sentinel head/tail) instead of collections.OrderedDict. The node
    right after ``_head`` is the most-recently-used entry; the node right
    before ``_tail`` is the least-recently-used one.
    """

    def __init__(self, capacity):
        self.capacity = capacity
        self._store = {}
        self._head = _Node()
        self._tail = _Node()
        self._head.next = self._tail
        self._tail.prev = self._head

    def _unlink(self, node):
        node.prev.next = node.next
        node.next.prev = node.prev

    def _push_front(self, node):
        node.next = self._head.next
        node.prev = self._head
        self._head.next.prev = node
        self._head.next = node

    def _touch(self, node):
        self._unlink(node)
        self._push_front(node)

    def get(self, key, default=None):
        node = self._store.get(key)
        if node is None:
            return default
        self._touch(node)
        return node.value

    def put(self, key, value):
        node = self._store.get(key)
        if node is not None:
            node.value = value
            self._touch(node)
            return
        node = _Node(key, value)
        self._store[key] = node
        self._push_front(node)
        if len(self._store) > self.capacity:
            lru_node = self._tail.prev
            self._unlink(lru_node)
            del self._store[lru_node.key]

    def __len__(self):
        return len(self._store)
