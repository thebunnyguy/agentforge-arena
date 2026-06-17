import heapq


class CycleError(Exception):
    """Raised when the graph contains a cycle and cannot be topologically sorted."""


def toposort(graph):
    """Return a dependency-respecting ordering of the nodes in ``graph``.

    ``graph`` maps each node to the list of nodes it DEPENDS ON. The returned
    list places every dependency before the dependents that require it. When
    several nodes are simultaneously eligible, they are emitted in lexicographic
    order so the result is deterministic. Any cycle (including a self-loop)
    raises :class:`CycleError`.
    """
    # Collect every node, including those that appear only as a dependency.
    nodes = set(graph)
    for deps in graph.values():
        nodes.update(deps)

    # Build dependency sets and the reverse (dependents) adjacency, plus the
    # in-degree = number of unsatisfied dependencies for each node.
    deps_of = {n: set(graph.get(n, ())) for n in nodes}
    dependents = {n: [] for n in nodes}
    indegree = {n: 0 for n in nodes}
    for node, deps in deps_of.items():
        indegree[node] = len(deps)
        for dep in deps:
            dependents[dep].append(node)

    # Kahn's algorithm with a min-heap so ties resolve lexicographically.
    ready = [n for n in nodes if indegree[n] == 0]
    heapq.heapify(ready)

    order = []
    while ready:
        node = heapq.heappop(ready)
        order.append(node)
        for dependent in dependents[node]:
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                heapq.heappush(ready, dependent)

    if len(order) != len(nodes):
        raise CycleError("graph contains a cycle")
    return order
