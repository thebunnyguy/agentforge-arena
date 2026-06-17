def all_nodes(graph):
    """Return a sorted list of every node in ``graph``.

    Includes both the keys (nodes that declare dependencies) and any node that
    appears only inside a dependency list (i.e. has no entry of its own).
    """
    nodes = set(graph)
    for deps in graph.values():
        nodes.update(deps)
    return sorted(nodes)
