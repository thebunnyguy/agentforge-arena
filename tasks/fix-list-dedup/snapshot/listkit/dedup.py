def dedup(items):
    """Remove duplicate elements from ``items``.

    Should return a list containing each distinct element exactly once, in the
    order of first appearance.

    BUG: this implementation uses ``set`` and does not preserve order.
    """
    return list(set(items))
