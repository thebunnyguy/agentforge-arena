import heapq


class CycleError(Exception):
    """Raised when the graph contains a cycle and cannot be topologically sorted."""


def toposort(graph):
    """Return a dependency-respecting ordering of the nodes in ``graph``.

    BUG (realistic, known_bad control): for a node with more than one
    dependency, only the first entry in its dependency list is wired up; any
    further dependencies in the same list are silently dropped. Everything
    else (cycle detection, lexicographic min-heap tiebreak) matches the
    reference.
    """
    nodes = set(graph)
    for deps in graph.values():
        nodes.update(deps)

    deps_of = {}
    for n in nodes:
        raw = graph.get(n, ())
        # BUG: `raw[:1]` instead of the full list -- extra dependencies
        # beyond the first are never registered.
        deps_of[n] = set(raw[:1])

    dependents = {n: [] for n in nodes}
    indegree = {n: 0 for n in nodes}
    for node, deps in deps_of.items():
        indegree[node] = len(deps)
        for dep in deps:
            dependents[dep].append(node)

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
