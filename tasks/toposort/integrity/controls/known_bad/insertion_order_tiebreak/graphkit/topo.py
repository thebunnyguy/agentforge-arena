from collections import deque


class CycleError(Exception):
    """Raised when the graph contains a cycle and cannot be topologically sorted."""


def toposort(graph):
    """Return a dependency-respecting ordering of the nodes in ``graph``.

    BUG (realistic, known_bad control): dependencies are respected and cycles
    are correctly detected, but ties among simultaneously-eligible nodes are
    broken by first-seen (insertion) order -- the order nodes are encountered
    while scanning ``graph`` -- rather than lexicographic order. A plain FIFO
    queue is used instead of a min-heap, so nothing sorts the ready set.
    """
    nodes = []
    seen = set()
    for node, deps in graph.items():
        if node not in seen:
            nodes.append(node)
            seen.add(node)
        for dep in deps:
            if dep not in seen:
                nodes.append(dep)
                seen.add(dep)

    deps_of = {n: list(graph.get(n, ())) for n in nodes}
    dependents = {n: [] for n in nodes}
    indegree = {n: 0 for n in nodes}
    for node, deps in deps_of.items():
        indegree[node] = len(deps)
        for dep in deps:
            dependents[dep].append(node)

    # BUG: FIFO order of first appearance, not a lexicographically-sorted
    # min-heap, decides how ties are broken.
    ready = deque(n for n in nodes if indegree[n] == 0)

    order = []
    while ready:
        node = ready.popleft()
        order.append(node)
        for dependent in dependents[node]:
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                ready.append(dependent)

    if len(order) != len(nodes):
        raise CycleError("graph contains a cycle")
    return order
