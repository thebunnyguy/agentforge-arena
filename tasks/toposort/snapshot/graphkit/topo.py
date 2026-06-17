class CycleError(Exception):
    """Raised when the graph contains a cycle and cannot be topologically sorted."""


def toposort(graph):
    """Return a dependency-respecting ordering of the nodes in ``graph``.

    ``graph`` maps each node to the list of nodes it DEPENDS ON. The returned
    list must place every dependency before the dependents that require it. When
    several nodes are simultaneously eligible, they must be emitted in
    lexicographic order so the result is deterministic. Any cycle (including a
    self-loop) must raise :class:`CycleError`.

    STUB: not implemented yet.
    """
    raise NotImplementedError("toposort is not implemented yet")
