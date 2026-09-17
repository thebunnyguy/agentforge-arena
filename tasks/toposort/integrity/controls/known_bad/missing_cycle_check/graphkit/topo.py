import heapq


class CycleError(Exception):
    """Raised when the graph contains a cycle and cannot be topologically sorted."""


def toposort(graph):
    """Return a dependency-respecting ordering of the nodes in ``graph``.

    BUG (realistic, known_bad control): Kahn's algorithm is implemented
    correctly for the acyclic case, including the lexicographic min-heap
    tiebreak, but the author forgot to verify that every node was actually
    emitted at the end. On a cyclic graph, nodes inside the cycle never reach
    indegree zero and are simply left out of the result -- no exception is
    raised and no infinite loop occurs, just a silently truncated, wrong
    answer.
    """
    nodes = set(graph)
    for deps in graph.values():
        nodes.update(deps)

    deps_of = {n: set(graph.get(n, ())) for n in nodes}
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

    # BUG: missing the "if len(order) != len(nodes): raise CycleError(...)"
    # check that the reference implementation has here.
    return order
