class CycleError(Exception):
    """Raised when the graph contains a cycle and cannot be topologically sorted."""


def toposort(graph):
    """Return a dependency-respecting ordering of the nodes in ``graph``.

    Structurally different from the reference implementation: this is a
    depth-first postorder traversal (visit a node's dependencies first, then
    append the node itself once every dependency has been placed) instead of
    the reference's breadth-first Kahn's algorithm over a min-heap of ready
    nodes. Cycles are detected with the classic white/gray/black
    recursion-stack coloring: a back-edge to a GRAY (currently-on-stack) node
    means a cycle. Determinism is achieved by visiting nodes, and each node's
    own dependency list, in lexicographic order.
    """
    nodes = set(graph)
    for deps in graph.values():
        nodes.update(deps)

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in nodes}
    order = []

    def visit(node):
        color[node] = GRAY
        for dep in sorted(graph.get(node, ())):
            if color[dep] == WHITE:
                visit(dep)
            elif color[dep] == GRAY:
                raise CycleError("graph contains a cycle")
            # BLACK dependencies are already safely placed; nothing to do.
        color[node] = BLACK
        order.append(node)

    for node in sorted(nodes):
        if color[node] == WHITE:
            visit(node)

    return order
